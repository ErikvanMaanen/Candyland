from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, session

import subprocess
import os
import pyodbc
import sqlite3
import datetime
import logging
from werkzeug.utils import secure_filename
import wave
import tempfile
import hashlib
import requests
import uuid
import qrcode
from functools import wraps
try:
    import speech_recognition as sr
except ImportError:
    sr = None


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change_me')
app.logger.setLevel('DEBUG')

# --- Utility functions for database connections ---
def get_sql_connection(db_name):
    """Return a connection to the given database either on Azure SQL or local SQLite."""
    if os.environ.get('WEBSITE_SITE_NAME'):
        server = os.environ.get('AZURE_SQL_SERVER')
        username = os.environ.get('AZURE_SQL_USER')
        password = os.environ.get('AZURE_SQL_PASSWORD')
        port = os.environ.get('AZURE_SQL_PORT', '1433')
        conn_str = (
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={server},{port};'
            f'DATABASE={db_name};'
            f'UID={username};PWD={password}'
        )
        return pyodbc.connect(conn_str)
    else:
        return sqlite3.connect(f"{db_name.lower()}.db")


class SQLLogHandler(logging.Handler):
    """Logging handler that stores log records in the Log database."""

    def emit(self, record):
        msg = self.format(record)
        ts = datetime.datetime.now().isoformat()
        try:
            conn = get_sql_connection('Log')
            cursor = conn.cursor()
            if isinstance(conn, sqlite3.Connection):
                cursor.execute(
                    'CREATE TABLE IF NOT EXISTS Logs ('
                    'id INTEGER PRIMARY KEY AUTOINCREMENT,'
                    'timestamp TEXT,'
                    'level TEXT,'
                    'message TEXT)'
                )
                cursor.execute(
                    'INSERT INTO Logs (timestamp, level, message) VALUES (?, ?, ?)',
                    (ts, record.levelname, msg),
                )
            else:
                cursor.execute(
                    'IF NOT EXISTS (SELECT * FROM sysobjects WHERE name="Logs" AND xtype="U") '
                    'CREATE TABLE Logs ('
                    'id INT IDENTITY(1,1) PRIMARY KEY,'
                    'timestamp NVARCHAR(50),'
                    'level NVARCHAR(20),'
                    'message NVARCHAR(MAX))'
                )
                conn.commit()
                cursor.execute(
                    'INSERT INTO Logs (timestamp, level, message) VALUES (?, ?, ?)',
                    ts,
                    record.levelname,
                    msg,
                )
            conn.commit()
            conn.close()
        except Exception:
            # Avoid recursion if logging fails
            pass


log_handler = SQLLogHandler()
log_handler.setLevel(logging.INFO)
app.logger.addHandler(log_handler)

# Precomputed SHA3-512 hash of the allowed password
HASHED_PASSWORD = "16725c4d35c707477e09bee390fbb27e3e294fe84a807940c8e8349891b6ef3137bf18be05144e9adb869436c96b3ba1c1a8b70c2543c5ade24e54b8644f3a47"

# Bitcoin payment address for the ecommerce demo
BTC_ADDRESS = (
    "PM8TJLtyXMwbcEYy6RTnS3oSyCrA9RCSnx4faV1j8hVBuPYcfgs6cbcHKXdoKjo65owS22RgaVe3jsgdXBGUSA8fL7mLef84nH3QcAZaeK4FDVPiPj43"
)


