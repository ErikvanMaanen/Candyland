from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

import subprocess
import os
import pyodbc
import sqlite3
import datetime
from werkzeug.utils import secure_filename
import wave
import tempfile
try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import whisper
except ImportError:
    whisper = None

app = Flask(__name__)

# ...existing code...

# --- Video recording endpoint ---
@app.route('/record_video', methods=['POST'])
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

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/show_smiley')
def show_smiley():
    return render_template('smiley.html')

@app.route('/run_script_no_args', methods=['POST'])
def run_script_no_args():
    # Replace 'script_no_args.py' with your script name
    result = subprocess.run(['python', 'script_no_args.py'], capture_output=True, text=True)
    return jsonify({'output': result.stdout})

@app.route('/run_script_with_args', methods=['POST'])
def run_script_with_args():
    arg = request.form.get('arg')
    # Replace 'script_with_args.py' with your script name
    result = subprocess.run(['python', 'script_with_args.py', arg], capture_output=True, text=True)
    return jsonify({'output': result.stdout})


# --- Audio recording endpoint ---
@app.route('/record_message', methods=['POST'])
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

    # Transcribe audio using OpenAI Whisper (local base model)
    transcription = ''
    if whisper and wav_path and os.path.exists(wav_path):
        try:
            model = whisper.load_model('base')
            result = model.transcribe(wav_path)
            transcription = result.get('text', '')
        except Exception:
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
