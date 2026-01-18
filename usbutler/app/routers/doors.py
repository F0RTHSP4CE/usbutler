"""Doors API router."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.door import (
    DoorCreate,
    DoorOpenRequest,
    DoorOpenResponse,
    DoorResponse,
    DoorUpdate,
)
from app.services.door_service import DoorService
from app.services.door_control_service import DoorControlService
from app.services.user_service import UserService

router = APIRouter(prefix="/doors", tags=["doors"])


@router.get("", response_model=List[DoorResponse])
def list_doors(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all doors."""
    service = DoorService(db)
    return service.get_all(skip=skip, limit=limit)


@router.post("", response_model=DoorResponse, status_code=status.HTTP_201_CREATED)
def create_door(
    door_data: DoorCreate,
    db: Session = Depends(get_db),
):
    """Create a new door."""
    service = DoorService(db)

    # Check if name already exists
    existing = service.get_by_name(door_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Door with name '{door_data.name}' already exists",
        )

    return service.create(door_data)


@router.get("/{door_id}", response_model=DoorResponse)
def get_door(
    door_id: int,
    db: Session = Depends(get_db),
):
    """Get a door by ID."""
    service = DoorService(db)
    door = service.get_by_id(door_id)

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
    db: Session = Depends(get_db),
):
    """Update a door."""
    service = DoorService(db)

    # Check if name is being changed to an existing one
    if door_data.name:
        existing = service.get_by_name(door_data.name)
        if existing and existing.id != door_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Door with name '{door_data.name}' already exists",
            )

    door = service.update(door_id, door_data)

    if not door:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )

    return door


@router.delete("/{door_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door(
    door_id: int,
    db: Session = Depends(get_db),
):
    """Delete a door."""
    service = DoorService(db)

    if not service.delete(door_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Door with id {door_id} not found",
        )


@router.post("/{door_id}/open", response_model=DoorOpenResponse)
def open_door(
    door_id: int,
    request: DoorOpenRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Open a door.

    The door opening is performed asynchronously in the background.
    Optionally provide user_id or username for notification purposes.
    """
    door_service = DoorService(db)
    user_service = UserService(db)
    door_control = DoorControlService()

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