def login_required(func):
    """Simple decorator to ensure the user is authenticated."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

# ...existing code...

# --- Video recording endpoint ---
@app.route('/record_video', methods=['POST'])
@login_required
def record_video():
    video = request.files['video']
    filename = f"video_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.webm"
    videos_dir = os.path.join('recordings', 'videos')
    os.makedirs(videos_dir, exist_ok=True)
    save_path = os.path.join(videos_dir, filename)
    video.save(save_path)
    return jsonify({'status': 'ok'})

# --- List recorded videos ---
@app.route('/get_videos')
@login_required
def get_videos():
    videos_dir = os.path.join('recordings', 'videos')
    videos = []
    if os.path.exists(videos_dir):
        for fname in sorted(os.listdir(videos_dir), reverse=True):
            if fname.endswith('.webm'):
                url = url_for('static', filename=f'../recordings/videos/{fname}')
                videos.append({'url': url, 'name': fname})
    return jsonify({'videos': videos})

@app.route('/get_movement')
@login_required
def get_movement():
    records = []
    if os.environ.get('WEBSITE_SITE_NAME'):
        # Azure SQL
        conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
        if not conn_str:
            server = os.environ.get('AZURE_SQL_SERVER')
            database = os.environ.get('AZURE_SQL_DATABASE')
            username = os.environ.get('AZURE_SQL_USER')
            password = os.environ.get('AZURE_SQL_PASSWORD')
            port = os.environ.get('AZURE_SQL_PORT', '1433')
            conn_str = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={server},{port};'
                f'DATABASE={database};'
                f'UID={username};PWD={password}'
            )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute('SELECT timestamp, lat, lon, gx, gy, gz FROM Movement ORDER BY id DESC')
        for row in cursor.fetchall():
            records.append({
                'timestamp': row[0],
                'lat': row[1],
                'lon': row[2],
                'gx': row[3],
                'gy': row[4],
                'gz': row[5]
            })
        conn.close()
    else:
        # Local SQLite
        conn = sqlite3.connect('recordings.db')
        c = conn.cursor()
        c.execute('SELECT timestamp, lat, lon, gx, gy, gz FROM Movement ORDER BY id DESC')
        for row in c.fetchall():
            records.append({
                'timestamp': row[0],
                'lat': row[1],
                'lon': row[2],
                'gx': row[3],
                'gy': row[4],
                'gz': row[5]
            })
        conn.close()
    return jsonify({'records': records})

@app.route('/record_movement', methods=['POST'])
@login_required
def record_movement():
    data = request.get_json().get('data', [])
    # Use Azure SQL if running in Azure, else use SQLite
    if os.environ.get('WEBSITE_SITE_NAME'):
        # Azure SQL
        conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
        if not conn_str:
            server = os.environ.get('AZURE_SQL_SERVER')
            database = os.environ.get('AZURE_SQL_DATABASE')
            username = os.environ.get('AZURE_SQL_USER')
            password = os.environ.get('AZURE_SQL_PASSWORD')
            port = os.environ.get('AZURE_SQL_PORT', '1433')
            conn_str = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={server},{port};'
                f'DATABASE={database};'
                f'UID={username};PWD={password}'
            )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Movement' AND xtype='U')
            CREATE TABLE Movement (
                id INT IDENTITY(1,1) PRIMARY KEY,
                timestamp BIGINT,
                lat FLOAT,
                lon FLOAT,
                gx FLOAT,
                gy FLOAT,
                gz FLOAT
            )
        ''')
        conn.commit()
        for entry in data:
            cursor.execute('''INSERT INTO Movement (timestamp, lat, lon, gx, gy, gz) VALUES (?, ?, ?, ?, ?, ?)''',
                           entry.get('timestamp'), entry.get('lat'), entry.get('lon'), entry.get('gx'), entry.get('gy'), entry.get('gz'))
        conn.commit()
        conn.close()
    else:
        # Local SQLite
        conn = sqlite3.connect('recordings.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Movement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            lat REAL,
            lon REAL,
            gx REAL,
            gy REAL,
            gz REAL
        )''')
        for entry in data:
            c.execute('INSERT INTO Movement (timestamp, lat, lon, gx, gy, gz) VALUES (?, ?, ?, ?, ?, ?)',
                      (entry.get('timestamp'), entry.get('lat'), entry.get('lon'), entry.get('gx'), entry.get('gy'), entry.get('gz')))
        conn.commit()
        conn.close()
    return jsonify({'status': 'ok'})

@app.route('/get_archive')
@login_required
def get_archive():
    # Use Azure SQL if running in Azure, else use SQLite
    records = []
    if os.environ.get('WEBSITE_SITE_NAME'):
        # Azure SQL
        conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
        if not conn_str:
            server = os.environ.get('AZURE_SQL_SERVER')
            database = os.environ.get('AZURE_SQL_DATABASE')
            username = os.environ.get('AZURE_SQL_USER')
            password = os.environ.get('AZURE_SQL_PASSWORD')
            port = os.environ.get('AZURE_SQL_PORT', '1433')
            conn_str = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={server},{port};'
                f'DATABASE={database};'
                f'UID={username};PWD={password}'
            )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute('SELECT date, filename, length, transcription FROM Recordings ORDER BY id DESC')
        for row in cursor.fetchall():
            records.append({
                'date': row[0],
                'filename': row[1],
                'length': row[2],
                'transcription': row[3]
            })
        conn.close()
    else:
        # Local SQLite
        conn = sqlite3.connect('recordings.db')
        c = conn.cursor()
        c.execute('SELECT date, filename, length, transcription FROM Recordings ORDER BY id DESC')
        for row in c.fetchall():
            records.append({
                'date': row[0],
                'filename': row[1],
                'length': row[2],
                'transcription': row[3]
            })
        conn.close()
    return jsonify({'records': records})

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        hashed = hashlib.sha3_512(password.encode()).hexdigest()
        if hashed == HASHED_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('home'))
        else:
            error = 'Invalid password'
    return render_template('login.html', error=error)

@app.route('/')
@login_required
def home():
    return render_template('index.html')

# Route for Functions 1 page containing the previous portal functionality
@app.route('/functions1')
@login_required
def functions1():
    return render_template('functions1.html')

@app.route('/show_smiley')
@login_required
def show_smiley():
    return render_template('smiley.html')

@app.route('/run_script_no_args', methods=['POST'])
@login_required
def run_script_no_args():
    # Replace 'script_no_args.py' with your script name
    result = subprocess.run(['python', 'script_no_args.py'], capture_output=True, text=True)
    return jsonify({'output': result.stdout})

@app.route('/run_script_with_args', methods=['POST'])
@login_required
def run_script_with_args():
    arg = request.form.get('arg')
    # Replace 'script_with_args.py' with your script name
    result = subprocess.run(['python', 'script_with_args.py', arg], capture_output=True, text=True)
    return jsonify({'output': result.stdout})


# --- Simple ecommerce demo ---
def fetch_btc_rate():
    """Fetch current BTC rate in EUR. Fallback to a fixed value on error."""
    try:
        resp = requests.get('https://api.coindesk.com/v1/bpi/currentprice/EUR.json', timeout=5)
        data = resp.json()
        rate = float(data['bpi']['EUR']['rate'].replace(',', ''))
        return rate
    except Exception:
        return 30000.0


def create_qr_code(data, path):
    """Generate a QR code image with high error correction."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(path)


