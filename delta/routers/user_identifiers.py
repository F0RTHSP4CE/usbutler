from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from schemas import UserResponse, IdentifierResponse, IdentifierListResponse
from services import (
    UserService,
    get_user_service,
    IdentifierService,
    get_identifier_service,
)

router = APIRouter(prefix="/users/{user_id}/identifiers", tags=["User Identifiers"])


class AssignIdentifierRequest(BaseModel):
    """Request to assign an identifier to a user."""

    identifier_id: str


@router.get("", response_model=IdentifierListResponse)
def get_user_identifiers(
    user_id: str,
    user_service: UserService = Depends(get_user_service),
    identifier_service: IdentifierService = Depends(get_identifier_service),
) -> IdentifierListResponse:
    """Get all identifiers assigned to a user."""
    # Verify user exists
    user_service.get_by_id(user_id)

    # Get identifiers owned by this user
    identifiers = identifier_service.get_by_owner(user_id)
    return IdentifierListResponse(data=identifiers, total=len(identifiers))


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def assign_identifier_to_user(
    user_id: str,
    request: AssignIdentifierRequest,
    user_service: UserService = Depends(get_user_service),
    identifier_service: IdentifierService = Depends(get_identifier_service),
) -> UserResponse:
    """Assign an identifier to a user."""
    # Verify both user and identifier exist
    user_service.get_by_id(user_id)
    identifier_service.get_by_id(request.identifier_id)

    # Update identifier's owner
    identifier_service.assign_owner(request.identifier_id, user_id)

    # Add identifier to user's list
    user = user_service.add_identifier(user_id, request.identifier_id)
    return UserResponse(data=user)


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_identifier_from_user(
    user_id: str,
    identifier_id: str,
    user_service: UserService = Depends(get_user_service),
    identifier_service: IdentifierService = Depends(get_identifier_service),
) -> None:
    """Remove an identifier from a user."""
    # Verify both user and identifier exist
    user_service.get_by_id(user_id)
    identifier_service.get_by_id(identifier_id)

    # Remove owner from identifier
    identifier_service.assign_owner(identifier_id, None)

    # Remove identifier from user's list
    user_service.remove_identifier(user_id, identifier_id)
