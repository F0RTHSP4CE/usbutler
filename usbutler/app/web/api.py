"""API router for user management and reader control."""

from __future__ import annotations

import time
import threading
from typing import Union

from fastapi import APIRouter, Body, Depends, Response, status

from app.web.common import (
    AddUserRequest,
    AuthenticationService,
    EMVCardService,
    ReaderControl,
    ScanErrorResponse,
    ScanRequest,
    ScanResponse,
    ScanSummary,
    SuccessResponse,
    UserErrorResponse,
    UserListResponse,
    UserResponse,
    RemoveIdentifierResponse,
    ReaderStateResponse,
    ReaderClaimResponse,
    ReaderReleaseResponse,
    _build_stats,
    _is_web_reader_enabled,
    _metadata_to_dict,
    _serialize_reader_state,
    _serialize_reader_update,
    _serialize_user,
    get_auth_service,
    get_emv_service,
    get_last_scan,
    get_reader_control,
    get_scan_lock,
    set_last_scan,
)

router = APIRouter()


@router.get("/users", response_model=UserListResponse)
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


@router.post(
    "/scan-card",
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
        metadata = {
            "issuer": getattr(scan, "issuer", None),
            "expiry": getattr(scan, "expiry", None),
            "card_type": getattr(scan, "card_type", None),
            "tag_type": getattr(scan, "tag_type", None),
            "atr_hex": getattr(scan, "atr_hex", None),
            "atr_hex_compact": getattr(scan, "atr_hex_compact", None),
            "atr_summary": getattr(scan, "atr_summary", None),
        }
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
            issuer=metadata.get("issuer") if metadata else None,
            expiry=metadata.get("expiry") if metadata else None,
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


@router.get("/reader", response_model=ReaderStateResponse)
async def api_get_reader_state(
    reader_control_dep: ReaderControl = Depends(get_reader_control),
) -> ReaderStateResponse:
    return ReaderStateResponse(
        state=_serialize_reader_state(reader_control_dep),
        reader_enabled=_is_web_reader_enabled(),
    )


@router.post("/reader/claim", response_model=ReaderClaimResponse)
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


@router.post("/reader/release", response_model=ReaderReleaseResponse)
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


@router.post(
    "/users",
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


@router.post(
    "/users/{user_id}/toggle",
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


@router.post(
    "/users/{user_id}/pause",
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


@router.post(
    "/users/{user_id}/resume",
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


@router.delete(
    "/users/{user_id}",
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


@router.get(
    "/users/by-identifier/{identifier_value:path}",
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


@router.delete(
    "/users/{user_id}/identifiers/{identifier_value}",
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


@router.post(
    "/users/{user_id}/identifiers/{identifier_value}/primary",
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