def record_purchase(apples, bananas, name, address, email, total_eur, total_btc, tx_hash):
    """Store purchase information in the Purchases database."""
    ts = datetime.datetime.now().isoformat()
    conn = get_sql_connection('Purchases')
    cursor = conn.cursor()
    if isinstance(conn, sqlite3.Connection):
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS Purchases ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT,'
            'timestamp TEXT,'
            'apples INTEGER,'
            'bananas INTEGER,'
            'name TEXT,'
            'address TEXT,'
            'email TEXT,'
            'total_eur REAL,'
            'total_btc REAL,'
            'tx_hash TEXT)'
        )
        cursor.execute(
            'INSERT INTO Purchases (timestamp, apples, bananas, name, address, email, total_eur, total_btc, tx_hash) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (ts, apples, bananas, name, address, email, total_eur, total_btc, tx_hash),
        )
    else:
        cursor.execute(
            'IF NOT EXISTS (SELECT * FROM sysobjects WHERE name="Purchases" AND xtype="U") '
            'CREATE TABLE Purchases ('
            'id INT IDENTITY(1,1) PRIMARY KEY,'
            'timestamp NVARCHAR(50),'
            'apples INT,'
            'bananas INT,'
            'name NVARCHAR(255),'
            'address NVARCHAR(255),'
            'email NVARCHAR(255),'
            'total_eur FLOAT,'
            'total_btc FLOAT,'
            'tx_hash NVARCHAR(64))'
        )
        conn.commit()
        cursor.execute(
            'INSERT INTO Purchases (timestamp, apples, bananas, name, address, email, total_eur, total_btc, tx_hash) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ts,
            apples,
            bananas,
            name,
            address,
            email,
            total_eur,
            total_btc,
            tx_hash,
        )
    conn.commit()
    conn.close()


