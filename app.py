from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

import subprocess
import os
import pyodbc
import datetime
from werkzeug.utils import secure_filename
import wave
import tempfile
try:
    import speech_recognition as sr
except ImportError:
    sr = None

app = Flask(__name__)

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
    save_path = os.path.join('static', filename)
    audio.save(save_path)

    # Convert webm to wav for transcription (if possible)
    wav_path = None
    try:
        import ffmpeg
        wav_path = save_path.replace('.webm', '.wav')
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

    # Transcribe audio (if possible)
    transcription = ''
    if sr and wav_path and os.path.exists(wav_path):
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            try:
                transcription = recognizer.recognize_google(audio_data)
            except Exception:
                transcription = ''


    # Store in Azure SQL Database
    conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
    if not conn_str:
        # Build from individual env vars if needed
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
    # Create table if not exists
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
    # Insert record
    cursor.execute('''INSERT INTO Recordings (date, filename, length, transcription) VALUES (?, ?, ?, ?)''',
                   datetime.datetime.now().isoformat(), filename, length, transcription)
    conn.commit()
    conn.close()

    return jsonify({'status': 'ok', 'length': length, 'transcription': transcription})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
