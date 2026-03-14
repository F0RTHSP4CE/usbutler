"""Users API router."""

from typing import List
from fastapi import APIRouter, HTTPException, status
from app.dependencies import ServicesDep
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithIdentifiers,
    TokenResponse,
)
from app.services.api_token_service import generate_token, hash_token

router = APIRouter(prefix="/users", tags=["users"])


def _sources_to_csv(sources: list[str] | None) -> str | None:
    """Convert list of CIDRs to comma-separated string for DB storage."""
    if sources is None:
        return None
    return ",".join(s.strip() for s in sources if s.strip()) or None


@router.get("", response_model=List[UserWithIdentifiers])
def list_users(s: ServicesDep, skip: int = 0, limit: int = 100):
    users = s.users.get_all(skip=skip, limit=limit)
    return [_user_response(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, s: ServicesDep):
    if s.users.get_by_username(user_data.username):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Username '{user_data.username}' exists"
        )
    user = s.users.create(user_data, _sources_to_csv(user_data.allowed_sources))
    return _user_response(user)


@router.get("/{user_id}", response_model=UserWithIdentifiers)
def get_user(user_id: int, s: ServicesDep):
    if user := s.users.get_by_id(user_id):
        return _user_response(user)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")


@router.get("/by-username/{username}", response_model=UserWithIdentifiers)
def get_user_by_username(username: str, s: ServicesDep):
    if user := s.users.get_by_username(username):
        return _user_response(user)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User '{username}' not found")


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, user_data: UserUpdate, s: ServicesDep):
    if user_data.username:
        existing = s.users.get_by_username(user_data.username)
        if existing and existing.id != user_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Username '{user_data.username}' exists"
            )
    if user := s.users.update(
        user_id, user_data, _sources_to_csv(user_data.allowed_sources)
    ):
        return _user_response(user)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, s: ServicesDep):
    if not s.users.delete(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")


@router.post("/{user_id}/regenerate-token", response_model=TokenResponse)
def regenerate_token(user_id: int, s: ServicesDep):
    """Generate a new API token for the user. The token is shown only once."""
    user = s.users.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
    raw_token = generate_token()
    s.users.set_token_hash(user_id, hash_token(raw_token))
    return TokenResponse(token=raw_token)


@router.post("/{user_id}/revoke-token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(user_id: int, s: ServicesDep):
    """Revoke (delete) a user's API token."""
    user = s.users.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
    s.users.set_token_hash(user_id, None)


def _user_response(user) -> dict:
    """Build user response dict with allowed_sources parsed from CSV."""
    sources = []
    if user.api_allowed_sources:
        sources = [s.strip() for s in user.api_allowed_sources.split(",") if s.strip()]
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status,
        "allowed_sources": sources,
        "identifiers": list(user.identifiers) if hasattr(user, "identifiers") else [],
    }
