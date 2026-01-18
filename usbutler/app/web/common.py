"""Shared models, state, and helpers for the web app."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.services.auth_service import AuthService
from app.services.emv_service import EMVCardService
from app.services.reader_control import ReaderControl, get_reader_control
from app.services.door_config_service import DoorConfigService, get_door_config_service

_DEFAULT_DB_PATH = os.getenv("USBUTLER_USERS_DB", "users.json")
_DEFAULT_DOORS_DB_PATH = os.getenv("USBUTLER_DOORS_DB", "doors.json")
_BASE_DIR = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")
_STATIC_DIR = os.path.join(_BASE_DIR, "static")


def _is_web_reader_enabled() -> bool:
    value = os.getenv("USBUTLER_WEB_ENABLE_READER", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


# Shared service instances reused across requests
_auth_service = AuthService(_DEFAULT_DB_PATH)
_door_config_service = get_door_config_service(_DEFAULT_DOORS_DB_PATH)
_emv_service = EMVCardService() if _is_web_reader_enabled() else None
_scan_lock = threading.Lock()
_reader_control = get_reader_control()


# =============================================================================
# Output Models (for responses)
# =============================================================================


class IdentifierOut(BaseModel):
    """Identifier (card) output model."""

    model_config = ConfigDict(from_attributes=True)

    value: str
    type: str
    metadata: dict

    @computed_field
    @property
    def masked(self) -> str:
        """Masked identifier value for display."""
        if len(self.value) <= 4:
            return self.value
        return f"****{self.value[-4:]}"


class UserOut(BaseModel):
    """User output model."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    name: str
    access_level: str
    active: bool
    identifiers: List[IdentifierOut]


class DoorGpioOut(BaseModel):
    """Door GPIO configuration output model."""

    model_config = ConfigDict(from_attributes=True)

    gpio_pin: int
    gpio_chip: str
    active_high: bool


class DoorOut(BaseModel):
    """Door output model."""

    model_config = ConfigDict(from_attributes=True)

    door_id: str
    name: str
    gpio: DoorGpioOut
    auto_lock_delay: float
    enabled: bool
    description: str


class ReaderStateOut(BaseModel):
    """Reader state output model."""

    owner: str
    enabled: bool = False
    claimed: bool | None = None
    already_owned: bool | None = None
    already_released: bool | None = None


class ScanDataOut(BaseModel):
    """Scan data output model."""

    identifier: str
    identifier_type: str | None = None
    tag_type: str | None = None
    card_type: str | None = None
    uid: str | None = None
    pan: str | None = None
    tokenized: bool | None = None
    masked_identifier: str
    timestamp: float
    metadata: Dict[str, Any] | None = None
    issuer: str | None = None
    expiry: str | None = None


# =============================================================================
# Request Models
# =============================================================================


class CreateUserRequest(BaseModel):
    """Request model for creating a new user."""

    name: str = Field(..., description="User's display name")
    identifier: str = Field(..., description="Initial identifier (card) value")
    identifier_type: str | None = Field(
        default="UID", description="Type of identifier (UID, PAN)"
    )
    access_level: str | None = Field(
        default="user", description="Access level (user, admin)"
    )
    metadata: Dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )

    @model_validator(mode="after")
    def normalize(self) -> "CreateUserRequest":
        self.identifier = (self.identifier or "").strip()
        self.identifier_type = (self.identifier_type or "UID").strip()
        self.access_level = (self.access_level or "user").strip().lower()
        self.name = (self.name or "").strip()
        self.metadata = _metadata_to_dict(self.metadata)
        return self


class UpdateUserRequest(BaseModel):
    """Request model for updating a user."""

    name: str | None = Field(default=None, description="User's display name")
    access_level: str | None = Field(
        default=None, description="Access level (user, admin)"
    )
    active: bool | None = Field(default=None, description="Whether user is active")

    @model_validator(mode="after")
    def normalize(self) -> "UpdateUserRequest":
        if self.name is not None:
            self.name = self.name.strip() or None
        if self.access_level is not None:
            self.access_level = self.access_level.strip().lower() or None
        return self


class AddIdentifierRequest(BaseModel):
    """Request model for adding an identifier to a user."""

    value: str = Field(..., description="Identifier value")
    type: str | None = Field(default="UID", description="Type of identifier (UID, PAN)")
    metadata: Dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )

    @model_validator(mode="after")
    def normalize(self) -> "AddIdentifierRequest":
        self.value = (self.value or "").strip()
        self.type = (self.type or "UID").strip()
        self.metadata = _metadata_to_dict(self.metadata)
        return self


