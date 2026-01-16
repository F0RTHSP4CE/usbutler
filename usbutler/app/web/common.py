"""Shared models, state, and helpers for the web app."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.services.auth_service import AuthenticationService, Identifier, User
from app.services.emv_service import EMVCardService
from app.services.reader_control import ReaderControl

_DEFAULT_DB_PATH = os.getenv("USBUTLER_USERS_DB", "users.json")
_BASE_DIR = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")
_STATIC_DIR = os.path.join(_BASE_DIR, "static")


def _is_web_reader_enabled() -> bool:
    value = os.getenv("USBUTLER_WEB_ENABLE_READER", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


# Shared service instances reused across requests
_auth_service = AuthenticationService(_DEFAULT_DB_PATH)
_emv_service = EMVCardService() if _is_web_reader_enabled() else None
_scan_lock = threading.Lock()
_last_scan: "ScanSummary | None" = None
_reader_control: ReaderControl | None = None


class IdentifierOut(BaseModel):
    value: str
    type: str
    primary: bool
    masked: str
    metadata: dict


class UserOut(BaseModel):
    user_id: str
    name: str
    access_level: str
    active: bool
    identifiers: List[IdentifierOut]
    primary_identifier: IdentifierOut | None = None


class StatsOut(BaseModel):
    total: int
    active: int
    inactive: int


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
    make_primary: bool = False
    name: str | None = None
    metadata: Dict[str, Any] | None = None


class SuccessResponse(BaseModel):
    success: bool = True


class UserResponse(SuccessResponse):
    user: UserOut


class UserListResponse(SuccessResponse):
    users: List[UserOut]
    stats: StatsOut
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


def _serialize_identifier(identifier: Identifier) -> IdentifierOut:
    return IdentifierOut(
        value=identifier.value,
        type=identifier.type,
        primary=identifier.primary,
        masked=identifier.mask(),
        metadata=identifier.metadata,
    )


def _serialize_user(user: User) -> UserOut:
    identifiers = [_serialize_identifier(identifier) for identifier in user.identifiers]
    primary = user.primary_identifier()
    return UserOut(
        user_id=user.user_id,
        name=user.name,
        access_level=user.access_level,
        active=user.active,
        identifiers=identifiers,
        primary_identifier=_serialize_identifier(primary) if primary else None,
    )


def _build_stats(users: List[User]) -> StatsOut:
    total = len(users)
    active = sum(1 for user in users if user.active)
    return StatsOut(total=total, active=active, inactive=total - active)


def _get_reader_control() -> ReaderControl:
    global _reader_control
    if _reader_control is None:
        _reader_control = ReaderControl()
    return _reader_control


def set_reader_control(control: ReaderControl | None) -> None:
    global _reader_control
    _reader_control = control


def reset_services(user_db_path: str | None = None) -> None:
    """Reset service instances (intended for tests)."""

    global _auth_service, _emv_service, _last_scan, _reader_control
    db_path = user_db_path or os.getenv("USBUTLER_USERS_DB", "users.json")
    _auth_service = AuthenticationService(db_path)
    _emv_service = EMVCardService() if _is_web_reader_enabled() else None
    _last_scan = None
    _reader_control = None


def _serialize_reader_state(reader_control: ReaderControl) -> ReaderStateOut:
    state = reader_control.get_state()
    owner = str(state.get("owner") or "door")
    updated_at = state.get("updated_at")
    return ReaderStateOut(
        owner=owner,
        owned_by_web=owner == "web",
        owned_by_door=owner == "door",
        updated_at=updated_at if isinstance(updated_at, (int, float)) else None,
    )


def _serialize_reader_update(state: Dict[str, object]) -> ReaderControlUpdate:
    owner = str(state.get("owner") or "door")
    updated_at = state.get("updated_at")
    previous_owner = state.get("previous_owner")
    return ReaderControlUpdate(
        owner=owner,
        updated_at=updated_at if isinstance(updated_at, (int, float)) else None,
        previous_owner=str(previous_owner) if previous_owner is not None else None,
    )


def _metadata_to_dict(metadata: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        return None
    data = {key: value for key, value in metadata.items() if value is not None}
    return data or None


def get_auth_service() -> AuthenticationService:
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


def get_reader_control() -> ReaderControl:
    return _get_reader_control()