@app.route('/ecommerce')
@login_required
def ecommerce():
    return render_template('ecommerce.html')


@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    apples = int(request.form.get('apples', 0))
    bananas = int(request.form.get('bananas', 0))
    name = request.form.get('name')
    address = request.form.get('address')
    email = request.form.get('email')
    app.logger.debug('Checkout requested')

    total_eur = apples * 1 + bananas * 2
    rate = fetch_btc_rate()
    total_btc = round(total_eur / rate, 8)

    # Create a unique hash for this transaction
    tx_seed = f"{name}|{address}|{email}|{apples}|{bananas}|{total_eur}|{total_btc}|{uuid.uuid4().hex}"
    tx_hash = hashlib.sha256(tx_seed.encode()).hexdigest()

    # Generate a QR code for payment
    btc_uri = f"bitcoin:{BTC_ADDRESS}?amount={total_btc}"
    qr_dir = os.path.join('static', 'qrcodes')
    os.makedirs(qr_dir, exist_ok=True)
    qr_filename = f"{tx_hash}.png"
    qr_path = os.path.join(qr_dir, qr_filename)
    create_qr_code(btc_uri, qr_path)

    record_purchase(
        apples,
        bananas,
        name,
        address,
        email,
        total_eur,
        total_btc,
        tx_hash,
    )

    return render_template(
        'checkout.html',
        total_eur=total_eur,
        total_btc=total_btc,
        btc_address=BTC_ADDRESS,
        btc_rate=rate,
        tx_hash=tx_hash,
        qr_filename=qr_filename,
        apples=apples,
        bananas=bananas,
        name=name,
        address=address,
        email=email,
    )


@app.route('/update_payment', methods=['POST'])
@login_required
def update_payment():
    data = request.get_json(force=True)
    apples = int(data.get('apples', 0))
    bananas = int(data.get('bananas', 0))
    name = data.get('name')
    address = data.get('address')
    email = data.get('email')
    app.logger.debug('Updating payment')

    total_eur = apples * 1 + bananas * 2
    rate = fetch_btc_rate()
    total_btc = round(total_eur / rate, 8)

    tx_seed = f"{name}|{address}|{email}|{apples}|{bananas}|{total_eur}|{total_btc}|{uuid.uuid4().hex}"
    tx_hash = hashlib.sha256(tx_seed.encode()).hexdigest()

    btc_uri = f"bitcoin:{BTC_ADDRESS}?amount={total_btc}"
    qr_dir = os.path.join('static', 'qrcodes')
    os.makedirs(qr_dir, exist_ok=True)
    qr_filename = f"{tx_hash}.png"
    qr_path = os.path.join(qr_dir, qr_filename)
    create_qr_code(btc_uri, qr_path)
    record_purchase(
        apples,
        bananas,
        name,
        address,
        email,
        total_eur,
        total_btc,
        tx_hash,
    )
    app.logger.debug(f"New tx hash {tx_hash}")

    return jsonify({
        'tx_hash': tx_hash,
        'qr_filename': qr_filename,
        'total_btc': total_btc,
        'btc_rate': rate,
    })


