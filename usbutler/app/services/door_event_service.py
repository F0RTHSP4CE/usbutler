"""Door event service for database operations."""

import math
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from app.models.door_event import DoorEvent, DoorEventType


class DoorEventService:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        door_id: int,
        event_type: DoorEventType,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        on_behalf_of: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> DoorEvent:
        event = DoorEvent(
            door_id=door_id,
            event_type=event_type,
            user_id=user_id,
            username=username,
            on_behalf_of=on_behalf_of,
            timestamp=timestamp or datetime.utcnow(),
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_history(
        self, door_id: Optional[int] = None, page: int = 1, page_size: int = 50
    ) -> Tuple[List[DoorEvent], int]:
        base = select(DoorEvent)
        count_q = select(func.count(DoorEvent.id))

        if door_id:
            base = base.where(DoorEvent.door_id == door_id)
            count_q = count_q.where(DoorEvent.door_id == door_id)

        total = self.db.scalar(count_q) or 0
        events = list(
            self.db.scalars(
                base.order_by(desc(DoorEvent.timestamp))
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return events, total
