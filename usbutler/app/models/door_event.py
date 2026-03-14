"""Door event model."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Enum, ForeignKey, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.door import Door
    from app.models.user import User


class DoorEventType(str, enum.Enum):
    API = "api"
    BUTTON = "button"
    CARD = "card"


class DoorEvent(Base):
    __tablename__ = "door_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    door_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("doors.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[DoorEventType] = mapped_column(Enum(DoorEventType))
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    door: Mapped["Door"] = relationship("Door", back_populates="events")
    user: Mapped[Optional["User"]] = relationship("User")
