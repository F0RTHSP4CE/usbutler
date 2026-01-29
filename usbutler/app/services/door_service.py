"""Door service for database operations."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.door import Door
from app.schemas.door import DoorCreate, DoorUpdate


class DoorService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Door]:
        return list(self.db.scalars(select(Door).offset(skip).limit(limit)).all())

    def get_by_id(self, door_id: int) -> Optional[Door]:
        return self.db.scalars(select(Door).where(Door.id == door_id)).first()

    def get_by_name(self, name: str) -> Optional[Door]:
        return self.db.scalars(select(Door).where(Door.name == name)).first()

    def create(self, data: DoorCreate) -> Door:
        door = Door(
            name=data.name,
            gpio_pin=data.gpio_pin,
            gpio_active_low=data.gpio_active_low,
            open_hold_time=data.open_hold_time,
        )
        self.db.add(door)
        self.db.commit()
        self.db.refresh(door)
        return door

    def update(self, door_id: int, data: DoorUpdate) -> Optional[Door]:
        door = self.get_by_id(door_id)
        if not door:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(door, k, v)
        self.db.commit()
        self.db.refresh(door)
        return door

    def delete(self, door_id: int) -> bool:
        door = self.get_by_id(door_id)
        if not door:
            return False
        self.db.delete(door)
        self.db.commit()
        return True
