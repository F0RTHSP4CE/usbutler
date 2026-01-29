"""Door event service for database operations."""

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from app.models.door import Door
from app.models.door_event import DoorEvent, DoorEventType


class DoorEventService:
    """Service for door event CRUD operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        door_id: int,
        event_type: DoorEventType,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> DoorEvent:
        """Create a new door event."""
        event = DoorEvent(
            door_id=door_id,
            event_type=event_type,
            user_id=user_id,
            username=username,
            timestamp=timestamp or datetime.utcnow(),
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_by_id(self, event_id: int) -> Optional[DoorEvent]:
        """Get an event by ID."""
        stmt = select(DoorEvent).where(DoorEvent.id == event_id)
        return self.db.scalars(stmt).first()

    def get_latest(self) -> Optional[DoorEvent]:
        """Get the most recent door event."""
        stmt = select(DoorEvent).order_by(desc(DoorEvent.timestamp)).limit(1)
        return self.db.scalars(stmt).first()

    def get_history(
        self,
        door_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[DoorEvent], int]:
        """Get door event history with pagination.

        Args:
            door_id: Optional filter by door ID
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Tuple of (list of events, total count)
        """
        # Base query
        base_query = select(DoorEvent)
        count_query = select(func.count(DoorEvent.id))

        if door_id is not None:
            base_query = base_query.where(DoorEvent.door_id == door_id)
            count_query = count_query.where(DoorEvent.door_id == door_id)

        # Get total count
        total = self.db.scalar(count_query) or 0

        # Get paginated results
        offset = (page - 1) * page_size
        stmt = (
            base_query.order_by(desc(DoorEvent.timestamp))
            .offset(offset)
            .limit(page_size)
        )
        events = list(self.db.scalars(stmt).all())

        return events, total

    def get_events_for_door(self, door_id: int, limit: int = 100) -> List[DoorEvent]:
        """Get recent events for a specific door."""
        stmt = (
            select(DoorEvent)
            .where(DoorEvent.door_id == door_id)
            .order_by(desc(DoorEvent.timestamp))
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_events_by_user(self, user_id: int, limit: int = 100) -> List[DoorEvent]:
        """Get recent events for a specific user."""
        stmt = (
            select(DoorEvent)
            .where(DoorEvent.user_id == user_id)
            .order_by(desc(DoorEvent.timestamp))
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())
