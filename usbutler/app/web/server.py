"""FastAPI-based web interface for managing users and enrolling new cards."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Union

from fastapi import Body, Depends, FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

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
_ALLOWED_METADATA_KEYS = {
    "issuer",
    "expiry",
    "card_type",
    "tag_type",
    "atr_hex",
    "atr_hex_compact",
    "atr_summary",
}


class MetadataInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issuer: str | None = None
    expiry: str | None = None
    card_type: str | None = None
    tag_type: str | None = None
    atr_hex: str | None = None
    atr_hex_compact: str | None = None
    atr_summary: List[str] | None = None


class MetadataOut(MetadataInput):
    expiry_formatted: str | None = None


class IdentifierOut(BaseModel):
    value: str
    type: str
    primary: bool
    masked: str
    metadata: MetadataOut | None = None


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
    metadata: MetadataOut | None = None


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
    metadata: MetadataOut | None = None
    issuer: str | None = None
    expiry: str | None = None
    expiry_formatted: str | None = None
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
    metadata: MetadataInput | None = None


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


def _filter_metadata(value: Any) -> MetadataInput:
    if not isinstance(value, dict):
        return MetadataInput()
    filtered: Dict[str, Any] = {}
    for key in _ALLOWED_METADATA_KEYS:
        if key in value:
            item = value[key]
            if item is None:
                continue
            if key == "atr_summary" and isinstance(item, list):
                filtered[key] = [str(entry) for entry in item[:10]]
            else:
                if isinstance(item, (str, int, float, bool)):
                    filtered[key] = item
                elif isinstance(item, (bytes, bytearray)):
                    filtered[key] = item.hex()
                else:
                    continue
    return MetadataInput(**filtered)


def _format_expiry(expiry: Any) -> str | None:
    if expiry is None:
        return None
    digits = "".join(ch for ch in str(expiry) if ch.isdigit())
    if len(digits) == 4:
        year = digits[:2]
        month = digits[2:4]
        return f"{month}/{year}"
    return str(expiry)


def _present_metadata(metadata: MetadataInput | None) -> MetadataOut | None:
    if metadata is None:
        return None
    view = metadata.model_dump(exclude_none=True)
    if not view:
        return None
    expiry = view.get("expiry")
    formatted = _format_expiry(expiry)
    if expiry and formatted and formatted != expiry:
        view["expiry_formatted"] = formatted
    return MetadataOut(**view)


def _build_scan_metadata(scan: Any) -> MetadataOut | None:
    metadata = {
        "issuer": getattr(scan, "issuer", None),
        "expiry": getattr(scan, "expiry", None),
        "card_type": getattr(scan, "card_type", None),
        "tag_type": getattr(scan, "tag_type", None),
        "atr_hex": getattr(scan, "atr_hex", None),
        "atr_hex_compact": getattr(scan, "atr_hex_compact", None),
        "atr_summary": getattr(scan, "atr_summary", None),
    }
    return _present_metadata(_filter_metadata(metadata))


def _serialize_identifier(identifier: Identifier) -> IdentifierOut:
    metadata = _present_metadata(_filter_metadata(identifier.metadata))
    return IdentifierOut(
        value=identifier.value,
        type=identifier.type,
        primary=identifier.primary,
        masked=identifier.mask(),
        metadata=metadata,
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


def _metadata_to_dict(metadata: MetadataInput | None) -> Dict[str, Any] | None:
    if metadata is None:
        return None
    data = metadata.model_dump(exclude_none=True)
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


def create_app(reader_control: ReaderControl | None = None) -> FastAPI:
    if reader_control is not None:
        set_reader_control(reader_control)
    app = FastAPI()
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        auth_service: AuthenticationService = Depends(get_auth_service),
        reader_control_dep: ReaderControl = Depends(get_reader_control),
        last_scan: ScanSummary | None = Depends(get_last_scan),
    ) -> HTMLResponse:
        users = list(auth_service.list_users().values())
        serialized = [_serialize_user(user) for user in users]
        serialized.sort(key=lambda item: item.name.lower())
        stats = _build_stats(users)
        reader_state = _serialize_reader_state(reader_control_dep)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "users": serialized,
                "stats": stats,
                "last_scan": last_scan.model_dump() if last_scan else None,
                "reader_enabled": _is_web_reader_enabled(),
                "reader_state": reader_state.model_dump(),
            },
        )

    @app.get("/api/users", response_model=UserListResponse)
    async def api_list_users(
        auth_service: AuthenticationService = Depends(get_auth_service),
        reader_control_dep: ReaderControl = Depends(get_reader_control),
        last_scan: ScanSummary | None = Depends(get_last_scan),
    ) -> UserListResponse:
        users = list(auth_service.list_users().values())
        serialized = [_serialize_user(user) for user in users]
        serialized.sort(key=lambda item: item.name.lower())
        return UserListResponse(
            users=serialized,
            stats=_build_stats(users),
            last_scan=last_scan,
            reader_enabled=_is_web_reader_enabled(),
            reader_state=_serialize_reader_state(reader_control_dep),
        )

    @app.post(
        "/api/scan-card",
        response_model=Union[ScanResponse, ScanErrorResponse],
    )
    async def api_scan_card(
        response: Response,
        payload: ScanRequest = Body(default_factory=ScanRequest),
        auth_service: AuthenticationService = Depends(get_auth_service),
        emv_service: EMVCardService | None = Depends(get_emv_service),
        reader_control_dep: ReaderControl = Depends(get_reader_control),
        scan_lock: threading.Lock = Depends(get_scan_lock),
    ) -> ScanResponse | ScanErrorResponse:
        timeout = payload.timeout if payload.timeout is not None else 15

        if not _is_web_reader_enabled() or emv_service is None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ScanErrorResponse(
                error="reader_disabled",
                message="Card reader access is disabled for this server.",
            )
        try:
            timeout_value = float(timeout)
            if timeout_value <= 0:
                timeout_value = 15.0
        except (TypeError, ValueError):
            timeout_value = 15.0

        if reader_control_dep.get_owner() != "web":
            response.status_code = status.HTTP_423_LOCKED
            return ScanErrorResponse(
                error="reader_locked",
                message="Reader is currently reserved by another service.",
            )

        if not scan_lock.acquire(blocking=False):
            response.status_code = status.HTTP_409_CONFLICT
            return ScanErrorResponse(
                error="reader_busy",
                message="Reader is busy with another scan.",
            )

        try:
            if not emv_service.wait_for_card(timeout=int(timeout_value)):
                response.status_code = status.HTTP_200_OK
                return ScanErrorResponse(
                    error="timeout",
                    message="No card detected.",
                )

            try:
                scan = emv_service.read_card_data()
            finally:
                emv_service.disconnect()

            identifier = scan.primary_identifier()
            if not identifier:
                response.status_code = status.HTTP_200_OK
                return ScanErrorResponse(
                    error="no_identifier",
                    message="Could not read a stable identifier from the card.",
                    tag_type=scan.tag_type,
                    card_type=scan.card_type,
                    uid=scan.uid,
                    tokenized=scan.tokenized,
                )

            masked_identifier = (
                identifier if len(identifier) <= 4 else f"****{identifier[-4:]}"
            )
            metadata = _build_scan_metadata(scan)
            existing_user = auth_service.find_user_by_identifier(identifier)

            response_model = ScanResponse(
                identifier=identifier,
                identifier_type=scan.primary_identifier_type(),
                tag_type=scan.tag_type,
                card_type=scan.card_type,
                uid=scan.uid,
                pan=scan.pan,
                tokenized=scan.tokenized,
                masked_identifier=masked_identifier,
                timestamp=time.time(),
                metadata=metadata,
                issuer=metadata.issuer if metadata else None,
                expiry=metadata.expiry if metadata else None,
                expiry_formatted=metadata.expiry_formatted if metadata else None,
                already_registered=existing_user is not None,
                existing_user=_serialize_user(existing_user) if existing_user else None,
            )

            set_last_scan(
                ScanSummary(
                    identifier=identifier,
                    masked_identifier=masked_identifier,
                    identifier_type=response_model.identifier_type,
                    timestamp=response_model.timestamp,
                    already_registered=response_model.already_registered,
                    existing_user_name=existing_user.name if existing_user else None,
                    existing_user_id=existing_user.user_id if existing_user else None,
                    metadata=metadata,
                )
            )
            response.status_code = status.HTTP_200_OK
            return response_model
        except Exception as exc:  # pragma: no cover - defensive fallback
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return ScanErrorResponse(error="internal_error", message=str(exc))
        finally:
            if scan_lock.locked():
                scan_lock.release()

    @app.get("/api/reader", response_model=ReaderStateResponse)
    async def api_get_reader_state(
        reader_control_dep: ReaderControl = Depends(get_reader_control),
    ) -> ReaderStateResponse:
        return ReaderStateResponse(
            state=_serialize_reader_state(reader_control_dep),
            reader_enabled=_is_web_reader_enabled(),
        )

    @app.post("/api/reader/claim", response_model=ReaderClaimResponse)
    async def api_claim_reader(
        response: Response,
        reader_control_dep: ReaderControl = Depends(get_reader_control),
    ) -> ReaderClaimResponse:
        state = reader_control_dep.get_state()
        owner = state.get("owner")
        if owner == "web":
            response.status_code = status.HTTP_200_OK
            return ReaderClaimResponse(
                state=_serialize_reader_state(reader_control_dep),
                already_owned=True,
            )
        new_state = reader_control_dep.set_owner("web", {"previous_owner": owner})
        response.status_code = status.HTTP_200_OK
        return ReaderClaimResponse(
            state=_serialize_reader_state(reader_control_dep),
            reader_enabled=_is_web_reader_enabled(),
            updated=_serialize_reader_update(new_state),
        )

    @app.post("/api/reader/release", response_model=ReaderReleaseResponse)
    async def api_release_reader(
        response: Response,
        reader_control_dep: ReaderControl = Depends(get_reader_control),
    ) -> ReaderReleaseResponse:
        state = reader_control_dep.get_state()
        owner = state.get("owner")
        if owner == "door":
            response.status_code = status.HTTP_200_OK
            return ReaderReleaseResponse(
                state=_serialize_reader_state(reader_control_dep),
                already_released=True,
            )
        new_state = reader_control_dep.reset_to_default()
        response.status_code = status.HTTP_200_OK
        return ReaderReleaseResponse(
            state=_serialize_reader_state(reader_control_dep),
            reader_enabled=_is_web_reader_enabled(),
            updated=_serialize_reader_update(new_state),
        )

    @app.post(
        "/api/users",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_add_user(
        response: Response,
        payload: AddUserRequest = Body(...),
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        identifier = (payload.identifier or "").strip()
        identifier_type = (payload.identifier_type or "UID").strip() or "UID"
        access_level = (payload.access_level or "user").strip().lower()
        user_id = (payload.user_id or "").strip() or None
        make_primary = bool(payload.make_primary)
        name = (payload.name or "").strip()
        metadata = _metadata_to_dict(payload.metadata)

        if not identifier:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return UserErrorResponse(error="missing_identifier")

        if auth_service.identifier_exists(identifier):
            existing_user = auth_service.find_user_by_identifier(identifier)
            response.status_code = status.HTTP_409_CONFLICT
            return UserErrorResponse(
                error="user_exists",
                existing_user=_serialize_user(existing_user) if existing_user else None,
            )

        if user_id:
            user = auth_service.get_user(user_id)
            if not user:
                response.status_code = status.HTTP_404_NOT_FOUND
                return UserErrorResponse(error="not_found")
            if not auth_service.add_identifier_to_user(
                user_id,
                identifier,
                identifier_type,
                make_primary,
                metadata,
            ):
                response.status_code = status.HTTP_409_CONFLICT
                return UserErrorResponse(error="user_exists")
            refreshed = auth_service.get_user(user_id)
            if refreshed is None:
                response.status_code = status.HTTP_404_NOT_FOUND
                return UserErrorResponse(error="not_found")
            response.status_code = status.HTTP_200_OK
            return UserResponse(user=_serialize_user(refreshed))

        if not name:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return UserErrorResponse(error="missing_name")
        if access_level not in {"user", "admin"}:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return UserErrorResponse(error="invalid_access_level")

        new_user = auth_service.create_user(
            identifier_value=identifier,
            name=name,
            access_level=access_level,
            identifier_type=identifier_type,
            metadata=metadata,
        )
        response.status_code = status.HTTP_201_CREATED
        return UserResponse(user=_serialize_user(new_user))

    @app.post(
        "/api/users/{user_id}/toggle",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_toggle_user(
        user_id: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        user = auth_service.get_user(user_id)
        if not user:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        auth_service.set_user_active(user_id, not user.active)
        refreshed = auth_service.get_user(user_id)
        if refreshed is None:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return UserResponse(user=_serialize_user(refreshed))

    @app.post(
        "/api/users/{user_id}/pause",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_pause_user(
        user_id: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        user = auth_service.get_user(user_id)
        if not user:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        if user.active:
            auth_service.set_user_active(user_id, False)
        refreshed = auth_service.get_user(user_id)
        if refreshed is None:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return UserResponse(user=_serialize_user(refreshed))

    @app.post(
        "/api/users/{user_id}/resume",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_resume_user(
        user_id: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        user = auth_service.get_user(user_id)
        if not user:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        if not user.active:
            auth_service.set_user_active(user_id, True)
        refreshed = auth_service.get_user(user_id)
        if refreshed is None:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return UserResponse(user=_serialize_user(refreshed))

    @app.delete(
        "/api/users/{user_id}",
        response_model=Union[SuccessResponse, UserErrorResponse],
    )
    async def api_delete_user(
        user_id: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> SuccessResponse | UserErrorResponse:
        if not auth_service.delete_user(user_id):
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return SuccessResponse()

    @app.get(
        "/api/users/by-identifier/{identifier_value:path}",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_get_user_by_identifier(
        identifier_value: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        value = identifier_value.strip()
        if not value:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return UserErrorResponse(error="missing_identifier")
        user = auth_service.find_user_by_identifier(value)
        if not user:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return UserResponse(user=_serialize_user(user))

    @app.delete(
        "/api/users/{user_id}/identifiers/{identifier_value}",
        response_model=Union[RemoveIdentifierResponse, UserErrorResponse],
    )
    async def api_remove_identifier(
        user_id: str,
        identifier_value: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> RemoveIdentifierResponse | UserErrorResponse:
        if not auth_service.remove_identifier_from_user(user_id, identifier_value):
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        user = auth_service.get_user(user_id)
        response.status_code = status.HTTP_200_OK
        if not user:
            return RemoveIdentifierResponse(user_removed=True)
        return RemoveIdentifierResponse(user=_serialize_user(user))

    @app.post(
        "/api/users/{user_id}/identifiers/{identifier_value}/primary",
        response_model=Union[UserResponse, UserErrorResponse],
    )
    async def api_set_primary(
        user_id: str,
        identifier_value: str,
        response: Response,
        auth_service: AuthenticationService = Depends(get_auth_service),
    ) -> UserResponse | UserErrorResponse:
        if not auth_service.set_primary_identifier(user_id, identifier_value):
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        user = auth_service.get_user(user_id)
        if user is None:
            response.status_code = status.HTTP_404_NOT_FOUND
            return UserErrorResponse(error="not_found")
        response.status_code = status.HTTP_200_OK
        return UserResponse(user=_serialize_user(user))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
