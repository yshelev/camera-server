from pydantic import BaseModel
from typing import Any
from datetime import datetime

class EventSchemaBase(BaseModel): 
    left_x: int
    right_x: int
    top_y: int
    bot_y: int
    worker_id: int
    zone_x: int
    zone_y: int

class ZoneSchemaBase(BaseModel): 
    zone_x: int
    zone_y: int
    worker_id: int
    
class CreateZonesSchema(BaseModel): 
    zones: list[ZoneSchemaBase]

class MetricData(BaseModel): 
    reason: str
    filtered_centroid_shift: float
    
class ZoneMetricsDataBase(BaseModel): 
    centroid_x: MetricData
    centroid_y: MetricData
    
class ZoneDataBase(BaseModel): 
    zone_key: list[int]
    roi_bbox_scaled: list[float]
    roi_bbox_original: list[int]
    metrics: ZoneMetricsDataBase

class EventDataBase(BaseModel): 
    service_id: int
    time_sec: float
    zones: list[ZoneDataBase]