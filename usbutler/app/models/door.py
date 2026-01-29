"""Door model."""

from typing import TYPE_CHECKING, List
from sqlalchemy import String, Integer, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.door_event import DoorEvent


class Door(Base):
    __tablename__ = "doors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    gpio_pin: Mapped[int] = mapped_column(Integer)
    gpio_active_low: Mapped[bool] = mapped_column(Boolean, default=False)
    open_hold_time: Mapped[float] = mapped_column(Float, default=3.0)
    events: Mapped[List["DoorEvent"]] = relationship(
        "DoorEvent", back_populates="door", cascade="all, delete-orphan"
    )
