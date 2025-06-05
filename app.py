from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
import subprocess
import os

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
