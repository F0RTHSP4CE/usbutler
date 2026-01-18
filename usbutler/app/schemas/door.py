"""Door schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


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
