"""Users API router."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import UserServiceDep
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithIdentifiers,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=List[UserWithIdentifiers])
def list_users(
    user_service: UserServiceDep,
    skip: int = 0,
    limit: int = 100,
):
    """List all users."""
    return user_service.get_all(skip=skip, limit=limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate,
    user_service: UserServiceDep,
):
    """Create a new user."""
    # Check if username already exists
    existing = user_service.get_by_username(user_data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{user_data.username}' already exists",
        )

    return user_service.create(user_data)


@router.get("/{user_id}", response_model=UserWithIdentifiers)
def get_user(
    user_id: int,
    user_service: UserServiceDep,
):
    """Get a user by ID."""
    user = user_service.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )

    return user


@router.get("/by-username/{username}", response_model=UserWithIdentifiers)
def get_user_by_username(
    username: str,
    user_service: UserServiceDep,
):
    """Get a user by username."""
    user = user_service.get_by_username(username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with username '{username}' not found",
        )

    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    user_service: UserServiceDep,
):
    """Update a user."""
    # Check if username is being changed to an existing one
    if user_data.username:
        existing = user_service.get_by_username(user_data.username)
        if existing and existing.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with username '{user_data.username}' already exists",
            )

    user = user_service.update(user_id, user_data)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    user_service: UserServiceDep,
):
    """Delete a user."""
    if not user_service.delete(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )
