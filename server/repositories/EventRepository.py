from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete, func
from fastapi import HTTPException, status

from models import Event
from schemas import EventSchemaBase
from models import Zone
from datetime import datetime, timezone, timedelta

class EventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def delete_hour_plus_events(self): 
        one_hour_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        
        stmt = delete(Event).where(Event.timestamp < one_hour_ago)
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount
    
    async def delete_events_by_zone(self, zone_id: int) -> int:
        stmt = delete(Event).where(Event.zone_id == zone_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
        
    async def get_events_count_by_zone(self):
        stmt = (
            select(Zone, func.count(Event.id).label("event_count"))
            .outerjoin(Event, Zone.id == Event.zone_id)  
            .group_by(Zone.id)
        )
        
        result = await self.db.execute(stmt)
        zones_with_counts = result.all() 
        
        return [
            {"zone": zone, "event_count": count}
            for zone, count in zones_with_counts
        ]

    async def create(self, data: EventSchemaBase, zone: Zone | None) -> Event:
        if not zone: 
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found zone with given coordinates",
            )
        event = Event(
            left_x=data.left_x,
            right_x=data.right_x,
            top_y=data.top_y,
            bot_y=data.bot_y,
            worker_id=data.worker_id,
            zone_id=zone.id,
        )
        event.zone = zone
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_by_zone_and_time_range(
        self,
        zone_id: int,
        start: datetime, 
        end: datetime
    ) -> list[Event]:
        stmt = select(Event).where(
            Event.zone_id == zone_id, 
            and_(Event.timestamp >= start, Event.timestamp <= end)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())