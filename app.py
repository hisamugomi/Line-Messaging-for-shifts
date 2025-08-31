import os
import pandas as pd
import requests
import json
import logging
from flask import Flask, request, render_template, jsonify, flash, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

# Configure logging for better debugging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-for-dev")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configuration
LINE_API_URL = "https://api.line.me/v2/bot/message/push"
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global variable to store uploaded data temporarily
UPLOADED_DATA = None

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_line_token():
    """Get LINE API token from environment variables."""
    return os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_CHANNEL_ACCESS_TOKEN")

def validate_excel_data(df):
    """Validate that the Excel file has required columns."""
    required_columns = ['employee_name', 'line_user_id', 'shift_date', 'start_time', 'end_time']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        return False, f"Missing required columns: {', '.join(missing_columns)}"
    
    # Check for empty rows
    empty_rows = df[required_columns].isnull().any(axis=1).sum()
    if empty_rows > 0:
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
        logging.info(f"Message sent successfully to {line_user_id}")
        return True, "Message sent successfully"
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error: {e}"
        try:
            if response.text:
                error_msg += f" - Response: {response.text}"
        except:
            pass
        logging.error(error_msg)
        return False, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Request error: {e}"
        logging.error(error_msg)
        return False, error_msg

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle Excel file upload and validation."""
    global UPLOADED_DATA
    
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
        df = df.dropna(subset=['employee_name', 'line_user_id', 'shift_date', 'start_time', 'end_time'])
        
        if df.empty:
            return jsonify({'status': 'error', 'message': 'No valid data found in the uploaded file'})
        
        # Store data globally for later use
        UPLOADED_DATA = df.to_dict('records')
        
        # Prepare preview data
        preview_data = []
        for row in UPLOADED_DATA:
            preview_data.append({
                'employee_name': str(row['employee_name']),
                'line_user_id': str(row['line_user_id']),
                'shift_date': str(row['shift_date']).split(' ')[0],  # Remove time part if present
                'start_time': str(row['start_time']),
                'end_time': str(row['end_time'])
            })
        
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
    global UPLOADED_DATA
    
    if not UPLOADED_DATA:
        return jsonify({'status': 'error', 'message': 'No data available. Please upload a file first.'})
    
    successful_sends = 0
    failed_sends = 0
    errors = []
    
    for row in UPLOADED_DATA:
        try:
            # Create personalized message
            message_body = (
                f"Hello {row['employee_name']},\n\n"
                f"Your shift has been scheduled for:\n"
                f"Date: {str(row['shift_date']).split(' ')[0]}\n"
                f"Time: {row['start_time']} - {row['end_time']}\n\n"
                f"Thank you for your hard work!"
            )
            
            # Send message
            success, error_msg = send_line_message(row['line_user_id'], message_body)
            
            if success:
                successful_sends += 1
            else:
                failed_sends += 1
                errors.append(f"{row['employee_name']}: {error_msg}")
                
        except Exception as e:
            failed_sends += 1
            error_msg = f"{row.get('employee_name', 'Unknown')}: {str(e)}"
            errors.append(error_msg)
            logging.error(f"Error sending message: {error_msg}")
    
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

@app.route('/clear_data', methods=['POST'])
def clear_data():
    """Clear uploaded data."""
    global UPLOADED_DATA
    UPLOADED_DATA = None
    return jsonify({'status': 'success', 'message': 'Data cleared successfully'})

@app.route('/webhook', methods=['POST'])
def webhook():
    """LINE webhook to capture user IDs when users message the bot."""
    try:
        body = request.get_json()
        logging.info(f"Webhook received: {body}")
        
        if 'events' in body:
            for event in body['events']:
                if event['type'] == 'message':
                    user_id = event['source']['userId']
                    logging.info(f"FOUND USER ID: {user_id}")
                    return jsonify({'status': 'success', 'message': f'User ID captured: {user_id}'})
        
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
    app.run(host='0.0.0.0', port=5000, debug=True)
