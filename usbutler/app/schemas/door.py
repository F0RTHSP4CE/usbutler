"""Door schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DoorEventType(str, Enum):
    """Type of door event."""

    API = "api"
    BUTTON = "button"
    CARD = "card"


class DoorBase(BaseModel):
    """Base schema for door data."""

    name: str
    gpio_pin: int
    gpio_active_low: bool = False
    open_hold_time: float = 3.0


class DoorCreate(DoorBase):
    """Schema for creating a door."""

    pass


class DoorUpdate(BaseModel):
    """Schema for updating a door."""

    name: Optional[str] = None
    gpio_pin: Optional[int] = None
    gpio_active_low: Optional[bool] = None
    open_hold_time: Optional[float] = None


class DoorResponse(DoorBase):
    """Schema for door response."""

    model_config = ConfigDict(from_attributes=True)

    id: int


class DoorOpenRequest(BaseModel):
    """Schema for door open request."""

    user_id: Optional[int] = None
    username: Optional[str] = None


class DoorOpenResponse(BaseModel):
    """Schema for door open response."""

    success: bool
    message: str
    door_id: int
    door_name: str


class LastDoorEventResponse(BaseModel):
    """Schema for last door event response."""

    door_name: Optional[str] = None
    door_id: Optional[int] = None
    gpio_pin: Optional[int] = None
    event_type: Optional[DoorEventType] = None
    username: Optional[str] = None
    timestamp: Optional[datetime] = None
