"""Door event model for tracking door opening history."""

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
    """Type of door event."""

    API = "api"
    BUTTON = "button"
    CARD = "card"


class DoorEvent(Base):
    """Door event model for tracking door opening history."""

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
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    # Relationships
    door: Mapped["Door"] = relationship("Door", back_populates="events")
    user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<DoorEvent(id={self.id}, door_id={self.door_id}, event_type={self.event_type}, timestamp={self.timestamp})>"
