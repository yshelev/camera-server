from flask import Flask, request, send_from_directory, Response
from flask_socketio import SocketIO
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/hls/<path:filename>')
def hls(filename):
    return send_from_directory('hls', filename)

@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')

@app.route('/metrics', methods=['POST'])
def metrics():
    data = request.json
    socketio.emit('metrics', data)
    
    return {"status": "ok"}

@socketio.on('connect')
def connect():
    print("client connected")

if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5001)