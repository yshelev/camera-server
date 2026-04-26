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
from math import sqrt
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import async_session
from pathlib import Path

from dependencies import (
    get_event_repo,
    get_zone_repo
)
from schemas import ( 
    EventDataBase, 
    CreateZonesSchema, 
    EventSchemaBase
)

from models import Event

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
ADD_METRIC_THRESHOLD = 50
EVENT_COUNT_THRESHOLD = 20
HLS_DIR = Path("hls")
HLS_DIR.mkdir(exist_ok=True)

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
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job(IntervalTrigger(seconds=10))
async def delete_old_events():
    async with async_session() as session:
        event_repo = EventRepository(session)
        await event_repo.delete_hour_plus_events()
        
        values = await event_repo.get_events_count_by_zone()
        for dct in values:
            zone = dct["zone"]
            event_count = dct["event_count"]
            if event_count >= EVENT_COUNT_THRESHOLD:
                print("broadcasted")
                await manager.broadcast({
                    "camera_id": zone.worker_id, 
                    "zone_x": zone.zone_x, 
                    "zone_y": zone.zone_y
                })
                print(zone.zone_x, zone.zone_y)
                await event_repo.delete_events_by_zone(zone.id)
        
    
@app.get("/")
async def index():
    return FileResponse('templates/index.html')

@app.get("/hls/{filename}")
async def get_stream_file(filename: str): 
    return FileResponse(f'/app/hls/{filename}')

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
        
        metrics = zone_data.metrics
        centroid_x = metrics.centroid_x
        centroid_y = metrics.centroid_y 
        
        if centroid_y.reason != "ok" or centroid_x.reason != "ok":
            print("reason is not ok")
            continue
        if sqrt(centroid_x.filtered_centroid_shift ** 2 + centroid_y.filtered_centroid_shift ** 2) > ADD_METRIC_THRESHOLD: 
            print("decline zone")
            continue
           
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
    cmd = [
        "ffmpeg", 
        "-i", "sample.mov",
        "-c:v", "libx264",  
        "-f", "hls",
        "-hls_list_size", "5",  
        "-hls_flags", "delete_segments+append_list",  
        "-hls_segment_filename", "hls/segment_%03d.ts",
        "hls/stream.m3u8"
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
    except Exception as e: 
        print(e)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
