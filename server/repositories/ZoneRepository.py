from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException, status

from models import Zone
from schemas import ZoneSchemaBase, CreateZonesSchema

class ZoneRepository:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, data: ZoneSchemaBase):
        existing = await self.get_by_coords(data.worker_id, data.zone_x, data.zone_y)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Zone with these coordinates already exists for this worker",
            )

        zone = Zone(**data.model_dump())
        self.db.add(zone)
        await self.db.commit()
        await self.db.refresh(zone)
        return zone
    
    async def create_many(self, data: CreateZonesSchema): 
        zones = [Zone(**zone.model_dump())  for zone in data.zones]
        self.db.add_all(zones)
        await self.db.commit()
        
    async def get_by_coords(self, worker_id: int, zone_x: int, zone_y: int):
        stmt = select(Zone).where(
            Zone.worker_id == worker_id,
            Zone.zone_x == zone_x,
            Zone.zone_y == zone_y,
        )
        
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()