class ScanCardRequest(BaseModel):
    """Request model for scanning a card."""

    timeout: float | int | None = Field(default=15, description="Timeout in seconds")


class CreateDoorRequest(BaseModel):
    """Request model for creating a new door."""

    name: str = Field(..., description="Door display name")
    gpio_pin: int = Field(..., description="GPIO pin number")
    gpio_chip: str = Field(
        default="/dev/gpiochip0", description="GPIO chip device path"
    )
    active_high: bool = Field(default=True, description="Whether GPIO is active-high")
    auto_lock_delay: float = Field(
        default=0.5, description="Auto-lock delay in seconds"
    )
    description: str = Field(default="", description="Optional door description")
    door_id: str | None = Field(default=None, description="Optional custom door ID")

    @model_validator(mode="after")
    def normalize(self) -> "CreateDoorRequest":
        self.name = (self.name or "").strip()
        self.gpio_chip = (self.gpio_chip or "/dev/gpiochip0").strip()
        self.description = (self.description or "").strip()
        if self.door_id:
            self.door_id = self.door_id.strip().lower().replace(" ", "-")
        return self


class UpdateDoorRequest(BaseModel):
    """Request model for updating a door."""

    name: str | None = Field(default=None, description="Door display name")
    gpio_pin: int | None = Field(default=None, description="GPIO pin number")
    gpio_chip: str | None = Field(default=None, description="GPIO chip device path")
    active_high: bool | None = Field(
        default=None, description="Whether GPIO is active-high"
    )
    auto_lock_delay: float | None = Field(
        default=None, description="Auto-lock delay in seconds"
    )
    enabled: bool | None = Field(default=None, description="Whether door is enabled")
    description: str | None = Field(
        default=None, description="Optional door description"
    )

    @model_validator(mode="after")
    def normalize(self) -> "UpdateDoorRequest":
        if self.name is not None:
            self.name = self.name.strip() or None
        if self.gpio_chip is not None:
            self.gpio_chip = self.gpio_chip.strip() or None
        if self.description is not None:
            self.description = self.description.strip()
        return self


# =============================================================================
# Response Models
# =============================================================================


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool = True
    message: str | None = None


class ErrorResponse(BaseModel):
    """Generic error response."""

    success: bool = False
    error: str
    message: str | None = None
    # Additional context for specific errors
    existing_user: UserOut | None = None
    tag_type: str | None = None
    card_type: str | None = None
    uid: str | None = None
    tokenized: bool | None = None


class UserResponse(BaseModel):
    """Single user response."""

    success: bool = True
    data: UserOut


class UserListResponse(BaseModel):
    """List of users response."""

    success: bool = True
    data: List[UserOut]


class IdentifierListResponse(BaseModel):
    """List of identifiers response."""

    success: bool = True
    data: List[IdentifierOut]
    user_id: str


class DoorResponse(BaseModel):
    """Single door response."""

    success: bool = True
    data: DoorOut


class DoorListResponse(BaseModel):
    """List of doors response."""

    success: bool = True
    data: List[DoorOut]


class ReaderResponse(BaseModel):
    """Reader state response."""

    success: bool = True
    data: ReaderStateOut


class ScanResponse(BaseModel):
    """Card scan response."""

    success: bool = True
    data: Dict[str, Any]
    already_registered: bool
    existing_user: UserOut | None = None


# =============================================================================
# Helper Functions
# =============================================================================


def _metadata_to_dict(metadata: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Clean up metadata dictionary."""
    if not isinstance(metadata, dict):
        return None
    return {key: value for key, value in metadata.items() if value is not None} or None


# =============================================================================
# Dependency Injection
# =============================================================================


def get_auth_service() -> AuthService:
    """Get the shared AuthService instance."""
    return _auth_service


def get_emv_service() -> EMVCardService | None:
    """Get the shared EMVCardService instance (if enabled)."""
    return _emv_service


def get_scan_lock() -> threading.Lock:
    """Get the shared scan lock."""
    return _scan_lock


def get_reader_control() -> ReaderControl:
    """Get the shared ReaderControl instance."""
    return _reader_control


def get_door_config() -> DoorConfigService:
    """Get the shared DoorConfigService instance."""
    return _door_config_service
