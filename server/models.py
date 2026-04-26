from datetime import datetime
from typing import Optional, List

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import func
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase): 
    pass

class Zone(Base):
    __tablename__ = "zone"
    __table_args__ = (
        UniqueConstraint("worker_id", "zone_x", "zone_y", name="uix_zone_coords"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int]
    zone_x: Mapped[int]
    zone_y: Mapped[int]

    events: Mapped[List["Event"]] = relationship(back_populates="zone", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        default=utc_now, 
        server_default=func.now()
    )
    left_x: Mapped[int]
    right_x: Mapped[int]
    top_y: Mapped[int]
    bot_y: Mapped[int]
    worker_id: Mapped[int]
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("zone.id", ondelete="CASCADE"))

    zone: Mapped[Optional["Zone"]] = relationship(back_populates="events")