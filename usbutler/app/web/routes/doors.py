"""Door management routes."""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Body, Depends, Path, Response, status

from app.services.door_config_service import DoorConfigService, DoorConfigError, Door
from app.web.common import (
    CreateDoorRequest,
    UpdateDoorRequest,
    DoorResponse,
    DoorListResponse,
    ErrorResponse,
    SuccessResponse,
    DoorOut,
    get_door_config,
)

router = APIRouter(prefix="/doors", tags=["Doors"])


def _map_door_error_to_status(code: str) -> int:
    """Map door config error codes to HTTP status codes."""
    return {
        "not_found": status.HTTP_404_NOT_FOUND,
        "door_exists": status.HTTP_409_CONFLICT,
        "missing_name": status.HTTP_400_BAD_REQUEST,
    }.get(code, status.HTTP_400_BAD_REQUEST)


def _handle_door_error(response: Response, exc: DoorConfigError) -> ErrorResponse:
    """Convert a DoorConfigError to an ErrorResponse."""
    response.status_code = _map_door_error_to_status(exc.code)
    return ErrorResponse(error=exc.code, message=exc.message)


def _door_to_out(door: Door) -> DoorOut:
    """Convert Door model to DoorOut."""
    return DoorOut.model_validate(door, from_attributes=True)


@router.get(
    "",
    response_model=DoorListResponse,
    summary="List all doors",
)
async def list_doors(
    door_config: DoorConfigService = Depends(get_door_config),
) -> DoorListResponse:
    """Get a list of all configured doors."""
    doors = door_config.list_doors()
    return DoorListResponse(data=[_door_to_out(d) for d in doors])


@router.post(
    "",
    response_model=Union[DoorResponse, ErrorResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new door",
)
async def create_door(
    response: Response,
    payload: CreateDoorRequest = Body(...),
    door_config: DoorConfigService = Depends(get_door_config),
) -> DoorResponse | ErrorResponse:
    """Create a new door configuration."""
    if not payload.name:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return ErrorResponse(error="missing_name", message="Door name is required")

    try:
        door = door_config.create_door_or_raise(
            name=payload.name,
            gpio_pin=payload.gpio_pin,
            gpio_chip=payload.gpio_chip,
            active_high=payload.active_high,
            auto_lock_delay=payload.auto_lock_delay,
            description=payload.description,
            door_id=payload.door_id,
        )
        response.status_code = status.HTTP_201_CREATED
        return DoorResponse(data=_door_to_out(door))
    except DoorConfigError as exc:
        return _handle_door_error(response, exc)


@router.get(
    "/{door_id}",
    response_model=Union[DoorResponse, ErrorResponse],
    summary="Get door by ID",
)
async def get_door(
    response: Response,
    door_id: str = Path(..., description="Door ID"),
    door_config: DoorConfigService = Depends(get_door_config),
) -> DoorResponse | ErrorResponse:
    """Get a specific door configuration by ID."""
    try:
        door = door_config.get_door_or_raise(door_id)
        return DoorResponse(data=_door_to_out(door))
    except DoorConfigError as exc:
        return _handle_door_error(response, exc)


@router.patch(
    "/{door_id}",
    response_model=Union[DoorResponse, ErrorResponse],
    summary="Update door",
)
async def update_door(
    response: Response,
    door_id: str = Path(..., description="Door ID"),
    payload: UpdateDoorRequest = Body(...),
    door_config: DoorConfigService = Depends(get_door_config),
) -> DoorResponse | ErrorResponse:
    """Update door configuration (name, GPIO settings, etc.)."""
    try:
        door = door_config.update_door_or_raise(
            door_id=door_id,
            name=payload.name,
            gpio_pin=payload.gpio_pin,
            gpio_chip=payload.gpio_chip,
            active_high=payload.active_high,
            auto_lock_delay=payload.auto_lock_delay,
            enabled=payload.enabled,
            description=payload.description,
        )
        return DoorResponse(data=_door_to_out(door))
    except DoorConfigError as exc:
        return _handle_door_error(response, exc)


@router.delete(
    "/{door_id}",
    response_model=Union[SuccessResponse, ErrorResponse],
    summary="Delete door",
)
async def delete_door(
    response: Response,
    door_id: str = Path(..., description="Door ID"),
    door_config: DoorConfigService = Depends(get_door_config),
) -> SuccessResponse | ErrorResponse:
    """Delete a door configuration."""
    try:
        door_config.delete_door_or_raise(door_id)
        return SuccessResponse(message="Door deleted successfully")
    except DoorConfigError as exc:
        return _handle_door_error(response, exc)


@router.post(
    "/{door_id}/unlock",
    response_model=Union[SuccessResponse, ErrorResponse],
    summary="Unlock door",
)
async def unlock_door(
    response: Response,
    door_id: str = Path(..., description="Door ID"),
    door_config: DoorConfigService = Depends(get_door_config),
) -> SuccessResponse | ErrorResponse:
    """Unlock a specific door (triggers GPIO)."""
    try:
        door = door_config.get_door_or_raise(door_id)
        if not door.enabled:
            response.status_code = status.HTTP_403_FORBIDDEN
            return ErrorResponse(
                error="door_disabled", message=f"Door '{door_id}' is disabled"
            )

        # TODO: Integrate with DoorControlService to actually trigger GPIO
        # For now, return a placeholder response
        return SuccessResponse(
            message=f"Door '{door.name}' ({door_id}) unlock triggered on GPIO {door.gpio.gpio_pin}"
        )
    except DoorConfigError as exc:
        return _handle_door_error(response, exc)
