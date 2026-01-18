"""Door configuration service - manages door settings stored in JSON."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from pydantic import BaseModel, Field


class DoorConfigError(Exception):
    """Base error for door configuration operations."""

    code: str = "error"
    default_message: str = "An error occurred"

    def __init__(self, message: str | None = None, **kwargs):
        self.code = self.__class__.code
        self.message = message or self.default_message
        for key, value in kwargs.items():
            setattr(self, key, value)
        super().__init__(self.message)


class DoorNotFoundError(DoorConfigError):
    code = "not_found"
    default_message = "Door not found"


class DoorExistsError(DoorConfigError):
    code = "door_exists"
    default_message = "Door with this ID already exists"


class MissingDoorNameError(DoorConfigError):
    code = "missing_name"
    default_message = "Door name is required"


class DoorGpioConfig(BaseModel):
    """GPIO configuration for a door."""

    gpio_pin: int = 17
    gpio_chip: str = "/dev/gpiochip0"
    active_high: bool = True


class Door(BaseModel):
    """Door configuration model."""

    door_id: str
    name: str
    gpio: DoorGpioConfig = Field(default_factory=DoorGpioConfig)
    auto_lock_delay: float = 0.5
    enabled: bool = True
    description: str = ""


class DoorConfigService:
    """Service for managing door configurations."""

    def __init__(self, db_file: str = "doors.json"):
        self.db_file = db_file
        self.doors = self._load_doors()

    def list_doors(self) -> list[Door]:
        """List all configured doors."""
        return list(self.doors.values())

    def get_door_or_raise(self, door_id: str) -> Door:
        """Get a door by ID or raise DoorNotFoundError."""
        door = self.doors.get(door_id)
        if not door:
            raise DoorNotFoundError(f"Door '{door_id}' not found")
        return door

    def get_door(self, door_id: str) -> Door | None:
        """Get a door by ID or return None."""
        return self.doors.get(door_id)

    def create_door_or_raise(
        self,
        name: str,
        gpio_pin: int,
        gpio_chip: str = "/dev/gpiochip0",
        active_high: bool = True,
        auto_lock_delay: float = 0.5,
        description: str = "",
        door_id: str | None = None,
    ) -> Door:
        """Create a new door configuration."""
        if not name:
            raise MissingDoorNameError()

        # Generate or validate door_id
        if door_id:
            if door_id in self.doors:
                raise DoorExistsError(f"Door with ID '{door_id}' already exists")
        else:
            door_id = str(uuid.uuid4())

        gpio_config = DoorGpioConfig(
            gpio_pin=gpio_pin,
            gpio_chip=gpio_chip,
            active_high=active_high,
        )

        door = Door(
            door_id=door_id,
            name=name,
            gpio=gpio_config,
            auto_lock_delay=auto_lock_delay,
            enabled=True,
            description=description,
        )

        self.doors[door_id] = door
        self._save_doors()
        return door

    def update_door_or_raise(
        self,
        door_id: str,
        name: str | None = None,
        gpio_pin: int | None = None,
        gpio_chip: str | None = None,
        active_high: bool | None = None,
        auto_lock_delay: float | None = None,
        enabled: bool | None = None,
        description: str | None = None,
    ) -> Door:
        """Update an existing door configuration."""
        door = self.doors.get(door_id)
        if not door:
            raise DoorNotFoundError(f"Door '{door_id}' not found")

        if name is not None:
            if not name.strip():
                raise MissingDoorNameError("Door name cannot be empty")
            door.name = name.strip()

        # Update GPIO settings
        if gpio_pin is not None:
            door.gpio.gpio_pin = gpio_pin
        if gpio_chip is not None:
            door.gpio.gpio_chip = gpio_chip
        if active_high is not None:
            door.gpio.active_high = active_high

        if auto_lock_delay is not None:
            door.auto_lock_delay = float(auto_lock_delay)
        if enabled is not None:
            door.enabled = enabled
        if description is not None:
            door.description = description

        self._save_doors()
        return door

    def delete_door_or_raise(self, door_id: str) -> None:
        """Delete a door configuration."""
        if door_id not in self.doors:
            raise DoorNotFoundError(f"Door '{door_id}' not found")

        del self.doors[door_id]
        self._save_doors()

    def _load_doors(self) -> dict[str, Door]:
        """Load doors from JSON file."""
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return self._create_default_doors()

        if not raw_data:
            return self._create_default_doors()

        if isinstance(raw_data, dict) and "doors" in raw_data:
            doors: dict[str, Door] = {}
            for door_id, payload in raw_data.get("doors", {}).items():
                if not isinstance(payload, dict):
                    continue
                doors[door_id] = Door(door_id=door_id, **payload)

            if not doors:
                return self._create_default_doors()
            return doors

        return self._create_default_doors()

    def _create_default_doors(self) -> dict[str, Door]:
        """Create default door configurations."""
        defaults = {
            "main": Door(
                door_id="main",
                name="Main Door",
                gpio=DoorGpioConfig(gpio_pin=17),
                description="Primary entrance",
            ),
            "gate": Door(
                door_id="gate",
                name="Gate",
                gpio=DoorGpioConfig(gpio_pin=27),
                description="External gate",
            ),
        }
        self.doors = defaults
        self._save_doors()
        return defaults

    def _save_doors(self) -> None:
        """Save doors to JSON file."""
        payload = {
            "doors": {
                door_id: door.model_dump(exclude={"door_id"})
                for door_id, door in self.doors.items()
            },
        }
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())


# Singleton instance
_door_config_service: DoorConfigService | None = None


def get_door_config_service(db_file: str = "doors.json") -> DoorConfigService:
    """Get the shared DoorConfigService instance."""
    global _door_config_service
    if _door_config_service is None:
        _door_config_service = DoorConfigService(db_file)
    return _door_config_service


__all__ = [
    "Door",
    "DoorGpioConfig",
    "DoorConfigService",
    "DoorConfigError",
    "DoorNotFoundError",
    "DoorExistsError",
    "MissingDoorNameError",
    "get_door_config_service",
]
