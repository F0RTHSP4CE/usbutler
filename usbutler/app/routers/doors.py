"""Doors API router."""

import math
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.dependencies import CallerDep, ServicesDep
from app.models.door_event import DoorEventType
from app.schemas.door import (
    DoorCreate,
    DoorEventListResponse,
    DoorEventResponse,
    DoorOpenRequest,
    DoorOpenResponse,
    DoorResponse,
    DoorUpdate,
    LastDoorEventResponse,
)

router = APIRouter(prefix="/doors", tags=["doors"])


def _refresh_monitoring(s: ServicesDep):
    s.door_control.update_monitored_doors(s.doors.get_all())


@router.get("/last-event", response_model=LastDoorEventResponse)
def get_last_door_event(s: ServicesDep):
    event = s.door_control.get_last_door_event()
    return LastDoorEventResponse(**event) if event else LastDoorEventResponse()


@router.get("/history", response_model=DoorEventListResponse)
def get_door_history(
    s: ServicesDep,
    door_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    events, total = s.door_events.get_history(
        door_id=door_id, page=page, page_size=page_size
    )
    items = []
    for event in events:
        door = s.doors.get_by_id(event.door_id)
        items.append(
            DoorEventResponse(
                id=event.id,
                door_id=event.door_id,
                door_name=door.name if door else f"Door #{event.door_id}",
                user_id=event.user_id,
                event_type=event.event_type,
                username=event.username,
                timestamp=event.timestamp,
            )
        )
    return DoorEventListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


@router.get("", response_model=List[DoorResponse])
def list_doors(s: ServicesDep, skip: int = 0, limit: int = 100):
    return s.doors.get_all(skip=skip, limit=limit)


@router.post("", response_model=DoorResponse, status_code=status.HTTP_201_CREATED)
def create_door(door_data: DoorCreate, s: ServicesDep):
    if s.doors.get_by_name(door_data.name):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Door '{door_data.name}' exists")
    door = s.doors.create(door_data)
    _refresh_monitoring(s)
    return door


@router.get("/{door_id}", response_model=DoorResponse)
def get_door(door_id: int, s: ServicesDep):
    if door := s.doors.get_by_id(door_id):
        return door
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Door {door_id} not found")


@router.patch("/{door_id}", response_model=DoorResponse)
def update_door(door_id: int, door_data: DoorUpdate, s: ServicesDep):
    # Get the current door first
    current_door = s.doors.get_by_id(door_id)
    if not current_door:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Door {door_id} not found")

    # Only check for name conflicts if the name is changing
    if door_data.name and door_data.name != current_door.name:
        existing = s.doors.get_by_name(door_data.name)
        if existing:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Door '{door_data.name}' exists"
            )

    door = s.doors.update(door_id, door_data)
    _refresh_monitoring(s)
    return door


@router.delete("/{door_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door(door_id: int, s: ServicesDep):
    if not s.doors.delete(door_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Door {door_id} not found")
    _refresh_monitoring(s)


@router.post("/{door_id}/open", response_model=DoorOpenResponse)
def open_door(
    door_id: int, request: DoorOpenRequest, s: ServicesDep, caller: CallerDep
):
    door = s.doors.get_by_id(door_id)
    if not door:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Door {door_id} not found")

    # Identity comes from the authenticated token
    username = caller.username if caller else "admin"
    user_id = caller.id if caller else None

    # Proxy usage: store on_behalf_of separately
    on_behalf_of = None
    if request.on_behalf_of:
        on_behalf_of = request.on_behalf_of

    success = s.door_control.open_door_blocking(door, username, DoorEventType.API, user_id, on_behalf_of)

    return DoorOpenResponse(
        success=success,
        message=f"Door '{door.name}' opened" if success else f"Door '{door.name}' failed to open",
        door_id=door.id,
        door_name=door.name,
    )
