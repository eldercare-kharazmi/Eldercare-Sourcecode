from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import sqlite3
import hashlib
import os
import requests 
from datetime import datetime, timedelta

app = Flask(__name__)

# کلید امنیتی سشن
app.secret_key = 'khwarazmi_fixed_secure_key_123456789' 
app.config['PERMANENT_SESSION_LIFETIME'] = 7200

# رفع خطای امنیتی مرورگر برای سشن‌ها در محیط بدون HTTPS (HTTP معمولی)
app.config.update(
    SESSION_COOKIE_SECURE=False,   # روی حالت False تا در محیط لوکال و HTTP خطا ندهد
    SESSION_COOKIE_HTTPONLY=True,  # جلوگیری از دسترسی اسکریپت‌های مخرب به کوکی سشن
    SESSION_COOKIE_SAMESITE='Lax', # سازگاری کامل با مرورگرها برای مدیریت کوکی امن
)

GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxfWYBOP8SGW06MkcwKutQjQNklSLPuX8U8xwmOZt6LZlnI3lNmWz1STu-XJHES753I8Q/exec"

CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'instance', 'database.db')
app.config['DATABASE'] = DATABASE_PATH

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    salt = "khwarazmi_salt_2024"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def init_db():
    instance_dir = os.path.dirname(app.config['DATABASE'])
    if not os.path.exists(instance_dir):
        os.makedirs(instance_dir)
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, fullname TEXT, email TEXT, user_type TEXT, elder_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS medications (id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id INTEGER NOT NULL, drug_name TEXT NOT NULL, usage_method TEXT, usage_date TEXT NOT NULL, usage_time TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (elder_id) REFERENCES users (id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id INTEGER, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.commit()

with app.app_context():
    try: init_db()
    except: pass

def send_email_via_google(to_email, subject, html_content):
    if "LINK_GOOGLE" in GOOGLE_SCRIPT_URL:
        return False
    payload = {"to": to_email, "subject": subject, "body": html_content}
    try:
        requests.post(GOOGLE_SCRIPT_URL, json=payload)
        return True
    except: return False

def trigger_alert(elder_id, family_email, elder_name, drug_name):
    db = get_db()
    msg_text = f"داروی «{drug_name}» توسط {elder_name} مصرف نشد."
    db.execute('INSERT INTO alerts (elder_id, message) VALUES (?, ?)', (elder_id, msg_text))
    db.commit()

    if family_email:
        subject = "⚠️ هشدار فوری: عدم مصرف دارو"
        body = f"""
        <div style="direction: rtl; text-align: right; font-family: Tahoma; border: 2px solid #e74c3c; padding: 20px; border-radius: 10px;">
            <h2 style="color: #e74c3c;">هشدار سیستم</h2>
            <p>خانواده گرامی،</p>
            <p>سالمند شما <strong>({elder_name})</strong> داروی <strong>{drug_name}</strong> را سر وقت مصرف نکرده است.</p>
        </div>
        """
        send_email_via_google(family_email, subject, body)

def check_missed_medications():
    try:
        db = get_db()
        cursor = db.cursor()
        iran_now = datetime.utcnow() + timedelta(hours=3, minutes=30)
        today = iran_now.strftime('%Y-%m-%d')
        now_total = iran_now.hour * 60 + iran_now.minute
        
        cursor.execute('''SELECT m.id, m.drug_name, m.usage_date, m.usage_time, m.elder_id, u.fullname as elder_name 
                          FROM medications m JOIN users u ON m.elder_id = u.id 
                          WHERE m.status = 'pending' AND m.usage_date <= ?''', (today,))
        
        for med in cursor.fetchall():
            try:
                h, m = map(int, med['usage_time'].split(':'))
                if med['usage_date'] < today or now_total > (h * 60 + m + 5):
                    cursor.execute('UPDATE medications SET status = "missed" WHERE id = ?', (med['id'],))
                    db.commit()
                    cursor.execute('SELECT email FROM users WHERE elder_id = ? AND user_type = "family"', (med['elder_id'],))
                    fam = cursor.fetchone()
                    trigger_alert(med['elder_id'], fam['email'] if fam else None, med['elder_name'], med['drug_name'])
            except: continue
    except: pass

@app.route('/api/system/auto-check-medications-secure-ping')
def system_ping():
    check_missed_medications()
    return jsonify({"status": "checked", "time": datetime.utcnow().isoformat()})

@app.route('/')
def index():
    check_missed_medications()
    user_info = {'fullname': session.get('fullname'), 'type': session.get('user_type')} if 'user_id' in session else None
    return render_template('index.html', user=user_info)

@app.route('/login')
def login_page(): return render_template('login.html', role=request.args.get('type', 'elder'))

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json; db = get_db(); cursor = db.cursor()
    try:
        elder_db_id = data.get('elder_code') if data['user_type'] == 'family' else None
        if data['user_type'] == 'family':
            cursor.execute('SELECT id FROM users WHERE id = ? AND user_type = "elder"', (elder_db_id,))
            if not cursor.fetchone(): return jsonify({'success': False, 'message': 'کد سالمند نامعتبر است'})

        cursor.execute('INSERT INTO users (username, password, fullname, email, user_type, elder_id) VALUES (?, ?, ?, ?, ?, ?)', 
                      (data['username'], hash_password(data['password']), data['fullname'], data.get('email'), data['user_type'], elder_db_id))
        db.commit()
        session['user_id'] = cursor.lastrowid; session['fullname'] = data['fullname']; session['user_type'] = data['user_type']
        return jsonify({'success': True, 'redirect_url': '/'})
    except: return jsonify({'success': False, 'message': 'نام کاربری تکراری است'})

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json; db = get_db(); cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (data['username'], hash_password(data['password'])))
    user = cursor.fetchone()
    if user:
        session['user_id'] = user['id']; session['fullname'] = user['fullname']; session['user_type'] = user['user_type']
        return jsonify({'success': True, 'redirect_url': '/dashboard/elder' if user['user_type'] == 'elder' else '/dashboard/family'})
    return jsonify({'success': False, 'message': 'نام کاربری یا رمز اشتباه است'})

@app.route('/dashboard/elder')
def elder_dashboard():
    if 'user_id' not in session: return redirect('/')
    check_missed_medications()
    db = get_db(); cursor = db.cursor()
    today = (datetime.utcnow() + timedelta(hours=3, minutes=30)).strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM medications WHERE elder_id = ? AND (usage_date = ? OR (status = 'pending' AND usage_date < ?)) ORDER BY usage_time", (session['user_id'], today, today))
    return render_template('dashboard_elder.html', medications=cursor.fetchall(), fullname=session['fullname'], today_date=today)

@app.route('/dashboard/family')
def family_dashboard():
    if 'user_id' not in session: return redirect('/')
    check_missed_medications()
    db = get_db(); cursor = db.cursor()
    cursor.execute('SELECT elder_id FROM users WHERE id = ?', (session['user_id'],))
    res = cursor.fetchone()
    if not res or not res['elder_id']: return render_template('dashboard_family.html', medications=[], alerts=[], elder_name='-', fullname=session['fullname'])
    elder_id = res['elder_id']
    cursor.execute('SELECT fullname FROM users WHERE id = ?', (elder_id,))
    elder = cursor.fetchone()
    today = (datetime.utcnow() + timedelta(hours=3, minutes=30)).strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM medications WHERE elder_id = ? AND (usage_date = ? OR status = 'missed') ORDER BY usage_time", (elder_id, today))
    meds = cursor.fetchall()
    cursor.execute("SELECT * FROM alerts WHERE elder_id = ? ORDER BY created_at DESC LIMIT 5", (elder_id,))
    alerts = cursor.fetchall()
    return render_template('dashboard_family.html', medications=meds, alerts=alerts, elder_name=elder['fullname'] if elder else '-', fullname=session['fullname'])

@app.route('/api/medication', methods=['POST'])
def add_medication():
    data = request.json; times = data.get('times'); db = get_db()
    start_date = datetime.utcnow() + timedelta(hours=3, minutes=30)
    for i in range(int(data.get('duration', 1))):
        d_str = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
        for t in times:
            if t: db.execute('INSERT INTO medications (elder_id, drug_name, usage_method, usage_date, usage_time) VALUES (?,?,?,?,?)', (session['user_id'], data['drug_name'], data['usage_method'], d_str, t))
    db.commit(); return jsonify({'success': True})

@app.route('/api/medication/<int:med_id>/status', methods=['PUT'])
def update_status(med_id):
    st = request.json.get('status'); db = get_db(); cursor = db.cursor()
    cursor.execute('UPDATE medications SET status = ? WHERE id = ? AND elder_id = ?', (st, med_id, session['user_id']))
    db.commit()
    if st == 'missed':
        cursor.execute('SELECT drug_name FROM medications WHERE id = ?', (med_id,))
        drug = cursor.fetchone()
        cursor.execute('SELECT email FROM users WHERE elder_id = ? AND user_type = "family"', (session['user_id'],))
        family = cursor.fetchone()
        if drug: trigger_alert(session['user_id'], family['email'] if family else None, session.get('fullname'), drug['drug_name'])
    return jsonify({'success': True})

@app.route('/api/elder/code')
def get_elder_code(): return jsonify({'success': True, 'elder_code': session.get('user_id')})

@app.route('/api/elder/connected-family')
def get_connected_family():
    db = get_db(); cursor = db.cursor()
    cursor.execute('SELECT fullname FROM users WHERE elder_id = ? AND user_type = "family"', (session['user_id'],))
    f = cursor.fetchone()
    return jsonify({'success': True, 'connected': bool(f), 'family_name': f['fullname'] if f else None})

@app.route('/api/elder/disconnect-family', methods=['POST'])
def disconnect_family():
    db = get_db(); db.execute('UPDATE users SET elder_id = NULL WHERE elder_id = ? AND user_type = "family"', (session['user_id'],)); db.commit()
    return jsonify({'success': True})

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

@app.route('/about')
def about(): return render_template('about.html')

if __name__ == '__main__': app.run()