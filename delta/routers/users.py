from fastapi import APIRouter, Depends, status

from schemas import (
    User,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
)
from services import UserService, get_user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=UserListResponse)
def get_users(service: UserService = Depends(get_user_service)) -> UserListResponse:
    """Get all users."""
    users = service.get_all()
    return UserListResponse(data=users, total=len(users))


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str, service: UserService = Depends(get_user_service)
) -> UserResponse:
    """Get a user by ID."""
    user = service.get_by_id(user_id)
    return UserResponse(data=user)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate, service: UserService = Depends(get_user_service)
) -> UserResponse:
    """Create a new user."""
    user = service.create(user_data)
    return UserResponse(data=user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    user_data: UserUpdate,
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    """Update an existing user."""
    user = service.update(user_id, user_data)
    return UserResponse(data=user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, service: UserService = Depends(get_user_service)) -> None:
    """Delete a user."""
    service.delete(user_id)
