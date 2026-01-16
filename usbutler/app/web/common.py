"""Shared models, state, and helpers for the web app."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.services.auth_service import AuthService
from app.services.emv_service import EMVCardService

_DEFAULT_DB_PATH = os.getenv("USBUTLER_USERS_DB", "users.json")
_BASE_DIR = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")
_STATIC_DIR = os.path.join(_BASE_DIR, "static")


def _is_web_reader_enabled() -> bool:
    value = os.getenv("USBUTLER_WEB_ENABLE_READER", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


# Shared service instances reused across requests
_auth_service = AuthService(_DEFAULT_DB_PATH)
_emv_service = EMVCardService() if _is_web_reader_enabled() else None
_scan_lock = threading.Lock()
_last_scan: "ScanSummary | None" = None


class IdentifierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str
    type: str
    primary: bool
    metadata: dict

    @computed_field
    @property
    def masked(self) -> str:
        if len(self.value) <= 4:
            return self.value
        return f"****{self.value[-4:]}"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    name: str
    access_level: str
    active: bool
    identifiers: List[IdentifierOut]


class ReaderStateOut(BaseModel):
    owner: str
    owned_by_web: bool
    owned_by_door: bool
    updated_at: float | None = None


class ReaderControlUpdate(BaseModel):
    owner: str
    updated_at: float | None = None
    previous_owner: str | None = None


class ScanSummary(BaseModel):
    identifier: str
    masked_identifier: str
    identifier_type: str | None
    timestamp: float
    already_registered: bool
    existing_user_name: str | None = None
    existing_user_id: str | None = None
    metadata: Dict[str, Any] | None = None


class ScanRequest(BaseModel):
    timeout: float | int | None = Field(default=15)


class ScanResponse(BaseModel):
    success: bool = True
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
    already_registered: bool
    existing_user: UserOut | None = None


class ScanErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: str | None = None
    tag_type: str | None = None
    card_type: str | None = None
    uid: str | None = None
    tokenized: bool | None = None


class AddUserRequest(BaseModel):
    identifier: str | None = None
    identifier_type: str | None = "UID"
    access_level: str | None = "user"
    user_id: str | None = None
    name: str | None = None
    metadata: Dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "AddUserRequest":
        self.identifier = (self.identifier or "").strip() or None
        self.identifier_type = (self.identifier_type or "UID").strip() or "UID"
        self.access_level = (self.access_level or "user").strip().lower() or "user"
        self.user_id = (self.user_id or "").strip() or None
        self.name = (self.name or "").strip()
        self.metadata = _metadata_to_dict(self.metadata)
        return self


class SuccessResponse(BaseModel):
    success: bool = True


class UserResponse(SuccessResponse):
    user: UserOut


class UserListResponse(SuccessResponse):
    users: List[UserOut]
    last_scan: ScanSummary | None = None
    reader_enabled: bool
    reader_state: ReaderStateOut


class ReaderStateResponse(SuccessResponse):
    state: ReaderStateOut
    reader_enabled: bool


class ReaderClaimResponse(SuccessResponse):
    state: ReaderStateOut
    reader_enabled: bool | None = None
    already_owned: bool | None = None
    updated: ReaderControlUpdate | None = None


class ReaderReleaseResponse(SuccessResponse):
    state: ReaderStateOut
    reader_enabled: bool | None = None
    already_released: bool | None = None
    updated: ReaderControlUpdate | None = None


class RemoveIdentifierResponse(SuccessResponse):
    user_removed: bool | None = None
    user: UserOut | None = None


class UserErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: str | None = None
    existing_user: UserOut | None = None


def _metadata_to_dict(metadata: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    return {key: value for key, value in metadata.items() if value is not None} or None


def get_auth_service() -> AuthService:
    return _auth_service


def get_emv_service() -> EMVCardService | None:
    return _emv_service


def get_scan_lock() -> threading.Lock:
    return _scan_lock


def get_last_scan() -> ScanSummary | None:
    return _last_scan


def set_last_scan(scan: ScanSummary | None) -> None:
    global _last_scan
    _last_scan = scan
