"""Doors API router."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ServicesDep
from app.schemas.door import (
    DoorCreate,
    DoorOpenRequest,
    DoorOpenResponse,
    DoorResponse,
    DoorUpdate,
    LastDoorEventResponse,
)

router = APIRouter(prefix="/doors", tags=["doors"])


def _refresh_button_monitoring(s: ServicesDep) -> None:
    """Refresh button monitoring with current doors list."""
    doors = s.doors.get_all()
    s.door_control.update_monitored_doors(doors)


@router.get("/last-event", response_model=LastDoorEventResponse)
def get_last_door_event(s: ServicesDep):
    """Get the last door event (open via API, button, or card)."""
    event = s.door_control.get_last_door_event()
    if not event:
        return LastDoorEventResponse()
    return LastDoorEventResponse(**event)


@router.get("", response_model=List[DoorResponse])
def list_doors(s: ServicesDep, skip: int = 0, limit: int = 100):
    """List all doors."""
    return s.doors.get_all(skip=skip, limit=limit)


@router.post("", response_model=DoorResponse, status_code=status.HTTP_201_CREATED)
def create_door(door_data: DoorCreate, s: ServicesDep):
    """Create a new door."""
    if s.doors.get_by_name(door_data.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Door with name '{door_data.name}' already exists",
        )
    door = s.doors.create(door_data)
    _refresh_button_monitoring(s)
    return door


@router.get("/{door_id}", response_model=DoorResponse)
def get_door(door_id: int, s: ServicesDep):
    """Get a door by ID."""
    if door := s.doors.get_by_id(door_id):
        return door
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Door with id {door_id} not found",
    )


@router.patch("/{door_id}", response_model=DoorResponse)
def update_door(door_id: int, door_data: DoorUpdate, s: ServicesDep):
    """Update a door."""
    if door_data.name:
        existing = s.doors.get_by_name(door_data.name)
        if existing and existing.id != door_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Door with name '{door_data.name}' already exists",
            )
    if door := s.doors.update(door_id, door_data):
        _refresh_button_monitoring(s)
        return door
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Door with id {door_id} not found",
    )


@router.delete("/{door_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door(door_id: int, s: ServicesDep):
    """Delete a door."""
    if not s.doors.delete(door_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )
    _refresh_button_monitoring(s)


@router.post("/{door_id}/open", response_model=DoorOpenResponse)
def open_door(door_id: int, request: DoorOpenRequest, s: ServicesDep):
    """
    Open a door.

    The door opening is performed asynchronously in the background.
    Optionally provide user_id or username for notification purposes.
    """
    door = s.doors.get_by_id(door_id)
    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )

    username = None
    if request.user_id:
        if user := s.users.get_by_id(request.user_id):
            username = user.username
    elif request.username:
        username = request.username

    s.door_control.open_door(door, username)

    return DoorOpenResponse(
        success=True,
        message=f"Door '{door.name}' opening initiated",
        door_id=door.id,
        door_name=door.name,
    )
