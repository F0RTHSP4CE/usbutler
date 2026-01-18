from fastapi import Depends, HTTPException, status

from database import JsonDatabase, get_database
from schemas import Door, DoorCreate, DoorUpdate


class DoorService:
    """Service layer for door operations."""

    COLLECTION = "doors"

    def __init__(self, db: JsonDatabase):
        self.db = db

    def get_all(self) -> list[Door]:
        """Get all doors."""
        doors_data = self.db.get_all(self.COLLECTION)
        return [Door(**door) for door in doors_data.values()]

    def get_by_id(self, door_id: str) -> Door:
        """Get a door by ID."""
        door_data = self.db.get_by_id(self.COLLECTION, door_id)
        if not door_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Door with id '{door_id}' not found",
            )
        return Door(**door_data)

    def get_by_name(self, name: str) -> Door | None:
        """Get a door by name."""
        doors = self.db.find_by_field(self.COLLECTION, "name", name)
        if doors:
            return Door(**doors[0])
        return None

    def get_by_gpio_pin(self, pin: int) -> Door | None:
        """Get a door by GPIO pin number."""
        doors_data = self.db.get_all(self.COLLECTION)
        for door_data in doors_data.values():
            if door_data.get("gpio_settings", {}).get("pin") == pin:
                return Door(**door_data)
        return None

    def create(self, door_data: DoorCreate) -> Door:
        """Create a new door."""
        # Check for duplicate name
        existing = self.get_by_name(door_data.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Door with name '{door_data.name}' already exists",
            )

        # Check for duplicate GPIO pin
        existing_pin = self.get_by_gpio_pin(door_data.gpio_settings.pin)
        if existing_pin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"GPIO pin {door_data.gpio_settings.pin} is already in use by door '{existing_pin.name}'",
            )

        door_id = self.db.generate_id()
        door = Door(
            id=door_id, name=door_data.name, gpio_settings=door_data.gpio_settings
        )
        self.db.create(self.COLLECTION, door_id, door.model_dump())
        return door

    def update(self, door_id: str, door_data: DoorUpdate) -> Door:
        """Update an existing door."""
        existing = self.get_by_id(door_id)

        # Check for duplicate name if changing
        if door_data.name and door_data.name != existing.name:
            duplicate = self.get_by_name(door_data.name)
            if duplicate and duplicate.id != door_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Door with name '{door_data.name}' already exists",
                )

        # Check for duplicate GPIO pin if changing
        if door_data.gpio_settings:
            existing_pin = self.get_by_gpio_pin(door_data.gpio_settings.pin)
            if existing_pin and existing_pin.id != door_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"GPIO pin {door_data.gpio_settings.pin} is already in use by door '{existing_pin.name}'",
                )

        update_data = door_data.model_dump(exclude_unset=True)
        merged_data = existing.model_dump()
        merged_data.update(update_data)
        updated_door = Door.model_validate(merged_data)
        self.db.update(self.COLLECTION, door_id, updated_door.model_dump())
        return updated_door

    def delete(self, door_id: str) -> bool:
        """Delete a door."""
        # Ensure door exists
        self.get_by_id(door_id)
        return self.db.delete(self.COLLECTION, door_id)


def get_door_service(db: JsonDatabase = Depends(get_database)) -> DoorService:
    """Dependency injection for DoorService."""
    return DoorService(db)
