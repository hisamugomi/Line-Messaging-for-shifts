import os
import pandas as pd
import requests
import json
import logging
from flask import Flask, request, render_template, jsonify, flash, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import sqlite3


load_dotenv()

# Configure logging for better debugging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-for-dev")

# Configuration
LINE_API_URL = "https://api.line.me/v2/bot/message/push"
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
DATABASE = 'employees.db'

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_db():
    """Create the database and tables if they don't exist."""
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                line_user_id TEXT PRIMARY KEY,
                employee_name TEXT NOT NULL UNIQUE
            )
        """)
        conn.commit()

def get_line_token():
    """Get LINE API token from environment variables."""
    return os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_CHANNEL_ACCESS_TOKEN")

required_columns = ['employee_name', 'shift_date', 'start_time', 'end_time']
def validate_excel_data(df):
    """Validate that the Excel file has required columns."""
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        return False, f"Missing required columns: {', '.join(missing_columns)}"
    
    # Check for empty rows
    if df[required_columns].isnull().any(axis=1).any():
        logging.warning(f"Found {empty_rows} rows with missing data")
    
    return True, "Valid data structure"

def send_line_message(line_user_id, message_body):
    """Send a message to a specific LINE user ID using the LINE Messaging API."""
    token = get_line_token()
    
    if token == "YOUR_CHANNEL_ACCESS_TOKEN":
        logging.error("LINE API token not configured properly")
        return False, "LINE API token not configured"
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    payload = {
        'to': line_user_id,
        'messages': [
            {
                'type': 'text',
                'text': message_body
            }
        ]
    }
    
    try:
        response = requests.post(LINE_API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        return True, "Message sent successfully"
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send message to {line_user_id}: {e}")
        return False, f"Failed to send message: {e}"

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle Excel file upload and validation."""    
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'})
        
        if not allowed_file (file.filename):
            return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload .xlsx or .xls files only.'})
        
        # Read Excel file
        df = pd.read_excel(file)
        
        # Validate data structure
        is_valid, message = validate_excel_data(df)
        if not is_valid:
            return jsonify({'status': 'error', 'message': message})
        
        # Clean and prepare data
        df = df.dropna(subset=['employee_name', 'shift_date', 'start_time', 'end_time'])
        
        if df.empty:
            return jsonify({'status': 'error', 'message': 'No valid data found in the uploaded file'})
        
        preview_data = [
            {
                'employee_name': str(row['employee_name']),
                'line_user_id': str(row['line_user_id']),
                'shift_date': str(row['shift_date']).split(' ')[0],
                'start_time': str(row['start_time']),
                'end_time': str(row['end_time'])
            } for row in df.to_dict('records')
        ]
        
        return jsonify({
            'status': 'success', 
            'message': f'Successfully uploaded and validated {len(preview_data)} records',
            'data': preview_data
        })
        
    except Exception as e:
        logging.error(f"Error processing file upload: {e}")
        return jsonify({'status': 'error', 'message': f'Error processing file: {str(e)}'})

@app.route('/send_messages', methods=['POST'])
def send_messages():
    """Send LINE messages to all employees in the uploaded data."""
    
    try:
        data = request.get_json()

        if not data or 'data' not in data:
            return jsonify({'status': 'error','message':'No data'})

        data = data.get('data', [])
        if not data:
            logging.error("No data provided in send_messages")
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400
        logging.info(f"Received data: {data}")

        if not all(all(key in item for key in required_columns) for item in data):
            logging.error("Missing required keys in data")
            return jsonify({'status': 'error', 'message': 'Data missing required keys: employee_name, shift_date, start_time, end_time'}), 400
        
        df = pd.DataFrame(data)
        
        if 'employee_name' not in df.columns:
            logging.error("employee_name column missing in DataFrame")
            return jsonify({'status': 'error', 'message': 'employee_name column missing in data'}), 400
        
        grouped_shifts = df.groupby('employee_name')
        successful_sends = 0
        failed_sends = 0
        errors = []
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT employee_name, line_user_id FROM users")
            registered_users = dict(cursor.fetchall())

        for name, shifts in grouped_shifts:
            line_user_id = registered_users.get(name)
        
            if not line_user_id:
                error_msg = f"User '{name}' not found in database"
                logging.error(error_msg)
                failed_sends += 1
                errors.append(error_msg)
                continue

                # Create personalized message
            message_body = f"Hello {name}, Your shifts have been scheduled for:"

            for index, row in shifts.iterrows():
                    shift_info = f"Date: {row['shift_date']}"

                    if row['start_time'] and row['end_time']:
                        shift_info += f", {row['start_time']} - {row['end_time']}"
                    elif row['start_time'] == '出勤':
                        shift_info += f", Time: {row['start_time']}"
                        
                    if 'place' in row and pd.notna(row['place']):
                        shift_info += f" {row['place']}"

                    message_body += f"- {shift_info}\n"

            message_body += "\n 宜しくおねがいします"

                    
                    # Send message
            success, error_msg = send_line_message(line_user_id, message_body)
                    
            if success:
                        successful_sends += 1
            else:
                        failed_sends += 1
                        # errors.append(f"{name}: {error_msg}")
            
        # Clear uploaded data after processing
        total_processed = successful_sends + failed_sends
        UPLOADED_DATA = None
        
        # Prepare response
        if failed_sends == 0:
            return jsonify({
                'status': 'success',
                'message': f'Successfully sent {successful_sends} messages to all employees!'
            })
        elif successful_sends == 0:
            return jsonify({
                'status': 'error',
                'message': f'Failed to send all {failed_sends} messages. Please check your LINE API configuration.',
                'errors': errors[:5]  # Limit error messages to avoid overwhelming the user
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': f'Sent {successful_sends} of {total_processed} messages. {failed_sends} failed.',
                'errors': errors[:5]
            })
    except Exception as e:
        logging.error(f"Error sending messages: {e}")
        return jsonify({'status': 'error', 'message': f'Error: {str(e)}'})

@app.route('/webhook', methods=['POST'])
def webhook():

    """LINE webhook to capture user IDs when users message the bot."""
    try:
        body = request.get_json()
        logging.info(f"Webhook received: {body}")

        for event in body.get('events', []):
                if event['type'] == 'message' and event['message']['type'] == 'text':
                    user_id = event['source']['userId']
                    user_message = event['message']['text'].strip()
                    with sqlite3.connect(DATABASE) as conn:
                        cursor = conn.cursor()

                        cursor.execute("SELECT employee_name FROM users WHERE line_user_id = ?", (user_id,))
                        existing_user = cursor.fetchone()

                        if existing_user: # User already registered
                            message = f"You are already registered as {existing_user[0]}."
                        elif user_message.lower() == 'register':
                            #User is starting registration process
                            message = "Please reply with your full name to register"
                        else: #Save user's ID and Name
                            try: 
                                cursor.execute("INSERT INTO users (line_user_id, employee_name) VALUES (?, ?)", (user_id, user_message))
                                conn.commit()
                                message = f"Thank you {user_message}! You have been registered."
                                logging.info(f"new user registered {user_message} with ID {user_id}")
                            except sqlite3.IntegrityError:
                                message = f"Sorry the name '{user_message}' is already taken."
                        send_line_message(user_id, message)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.errorhandler(404)
def not_found(error):
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Internal server error: {error}")
    return jsonify({'status': 'error', 'message': 'Internal server error occurred'}), 500


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
