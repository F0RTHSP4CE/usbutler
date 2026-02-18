"""Public API router."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ServicesDepUI
from app.schemas.user import IdentifierLookupRequest, UserResponse

router = APIRouter(prefix="/public", tags=["public"])


@router.post("/users/by-identifier", response_model=UserResponse)
def get_user_by_identifier(payload: IdentifierLookupRequest, s: ServicesDepUI):
    identifier = s.identifiers.get_by_value(payload.value)
    if not identifier or not identifier.user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No user found for submitted identifier",
        )
    return identifier.user
