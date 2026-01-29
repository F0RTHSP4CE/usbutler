"""Users API router."""

from typing import List
from fastapi import APIRouter, HTTPException, status
from app.dependencies import ServicesDep
from app.schemas.user import UserCreate, UserResponse, UserUpdate, UserWithIdentifiers

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=List[UserWithIdentifiers])
def list_users(s: ServicesDep, skip: int = 0, limit: int = 100):
    return s.users.get_all(skip=skip, limit=limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, s: ServicesDep):
    if s.users.get_by_username(user_data.username):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Username '{user_data.username}' exists"
        )
    return s.users.create(user_data)


@router.get("/{user_id}", response_model=UserWithIdentifiers)
def get_user(user_id: int, s: ServicesDep):
    if user := s.users.get_by_id(user_id):
        return user
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")


@router.get("/by-username/{username}", response_model=UserWithIdentifiers)
def get_user_by_username(username: str, s: ServicesDep):
    if user := s.users.get_by_username(username):
        return user
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User '{username}' not found")


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, user_data: UserUpdate, s: ServicesDep):
    if user_data.username:
        existing = s.users.get_by_username(user_data.username)
        if existing and existing.id != user_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Username '{user_data.username}' exists"
            )
    if user := s.users.update(user_id, user_data):
        return user
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, s: ServicesDep):
    if not s.users.delete(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
