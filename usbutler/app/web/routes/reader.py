"""Reader control and card scanning routes."""

from __future__ import annotations

import time
import threading
from dataclasses import asdict
from typing import Union

from fastapi import APIRouter, Body, Depends, Response, status

from app.services.auth_service import AuthServiceError
from app.services.reader_control import ReaderControl
from app.web.common import (
    ScanCardRequest,
    ReaderResponse,
    ScanResponse,
    ErrorResponse,
    UserOut,
    ReaderStateOut,
    AuthService,
    EMVCardService,
    get_auth_service,
    get_emv_service,
    get_reader_control,
    get_scan_lock,
    _is_web_reader_enabled,
)

router = APIRouter(prefix="/reader", tags=["Reader"])


@router.get(
    "",
    response_model=ReaderResponse,
    summary="Get reader status",
)
async def get_reader_state(
    reader_control: ReaderControl = Depends(get_reader_control),
) -> ReaderResponse:
    """Get the current state of the NFC card reader."""
    owner = reader_control.get_owner() or "door"
    return ReaderResponse(
        data=ReaderStateOut(owner=owner, enabled=_is_web_reader_enabled())
    )


@router.post(
    "/claim",
    response_model=ReaderResponse,
    summary="Claim reader for web interface",
)
async def claim_reader(
    reader_control: ReaderControl = Depends(get_reader_control),
) -> ReaderResponse:
    """Claim exclusive access to the NFC reader for the web interface."""
    current_owner = reader_control.get_owner()
    already_owned = current_owner == "web"

    if not already_owned:
        reader_control.set_owner("web")

    return ReaderResponse(
        data=ReaderStateOut(
            owner="web",
            enabled=_is_web_reader_enabled(),
            claimed=True,
            already_owned=already_owned,
        )
    )


@router.post(
    "/release",
    response_model=ReaderResponse,
    summary="Release reader back to door service",
)
async def release_reader(
    reader_control: ReaderControl = Depends(get_reader_control),
) -> ReaderResponse:
    """Release the NFC reader back to the door service."""
    current_owner = reader_control.get_owner()
    already_released = current_owner == "door"

    if not already_released:
        reader_control.reset_to_default()

    return ReaderResponse(
        data=ReaderStateOut(
            owner="door",
            enabled=_is_web_reader_enabled(),
            claimed=False,
            already_released=already_released,
        )
    )


@router.post(
    "/scan",
    response_model=Union[ScanResponse, ErrorResponse],
    summary="Scan a card",
)
async def scan_card(
    response: Response,
    payload: ScanCardRequest = Body(default_factory=ScanCardRequest),
    auth_service: AuthService = Depends(get_auth_service),
    emv_service: EMVCardService | None = Depends(get_emv_service),
    reader_control: ReaderControl = Depends(get_reader_control),
    scan_lock: threading.Lock = Depends(get_scan_lock),
) -> ScanResponse | ErrorResponse:
    """
    Scan a card using the NFC reader.

    The reader must be claimed by the web interface before scanning.
    Returns card information including identifier, type, and whether it's already registered.
    """
    timeout = payload.timeout if payload.timeout is not None else 15.0

    # Check if reader is enabled
    if not _is_web_reader_enabled() or emv_service is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ErrorResponse(
            error="reader_disabled",
            message="Card reader access is disabled for this server.",
        )

    # Validate timeout
    try:
        timeout_value = float(timeout)
        if timeout_value <= 0:
            timeout_value = 15.0
    except (TypeError, ValueError):
        timeout_value = 15.0

    # Check reader ownership
    if reader_control.get_owner() != "web":
        response.status_code = status.HTTP_423_LOCKED
        return ErrorResponse(
            error="reader_locked",
            message="Reader must be claimed before scanning. Use POST /api/reader/claim first.",
        )

    # Try to acquire scan lock
    if not scan_lock.acquire(blocking=False):
        response.status_code = status.HTTP_409_CONFLICT
        return ErrorResponse(
            error="reader_busy",
            message="Another scan operation is in progress.",
        )

    try:
        # Wait for card
        if not emv_service.wait_for_card(timeout=int(timeout_value)):
            return ErrorResponse(
                error="timeout",
                message="No card detected within the timeout period.",
            )

        # Read card data
        try:
            scan = emv_service.read_card_data()
        finally:
            emv_service.disconnect()

        identifier = scan.identifier()
        if not identifier:
            return ErrorResponse(
                error="no_identifier",
                message="Could not read a stable identifier from the card.",
                tag_type=scan.tag_type,
                card_type=scan.card_type,
                uid=scan.uid,
                tokenized=scan.tokenized,
            )

        # Mask identifier for display
        masked_identifier = (
            identifier if len(identifier) <= 4 else f"****{identifier[-4:]}"
        )
        metadata = asdict(scan)

        # Check if already registered
        try:
            existing_user = auth_service.find_user_by_identifier_or_raise(identifier)
        except AuthServiceError:
            existing_user = None

        return ScanResponse(
            data={
                "identifier": identifier,
                "identifier_type": scan.identifier_type(),
                "tag_type": scan.tag_type,
                "card_type": scan.card_type,
                "uid": scan.uid,
                "pan": scan.pan,
                "tokenized": scan.tokenized,
                "masked_identifier": masked_identifier,
                "timestamp": time.time(),
                "metadata": metadata,
                "issuer": metadata.get("issuer") if metadata else None,
                "expiry": metadata.get("expiry") if metadata else None,
            },
            already_registered=existing_user is not None,
            existing_user=(
                UserOut.model_validate(existing_user, from_attributes=True)
                if existing_user
                else None
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return ErrorResponse(error="internal_error", message=str(exc))
    finally:
        if scan_lock.locked():
            scan_lock.release()
