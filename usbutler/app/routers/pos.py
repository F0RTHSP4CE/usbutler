"""POS API router."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ServicesDepPOS
from app.schemas.user import IdentifierLookupRequest, UserResponse

router = APIRouter(prefix="/pos", tags=["pos"])


@router.post("/users/by-identifier", response_model=UserResponse)
def get_user_by_identifier(payload: IdentifierLookupRequest, s: ServicesDepPOS):
    """Look up a user by identifier value. Requires X-POS-Secret header."""
    identifier = s.identifiers.get_by_value(payload.value)
    if not identifier or not identifier.user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No user found for submitted identifier",
        )
    return identifier.user
