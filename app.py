import os
import pandas as pd
import requests
import json
import logging
import re
from flask import Flask, request, render_template, jsonify, flash, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import sqlite3
try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    logging.warning("Google AI not available - AI responses disabled")


load_dotenv()

# Configure logging for better debugging
logging.basicConfig(level=logging.DEBUG)

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-for-dev")

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'このページにアクセスするにはログインが必要です。'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    # For simplicity, we'll use a single admin user
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    if user_id == admin_username:
        return User(user_id, admin_username)
    return None

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,  -- 'user' or 'assistant'
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (line_user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shift_confirmations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                employee_name TEXT NOT NULL,
                confirmed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                week_start DATE NOT NULL,
                status TEXT DEFAULT 'confirmed',
                FOREIGN KEY (user_id) REFERENCES users (line_user_id)
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
        logging.error("Some rows in Excel file have missing data")
        return False, "Some rows have missing data"
    logging.info(f"Excel file columns: {list(df.columns)}")
    
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

def generate_ai_response(user_message, user_id=None, context="general"):
    """Generate AI response using Google Gemini with conversation history."""
    if not AI_AVAILABLE:
        return get_fallback_response(user_message, context)

    try:
        api_key = os.getenv("GOOGLE_AI_API_KEY")
        if not api_key:
            return get_fallback_response(user_message, context)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        system_prompt = """あなたはシフト管理アシスタントです。
        日本語で丁寧に、役立つ応答をしてください。

        重要: シフト情報について質問された場合、絶対に架空の情報をでっち上げないでください。
        実際のシフトデータがない場合は、正直に「現在シフト情報がありません」と伝えてください。

        対応できること:
        - ユーザー登録の案内
        - シフト変更依頼の受付（マネージャーに通知）
        - 一般的な質問への回答
        - システムの使い方の説明

        対応できないこと:
        - 実際のシフトスケジュールの表示（データがないため）
        - 架空のシフト情報の作成
        - 未来のシフトの予測

        会話の文脈を理解して、自然な会話を続けてください。
        応答は簡潔に、200文字以内で収めてください。"""

        # Build conversation history
        conversation_history = ""
        if user_id:
            history = get_conversation_history(user_id, limit=8)  # Get last 8 messages
            if history:
                conversation_history = "\n".join([
                    f"{'ユーザー' if role == 'user' else 'アシスタント'}: {message}"
                    for role, message in history
                ])
                conversation_history = f"\n\n会話履歴:\n{conversation_history}\n"

        full_prompt = f"{system_prompt}{conversation_history}\n\n現在のユーザー: {user_message}"

        response = model.generate_content(full_prompt)
        ai_response = response.text.strip()

        # Ensure response is not too long
        if len(ai_response) > 200:
            ai_response = ai_response[:197] + "..."

        return ai_response

    except Exception as e:
        logging.error(f"AI response generation failed: {e}")
        return get_fallback_response(user_message, context)

def get_fallback_response(user_message, context):
    """Fallback responses when AI is not available."""
    if "登録" in user_message.lower():
        return "登録を開始するには「登録」と入力してください。"
    elif any(word in user_message.lower() for word in ["変更", "修正", "update", "change"]):
        return "シフトの変更をご希望の場合は、田野義和マネージャーに直接ご連絡ください。"
    else:
        return "こんにちは！シフト管理アシスタントです。何かお手伝いできることはありますか？"

def validate_and_format_name(name):
    """Validate and format employee name."""
    if not name or len(name.strip()) < 2:
        return None, "名前が短すぎます。2文字以上で入力してください。"

    # Remove extra spaces and normalize
    formatted_name = re.sub(r'\s+', '', name.strip())

    # Check for invalid characters (allow Japanese, English, spaces originally)
    if not re.match(r'^[a-zA-Zぁ-ゖァ-ヾ一-龯\s]+$', name.strip()):
        return None, "名前には文字とスペースのみを使用してください。"

    # Check length
    if len(formatted_name) > 20:
        return None, "名前が長すぎます。20文字以内で入力してください。"

    return formatted_name, None

def notify_manager_schedule_change(user_id, user_name, change_request):
    """Notify manager about schedule change request."""
    manager_id = os.getenv("MANAGER_LINE_ID")  # 田野義和's LINE ID
    if not manager_id:
        logging.warning("Manager LINE ID not configured")
        return

    message = f"""🔔 シフト変更依頼

従業員: {user_name}
LINE ID: {user_id}
依頼内容: {change_request}

対応をお願いします。"""

    send_line_message(manager_id, message)

def is_schedule_change_request(message):
    """Check if message is a schedule change request."""
    change_keywords = [
        "変更", "修正", "update", "change", "シフト変更",
        "休み", "代わって", "代行", "入れ替え"
    ]
    return any(keyword in message.lower() for keyword in change_keywords)

def is_shift_inquiry(message):
    """Check if user is asking about actual shift information."""
    inquiry_keywords = [
        "シフトは", "今週のシフト", "来週のシフト", "今日のシフト", "明日のシフト",
        "shift", "schedule", "勤務", "出勤", "何時から", "いつ"
    ]
    return any(keyword in message.lower() for keyword in inquiry_keywords)

def is_shift_confirmation(message):
    """Check if user is confirming their shift."""
    confirmation_keywords = [
        "確認", "確認しました", "了解", "わかりました", "承知しました",
        "confirm", "acknowledged", "understood", "roger", "ok"
    ]
    return any(keyword in message.lower() for keyword in confirmation_keywords)

def record_shift_confirmation(user_id, user_name):
    """Record that a user has confirmed their shift."""
    try:
        from datetime import datetime, timedelta

        # Calculate the start of the current week (Monday)
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())  # Monday of current week
        week_start_date = week_start.date()

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Check if already confirmed this week
            cursor.execute("""
                SELECT id FROM shift_confirmations
                WHERE user_id = ? AND week_start = ? AND status = 'confirmed'
            """, (user_id, week_start_date))

            existing = cursor.fetchone()

            if existing:
                return False, "この週のシフトは既に確認済みです。"

            # Record the confirmation
            cursor.execute("""
                INSERT INTO shift_confirmations (user_id, employee_name, week_start, status)
                VALUES (?, ?, ?, 'confirmed')
            """, (user_id, user_name, week_start_date))

            conn.commit()

            # Notify manager about the confirmation
            notify_manager_confirmation(user_id, user_name, week_start_date)

            logging.info(f"Shift confirmed by {user_name} for week starting {week_start_date}")
            return True, f"{user_name}さんの今週のシフト確認が完了しました。"

    except Exception as e:
        logging.error(f"Error recording shift confirmation: {e}")
        return False, "確認の記録中にエラーが発生しました。"

