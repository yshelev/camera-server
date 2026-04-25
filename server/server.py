from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import subprocess
import os
import asyncio
from typing import Dict, Any
import json

from models import (
    MetricsData, 
    AnomalyData, 
    MetricData, 
    ServiceZoneMetricsData, 
    ServiceZoneData, 
    ServiceSnapshotData
)

app = FastAPI()

os.makedirs("hls", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/hls", StaticFiles(directory="hls"), name="hls")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()
    
@app.get("/")
async def index():
    return FileResponse('templates/index.html')

@app.post("/metrics")
async def metrics(metrics_data: MetricsData):
    await manager.broadcast({"type": "metrics", "data": metrics_data.data})
    return {"status": "ok"}

@app.post("/anomaly")
async def anomaly(anomaly_data: AnomalyData):
    await manager.broadcast({"type": "anomaly", "data": anomaly_data.data})
    return {"status": "ok"}

@app.post("/update_data")
async def update_values(data: ServiceSnapshotData): 
    service_id = data.service_id
    print(service_id)
    for zone_data in data.zones: 
        print(zone_data.roi_bbox_original)
        print(zone_data.metrics.centroid_x)
        print(zone_data.metrics.centroid_y)
    
    

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received from client: {data}")
            
            if data == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("Client disconnected")

if __name__ == "__main__": 
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
        log_level="info"
    )