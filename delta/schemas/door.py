from pydantic import BaseModel, ConfigDict, Field


class GpioSettings(BaseModel):
    """GPIO configuration settings for a door."""

    pin: int = Field(..., ge=0, description="GPIO pin number")
    default_state: bool = Field(
        default=False, description="Default state of the GPIO (False=LOW, True=HIGH)"
    )
    inverted: bool = Field(default=False, description="Whether the logic is inverted")
    pull_up: bool = Field(default=False, description="Enable internal pull-up resistor")


class DoorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Door name")
    gpio_settings: GpioSettings = Field(..., description="GPIO configuration")


class DoorCreate(DoorBase):
    """Schema for creating a new door."""

    pass


class DoorUpdate(BaseModel):
    """Schema for updating an existing door."""

    name: str | None = Field(None, min_length=1, max_length=100)
    gpio_settings: GpioSettings | None = None


class Door(DoorBase):
    """Full door model stored in database."""

    id: str = Field(..., description="Unique door ID")

    model_config = ConfigDict(from_attributes=True)


class DoorResponse(BaseModel):
    """Response schema for a single door."""

    success: bool = True
    data: Door


class DoorListResponse(BaseModel):
    """Response schema for a list of doors."""

    success: bool = True
    data: list[Door]
    total: int
