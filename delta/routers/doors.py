from fastapi import APIRouter, Depends, status

from schemas import (
    Door,
    DoorCreate,
    DoorUpdate,
    DoorResponse,
    DoorListResponse,
)
from services import DoorService, get_door_service

router = APIRouter(prefix="/doors", tags=["Doors"])


@router.get("", response_model=DoorListResponse)
def get_doors(service: DoorService = Depends(get_door_service)) -> DoorListResponse:
    """Get all doors."""
    doors = service.get_all()
    return DoorListResponse(data=doors, total=len(doors))


@router.get("/{door_id}", response_model=DoorResponse)
def get_door(
    door_id: str, service: DoorService = Depends(get_door_service)
) -> DoorResponse:
    """Get a door by ID."""
    door = service.get_by_id(door_id)
    return DoorResponse(data=door)


@router.post("", response_model=DoorResponse, status_code=status.HTTP_201_CREATED)
def create_door(
    door_data: DoorCreate, service: DoorService = Depends(get_door_service)
) -> DoorResponse:
    """Create a new door."""
    door = service.create(door_data)
    return DoorResponse(data=door)


@router.put("/{door_id}", response_model=DoorResponse)
def update_door(
    door_id: str,
    door_data: DoorUpdate,
    service: DoorService = Depends(get_door_service),
) -> DoorResponse:
    """Update an existing door."""
    door = service.update(door_id, door_data)
    return DoorResponse(data=door)


@router.delete("/{door_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_door(door_id: str, service: DoorService = Depends(get_door_service)) -> None:
    """Delete a door."""
    service.delete(door_id)
