from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
import sqlite3
import datetime
import pytz # Add this
import os  # Add this to read Render variables


app = Flask(__name__)

# --- CONFIGURATION ---
app.secret_key = 'super_secret_key_change_this_later'

# This pulls the values from the Render "Environment" tab we set up
TWILIO_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE = os.environ.get('TWILIO_PHONE_NUMBER')

client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    # Create the old reminders table
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tablet_name TEXT,
                  reminder_time TEXT,
                  phone_number TEXT,
                  is_sent BOOLEAN)''')
    # Create the NEW users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password_hash TEXT)''')
    conn.commit()
    conn.close()

# --- SMS & SCHEDULER LOGIC (Remains the same) ---
def send_sms(phone, tablet):
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=f"Reminder: It's time to take your tablet - {tablet}!",
            from_=TWILIO_PHONE,
            to=phone
        )
        print(f"✅ SMS successfully sent to {phone}.")
    except Exception as e:
        print(f"❌ Failed to send SMS: {e}")

def check_reminders():
    # 1. Get current time in the SAME format as the database (with timezone)
    IST = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(IST).strftime("%Y-%m-%dT%H:%M") 
    
    print(f"--- Scheduler checking for reminders starting with: {now} ---")
    
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    # 2. Use 'LIKE' so it matches the date and time, ignoring the extra seconds/offset
    c.execute("SELECT id, tablet_name, phone_number, reminder_time FROM reminders WHERE reminder_time LIKE ? AND is_sent = 0", (now + '%',))
    
    due_reminders = c.fetchall()
    
    for reminder in due_reminders:
        reminder_id, tablet_name, phone_number, reminder_time = reminder
        print(f"⏰ TRIGGERED: Sending SMS for {tablet_name} (Scheduled: {reminder_time})")
        
        try:
            send_sms(phone_number, tablet_name)
            c.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,))
            conn.commit()
            print(f"✅ Success: {tablet_name} sent to {phone_number}")
        except Exception as e:
            print(f"❌ Twilio Error: {e}")

    conn.close()

# --- AUTHENTICATION ROUTES ---
@app.route('/')
def login_page():
    # If already logged in, skip login and go to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_pw = generate_password_hash(password) # Scramble the password

        try:
            conn = sqlite3.connect('reminders.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed_pw))
            conn.commit()
            conn.close()
            return redirect(url_for('login_page'))
        except sqlite3.IntegrityError:
            return "Username already exists! Go back and try another."
    
    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()

    # Check if user exists AND password matches the scrambled hash
    if user and check_password_hash(user[1], password):
        session['user_id'] = user[0] # Start the session
        session['username'] = username
        return redirect(url_for('dashboard'))
    else:
        return "Invalid username or password! Go back and try again."

@app.route('/logout')
def logout():
    session.clear() # Destroy the session
    return redirect(url_for('login_page'))

# --- MAIN DASHBOARD ROUTES ---
@app.route('/dashboard')
def dashboard():
    # Security check: Kick them out if not logged in
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html')

@app.route('/add_reminder', methods=['POST'])
def add_reminder():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    tablet_name = request.form['tablet_name']
    reminder_time_str = request.form['reminder_time']
    phone_number = request.form['phone_number']
    
    # Grab the number of days from the HTML form (defaulting to 1 if missing)
    duration_days = int(request.form.get('duration_days', 1))

    # Convert the HTML time string into a Python datetime object
    # 1. Define the IST timezone
    IST = pytz.timezone('Asia/Kolkata')

    # 2. Parse the string into a datetime object
    # (Assuming reminder_time_str is like '2026-04-15 00:39')
    start_time_naive = datetime.datetime.strptime(reminder_time_str, "%Y-%m-%dT%H:%M")
    
    # 3. Localize it so the system knows this is specifically IST time
    start_time = IST.localize(start_time_naive)

    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()

    # Loop through the number of days
    for i in range(duration_days):
        current_day_time = start_time + datetime.timedelta(days=i)
        
        # 4. Save to DB as an ISO string that includes the timezone info
        db_time_str = current_day_time.strftime("%Y-%m-%dT%H:%M:%S%z")
        
        # Insert each day into the database
        c.execute("INSERT INTO reminders (tablet_name, reminder_time, phone_number, is_sent) VALUES (?, ?, ?, 0)",
                  (tablet_name, db_time_str, phone_number))
        
        # Terminal print statement
        print(f"📝 SAVED: {tablet_name} scheduled for {db_time_str}")
        
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": f"Successfully set for {duration_days} day(s)!"})

# --- Everything below this line should have ZERO spaces at the start ---
init_db()
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_reminders, trigger="interval", seconds=60)
scheduler.start()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
