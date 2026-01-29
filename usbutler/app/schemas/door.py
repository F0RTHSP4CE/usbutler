"""Door schemas."""

import math
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.models.door_event import DoorEventType


class DoorCreate(BaseModel):
    name: str
    gpio_pin: int
    gpio_active_low: bool = False
    open_hold_time: float = 3.0


class DoorUpdate(BaseModel):
    name: Optional[str] = None
    gpio_pin: Optional[int] = None
    gpio_active_low: Optional[bool] = None
    open_hold_time: Optional[float] = None


class DoorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    gpio_pin: int
    gpio_active_low: bool
    open_hold_time: float


class DoorOpenRequest(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None


class DoorOpenResponse(BaseModel):
    success: bool
    message: str
    door_id: int
    door_name: str


class LastDoorEventResponse(BaseModel):
    door_name: Optional[str] = None
    door_id: Optional[int] = None
    gpio_pin: Optional[int] = None
    event_type: Optional[DoorEventType] = None
    username: Optional[str] = None
    timestamp: Optional[datetime] = None


class DoorEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    door_id: int
    door_name: str
    user_id: Optional[int] = None
    event_type: DoorEventType
    username: Optional[str] = None
    timestamp: datetime


class DoorEventListResponse(BaseModel):
    items: List[DoorEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
