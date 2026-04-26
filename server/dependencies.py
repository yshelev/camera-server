from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from repositories.ZoneRepository import ZoneRepository
from repositories.EventRepository import EventRepository

async def get_zone_repo(db: AsyncSession = Depends(get_db)) -> ZoneRepository:
    return ZoneRepository(db)

async def get_event_repo(db: AsyncSession = Depends(get_db)) -> EventRepository:
    return EventRepository(db)
