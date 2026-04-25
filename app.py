from flask import Flask, request, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
import subprocess
import os

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/hls/<path:filename>')
def hls(filename):
    return send_from_directory('hls', filename)

@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

@app.route('/metrics', methods=['POST'])
def metrics():
    data = request.json
    socketio.emit('metrics', data)
    
    return {"status": "ok"}

@socketio.on('connect')
def connect():
    print("client connected")

@app.route('/anomaly', methods=['POST'])
def anomaly():
    data = request.json
    socketio.emit('anomaly', data)
    return {"status": "ok"}
    
if __name__ == "__main__":
    os.makedirs("hls", exist_ok=True)
    
    command = [
        'ffmpeg', 
        '-rtsp_transport', 'tcp', 
        '-i', 'rtsp://localhost:8554/stream', 
        '-c:v', 'libx264', 
        '-preset', 'veryfast', 
        '-tune', 'zerolatency', 
        '-f', 'hls', 
        '-hls_time', '2', 
        '-hls_list_size', '5', 
        '-hls_flags', 'delete_segments', 
        './hls/stream.m3u8'
    ]
    
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    

    
    socketio.run(app, host="127.0.0.1", port=5001)