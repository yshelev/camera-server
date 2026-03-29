from flask import Flask, request
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/metrics', methods=['POST'])
def metrics():
    data = request.json
    socketio.emit('metrics', data)
    
    return {"status": "ok"}

@socketio.on('connect')
def connect():
    print("client connected")

if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000)