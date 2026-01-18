"""Door service for database operations."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.door import Door
from app.schemas.door import DoorCreate, DoorUpdate


class DoorService:
    """Service for door CRUD operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Door]:
        """Get all doors with pagination."""
        stmt = select(Door).offset(skip).limit(limit)
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, door_id: int) -> Optional[Door]:
        """Get a door by ID."""
        stmt = select(Door).where(Door.id == door_id)
        return self.db.scalars(stmt).first()

    def get_by_name(self, name: str) -> Optional[Door]:
        """Get a door by name."""
        stmt = select(Door).where(Door.name == name)
        return self.db.scalars(stmt).first()

    def create(self, door_data: DoorCreate) -> Door:
        """Create a new door."""
        door = Door(
            name=door_data.name,
            gpio_pin=door_data.gpio_pin,
            gpio_active_low=door_data.gpio_active_low,
            open_hold_time=door_data.open_hold_time,
        )
        self.db.add(door)
        self.db.commit()
        self.db.refresh(door)
        return door

    def update(self, door_id: int, door_data: DoorUpdate) -> Optional[Door]:
        """Update an existing door."""
        door = self.get_by_id(door_id)
        if not door:
            return None

        update_data = door_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(door, field, value)

        self.db.commit()
        self.db.refresh(door)
        return door

    def delete(self, door_id: int) -> bool:
        """Delete a door."""
        door = self.get_by_id(door_id)
        if not door:
            return False

        self.db.delete(door)
        self.db.commit()
        return True