def notify_manager_confirmation(user_id, user_name, week_start):
    """Notify manager about shift confirmation."""
    manager_id = os.getenv("MANAGER_LINE_ID")
    if not manager_id:
        logging.warning("Manager LINE ID not configured for confirmations")
        return

    message = f"""✅ シフト確認完了

従業員: {user_name}
確認日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
対象週: {week_start.strftime('%Y-%m-%d')} 開始

シフト確認が完了しました。"""

    send_line_message(manager_id, message)

def get_shift_confirmations():
    """Get all shift confirmations for display."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sc.employee_name, sc.confirmed_at, sc.week_start, sc.status,
                       u.line_user_id
                FROM shift_confirmations sc
                JOIN users u ON sc.user_id = u.line_user_id
                ORDER BY sc.confirmed_at DESC
                LIMIT 100
            """)

            confirmations = []
            for row in cursor.fetchall():
                confirmations.append({
                    'employee_name': row[0],
                    'confirmed_at': row[1],
                    'week_start': row[2],
                    'status': row[3],
                    'line_user_id': row[4]
                })

            return confirmations

    except Exception as e:
        logging.error(f"Error retrieving shift confirmations: {e}")
        return []

def get_shift_response(user_name):
    """Provide appropriate response for shift inquiries."""
    return f"""{user_name}さん、シフト情報についてですね。

申し訳ありませんが、現在システムにあなたのシフトデータが登録されていません。

シフト情報が必要な場合は：
1. 田野義和マネージャーに直接お問い合わせください
2. または、管理者からシフト通知が届くまでお待ちください

シフトの変更依頼がある場合は、「変更」とメッセージを送ってください。"""

