"""Doors API router."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import (
    DoorControlServiceDep,
    DoorServiceDep,
    UserServiceDep,
)
from app.schemas.door import (
    DoorCreate,
    DoorOpenRequest,
    DoorOpenResponse,
    DoorResponse,
    DoorUpdate,
)

router = APIRouter(prefix="/doors", tags=["doors"])


@router.get("", response_model=List[DoorResponse])
def list_doors(
    door_service: DoorServiceDep,
    skip: int = 0,
    limit: int = 100,
):
    """List all doors."""
    return door_service.get_all(skip=skip, limit=limit)


@router.post("", response_model=DoorResponse, status_code=status.HTTP_201_CREATED)
def create_door(
    door_data: DoorCreate,
    door_service: DoorServiceDep,
):
    """Create a new door."""
    # Check if name already exists
    existing = door_service.get_by_name(door_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Door with name '{door_data.name}' already exists",
        )

    return door_service.create(door_data)


@router.get("/{door_id}", response_model=DoorResponse)
def get_door(
    door_id: int,
    door_service: DoorServiceDep,
):
    """Get a door by ID."""
    door = door_service.get_by_id(door_id)

    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )

    return door


@router.patch("/{door_id}", response_model=DoorResponse)
def update_door(
    door_id: int,
    door_data: DoorUpdate,
    door_service: DoorServiceDep,
):
    """Update a door."""
    # Check if name is being changed to an existing one
    if door_data.name:
        existing = door_service.get_by_name(door_data.name)
        if existing and existing.id != door_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Door with name '{door_data.name}' already exists",
            )

    door = door_service.update(door_id, door_data)

    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )

    return door


@router.delete("/{door_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door(
    door_id: int,
    door_service: DoorServiceDep,
):
    """Delete a door."""
    if not door_service.delete(door_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )


@router.post("/{door_id}/open", response_model=DoorOpenResponse)
def open_door(
    door_id: int,
    request: DoorOpenRequest,
    door_service: DoorServiceDep,
    user_service: UserServiceDep,
    door_control: DoorControlServiceDep,
):
    """
    Open a door.

    The door opening is performed asynchronously in the background.
    Optionally provide user_id or username for notification purposes.
    """
    # Get the door
    door = door_service.get_by_id(door_id)
    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )

    # Get username for notifications
    username = None
    if request.user_id:
        user = user_service.get_by_id(request.user_id)
        if user:
            username = user.username
    elif request.username:
        username = request.username

    # Open door in background (non-blocking)
    door_control.open_door(door, username)

    return DoorOpenResponse(
        success=True,
        message=f"Door '{door.name}' opening initiated",
        door_id=door.id,
        door_name=door.name,
    )