# --- Generic QR generator page ---
@app.route('/qr', methods=['GET', 'POST'])
@login_required
def qr_generator():
    qr_filename = None
    if request.method == 'POST':
        qr_type = request.form.get('qr_type')
        data = ''
        if qr_type == 'url':
            data = request.form.get('url', '')
        elif qr_type == 'text':
            data = request.form.get('text', '')
        elif qr_type == 'btc':
            address = request.form.get('btc_address', '')
            amount = request.form.get('btc_amount', '')
            if address:
                data = f'bitcoin:{address}'
                if amount:
                    data += f'?amount={amount}'
        if data:
            qr_dir = os.path.join('static', 'qrcodes')
            os.makedirs(qr_dir, exist_ok=True)
            qr_filename = f"{uuid.uuid4().hex}.png"
            qr_path = os.path.join(qr_dir, qr_filename)
            create_qr_code(data, qr_path)
    return render_template('qr_generator.html', qr_filename=qr_filename)


# --- Audio recording endpoint ---
@app.route('/record_message', methods=['POST'])
@login_required
def record_message():
    audio = request.files['audio']
    filename = secure_filename(f"recording_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.webm")
    recordings_dir = os.path.join('recordings')
    os.makedirs(recordings_dir, exist_ok=True)
    save_path = os.path.join(recordings_dir, filename)
    audio.save(save_path)

    # Convert webm to wav for transcription (if possible)
    wav_path = None
    try:
        import ffmpeg
        wav_path = os.path.join(recordings_dir, filename.replace('.webm', '.wav'))
        (
            ffmpeg
            .input(save_path)
            .output(wav_path)
            .run(overwrite_output=True, quiet=True)
        )
    except Exception:
        wav_path = None

    # Get audio length
    length = 0
    if wav_path and os.path.exists(wav_path):
        with wave.open(wav_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            length = round(frames / float(rate), 2)
    else:
        length = 0

    # Prepare transcription value
    transcription = ''


    # Use Azure SQL if running in Azure, else use SQLite
    if os.environ.get('WEBSITE_SITE_NAME'):
        # Azure SQL
        conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
        if not conn_str:
            server = os.environ.get('AZURE_SQL_SERVER')
            database = os.environ.get('AZURE_SQL_DATABASE')
            username = os.environ.get('AZURE_SQL_USER')
            password = os.environ.get('AZURE_SQL_PASSWORD')
            port = os.environ.get('AZURE_SQL_PORT', '1433')
            conn_str = (
                f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                f'SERVER={server},{port};'
                f'DATABASE={database};'
                f'UID={username};PWD={password}'
            )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Recordings' AND xtype='U')
            CREATE TABLE Recordings (
                id INT IDENTITY(1,1) PRIMARY KEY,
                date NVARCHAR(50),
                filename NVARCHAR(255),
                length FLOAT,
                transcription NVARCHAR(MAX)
            )
        ''')
        conn.commit()
        cursor.execute('''INSERT INTO Recordings (date, filename, length, transcription) VALUES (?, ?, ?, ?)''',
                       datetime.datetime.now().isoformat(), filename, length, transcription)
        conn.commit()
        conn.close()
    else:
        # Local SQLite
        conn = sqlite3.connect('recordings.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            filename TEXT,
            length REAL,
            transcription TEXT
        )''')
        c.execute('INSERT INTO Recordings (date, filename, length, transcription) VALUES (?, ?, ?, ?)',
                  (datetime.datetime.now().isoformat(), filename, length, transcription))
        conn.commit()
        conn.close()

    return jsonify({'status': 'ok', 'length': length, 'transcription': transcription})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