def store_conversation(user_id, role, message):
    """Store conversation message in database."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (user_id, role, message)
                VALUES (?, ?, ?)
            """, (user_id, role, message))
            conn.commit()

            # Keep only last 20 messages per user to avoid database bloat
            cursor.execute("""
                DELETE FROM conversations
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM conversations
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 20
                )
            """, (user_id, user_id))
            conn.commit()

    except Exception as e:
        logging.error(f"Error storing conversation: {e}")

def get_conversation_history(user_id, limit=10):
    """Get recent conversation history for a user."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, message FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))

            # Reverse to get chronological order (oldest first)
            rows = cursor.fetchall()
            return list(reversed(rows))

    except Exception as e:
        logging.error(f"Error retrieving conversation history: {e}")
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "password")

        if username == admin_username and password == admin_password:
            user = User(username, username)
            login_user(user)
            flash('ログインに成功しました。', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('ユーザー名またはパスワードが間違っています。', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Handle user logout."""
    logout_user()
    flash('ログアウトしました。', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """Render the main page."""
    confirmations = get_shift_confirmations()
    return render_template('index.html', confirmations=confirmations)

@app.route('/api/confirmations')
@login_required
def get_confirmations_api():
    """API endpoint to get shift confirmations."""
    confirmations = get_shift_confirmations()
    return jsonify(confirmations)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle Excel file upload and validation."""    
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'})
        
        if not allowed_file(file.filename):
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
            message_body = f"{name}さん、以下のシフトが予定されています：\n\n"

            for index, row in shifts.iterrows():
                    shift_info = f"日付: {row['shift_date']}"

                    if row['start_time'] and row['end_time']:
                        shift_info += f", {row['start_time']} - {row['end_time']}"
                    elif row['start_time'] == '出勤':
                        shift_info += f", 時間: {row['start_time']}"

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

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Enhanced LINE webhook with AI responses and structured registration."""
    if request.method == 'GET':
        # LINE webhook verification
        return "Webhook endpoint is active", 200
    try:
        # Log the raw request for debugging
        logging.info(f"Webhook headers: {dict(request.headers)}")
        logging.info(f"Webhook method: {request.method}")
        logging.info(f"Webhook content type: {request.content_type}")

        # Ensure we have JSON data
        if not request.is_json:
            logging.error("Request is not JSON")
            return jsonify({'status': 'error', 'message': 'Invalid content type'}), 400

        body = request.get_json()
        if not body:
            logging.error("No JSON body received")
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        logging.info(f"Webhook received body: {body}")

        # Validate LINE webhook structure
        if 'events' not in body:
            logging.error("No events in webhook body")
            return jsonify({'status': 'error', 'message': 'Invalid webhook format'}), 400

        events = body.get('events', [])
        if not events:
            logging.info("No events to process")
            return jsonify({'status': 'success'}), 200

        # Process each event
        for event in events:
            try:
                if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                    user_id = event.get('source', {}).get('userId')
                    user_message = event.get('message', {}).get('text', '').strip()

                    if not user_id:
                        logging.error("No user ID in event")
                        continue

                    if not user_message:
                        logging.info("Empty message received")
                        continue

                    logging.info(f"Processing message from {user_id}: {user_message}")

                    # Process the message
                    message = process_user_message(user_id, user_message)

                    # Send response (don't fail webhook if message send fails)
                    try:
                        send_line_message(user_id, message)
                        logging.info(f"Response sent to {user_id}")
                    except Exception as send_error:
                        logging.error(f"Failed to send message to {user_id}: {send_error}")

            except Exception as event_error:
                logging.error(f"Error processing event: {event_error}")
                continue

        # Always return success for webhook verification
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        # Return 200 even on error to prevent webhook verification failures
        return jsonify({'status': 'error', 'message': 'Internal error occurred'}), 200

def process_user_message(user_id, user_message):
    """Process user message and return appropriate response."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Check if user is already registered
            cursor.execute("SELECT employee_name FROM users WHERE line_user_id = ?", (user_id,))
            existing_user = cursor.fetchone()

            if existing_user:
                user_name = existing_user[0]

                # Store user message
                store_conversation(user_id, 'user', user_message)

                # Handle schedule change requests
                if is_schedule_change_request(user_message):
                    notify_manager_schedule_change(user_id, user_name, user_message)
                    response = f"""{user_name}さん、シフト変更依頼を受け付けました。

📝 依頼内容: {user_message}

田野義和マネージャーに通知しました。承認され次第、ご連絡いたします。
しばらくお待ちください。"""

                    # Store AI response
                    store_conversation(user_id, 'assistant', response)
                    return response

                # Handle shift confirmations
                elif is_shift_confirmation(user_message):
                    success, message = record_shift_confirmation(user_id, user_name)
                    response = message

                    # Store AI response
                    store_conversation(user_id, 'assistant', response)
                    return response

                # Handle shift inquiries (prevent hallucination)
                elif is_shift_inquiry(user_message):
                    response = get_shift_response(user_name)

                    # Store AI response
                    store_conversation(user_id, 'assistant', response)
                    return response

                # Handle other messages with AI
                else:
                    response = generate_ai_response(user_message, user_id=user_id, context="registered_user")

                    # Store AI response
                    store_conversation(user_id, 'assistant', response)
                    return response

            else:
                # User not registered - handle registration flow
                if user_message.lower() in ['登録', 'register', 'とうろく']:
                    response = """こんにちは！シフト管理システムへようこそ。

📝 登録方法:
あなたのフルネームをスペースなしで入力してください。

例: 田中太郎 → 「田中太郎」
例: 山田花子 → 「山田花子」

⚠️ 注意:
• スペースは自動的に削除されます
• 2-20文字以内
• ひらがな・カタカナ・漢字・英字のみ使用可能"""

                    # Store conversation
                    store_conversation(user_id, 'user', user_message)
                    store_conversation(user_id, 'assistant', response)
                    return response

                elif len(user_message) >= 2:
                    # Validate and format the name
                    formatted_name, error_msg = validate_and_format_name(user_message)

                    if formatted_name:
                        try:
                            cursor.execute("INSERT INTO users (line_user_id, employee_name) VALUES (?, ?)",
                                         (user_id, formatted_name))
                            conn.commit()

                            logging.info(f"New user registered: {formatted_name} (ID: {user_id})")
                            response = f"""✅ 登録が完了しました！

お名前: {formatted_name}さん

これでシフト通知を受け取ることができるようになりました。
シフトの変更依頼がある場合は、メッセージを送ってください。"""

                            # Store conversation
                            store_conversation(user_id, 'user', user_message)
                            store_conversation(user_id, 'assistant', response)
                            return response

                        except sqlite3.IntegrityError:
                            response = f"""❌ 登録エラー

「{user_message}」はすでに使用されています。

別の名前で再度お試しください。
例: {user_message}2 や {user_message}太郎"""

                            # Store conversation
                            store_conversation(user_id, 'user', user_message)
                            store_conversation(user_id, 'assistant', response)
                            return response

                    else:
                        response = f"""❌ 名前が無効です

{error_msg}

📝 正しい形式:
• スペースなしで入力
• 2-20文字以内
• ひらがな・カタカナ・漢字・英字のみ

例: 「田中太郎」「YamadaHanako」"""

                        # Store conversation
                        store_conversation(user_id, 'user', user_message)
                        store_conversation(user_id, 'assistant', response)
                        return response

                else:
                    # Short message - ask for proper registration
                    response = """👋 こんにちは！

シフト通知を受け取るには、まず登録が必要です。

「登録」と入力して、登録を開始してください。"""

                    # Store conversation
                    store_conversation(user_id, 'user', user_message)
                    store_conversation(user_id, 'assistant', response)
                    return response

    except Exception as e:
        logging.error(f"Error processing user message: {e}")
        error_response = "申し訳ありませんが、エラーが発生しました。しばらく経ってから再度お試しください。"

        # Try to store error conversation
        try:
            store_conversation(user_id, 'user', user_message)
            store_conversation(user_id, 'assistant', error_response)
        except:
            pass

        return error_response

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
