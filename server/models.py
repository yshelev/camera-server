from pydantic import BaseModel
from typing import Any


class MetricsData(BaseModel):
    data: dict[str, Any]

class AnomalyData(BaseModel):
    data: dict[str, Any]

class MetricData(BaseModel): 
    reason: str
    filtered_centroid_shift: float
    
class ServiceZoneMetricsData(BaseModel): 
    centroid_x: MetricData
    centroid_y: MetricData
    
class ServiceZoneData(BaseModel): 
    zone_key: list[int]
    roi_bbox_scaled: list[float]
    roi_bbox_original: list[int]
    metrics: ServiceZoneMetricsData

class ServiceSnapshotData(BaseModel): 
    service_id: int
    zones: list[ServiceZoneData]