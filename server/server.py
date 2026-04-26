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
from repositories.EventRepository import EventRepository
from repositories.ZoneRepository import ZoneRepository
from fastapi import Depends

from dependencies import (
    get_event_repo,
    get_zone_repo
)
from schemas import ( 
    EventDataBase, 
    CreateZonesSchema, 
    EventSchemaBase
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

@app.post("/create_zone")
async def create_zones(zones: CreateZonesSchema, zone_repo: ZoneRepository = Depends(get_zone_repo)): 
    zones = await zone_repo.create_many(zones)
    return {"status": "ok"}

@app.post("/update_data")
async def update_values(
    data: EventDataBase,
    zone_repo: ZoneRepository = Depends(get_zone_repo), 
    event_repo: EventRepository = Depends(get_event_repo)
): 
    service_id = data.service_id
    for zone_data in data.zones: 
        zone_x, zone_y = zone_data.zone_key
        bbox_lx, bbox_ty, bbox_rx, bbox_by = zone_data.roi_bbox_original
        event_schema_base = EventSchemaBase(
            left_x=bbox_lx,
            right_x=bbox_rx,
            top_y=bbox_ty,
            bot_y=bbox_by,
            worker_id=service_id, 
            zone_x=zone_x, 
            zone_y=zone_y
        )
        zone = await zone_repo.get_by_coords(service_id,  zone_x, zone_y)
        await event_repo.create(event_schema_base, zone)
        

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__": 
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )