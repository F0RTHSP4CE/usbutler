"""Identifiers API router."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import (
    CardReaderPollingDep,
    IdentifierServiceDep,
    UserServiceDep,
)
from app.schemas.identifier import (
    IdentifierCreate,
    IdentifierResponse,
    IdentifierUpdate,
    IdentifierWithUser,
    LastScanResponse,
)

router = APIRouter(prefix="/identifiers", tags=["identifiers"])


@router.get("", response_model=List[IdentifierWithUser])
def list_identifiers(
    identifier_service: IdentifierServiceDep,
    skip: int = 0,
    limit: int = 100,
):
    """List all identifiers."""
    return identifier_service.get_all(skip=skip, limit=limit)


@router.post("", response_model=IdentifierResponse, status_code=status.HTTP_201_CREATED)
def create_identifier(
    identifier_data: IdentifierCreate,
    identifier_service: IdentifierServiceDep,
    user_service: UserServiceDep,
):
    """Create a new identifier."""
    # Check if value already exists
    existing = identifier_service.get_by_value(identifier_data.value)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Identifier with value '{identifier_data.value}' already exists",
        )

    # Validate user_id if provided
    if identifier_data.user_id:
        user = user_service.get_by_id(identifier_data.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {identifier_data.user_id} not found",
            )

    return identifier_service.create(identifier_data)


@router.get("/last-scan", response_model=LastScanResponse)
def get_last_scan(
    identifier_service: IdentifierServiceDep,
    card_reader_polling: CardReaderPollingDep,
):
    """
    Get the last scanned card/identifier.

    This is useful for quickly assigning a recently scanned card to a user.
    """
    if card_reader_polling is None:
        return LastScanResponse()

    last_scan = card_reader_polling.get_last_scan()
    if not last_scan:
        return LastScanResponse()

    # Check if identifier exists and has a user
    identifier = identifier_service.get_by_value(last_scan["value"])

    user_id = None
    username = None
    if identifier and identifier.user:
        user_id = identifier.user.id
        username = identifier.user.username

    return LastScanResponse(
        value=last_scan["value"],
        type=last_scan["type"],
        scanned_at=last_scan["scanned_at"],
        user_id=user_id,
        username=username,
    )


@router.get("/{identifier_id}", response_model=IdentifierWithUser)
def get_identifier(
    identifier_id: int,
    identifier_service: IdentifierServiceDep,
):
    """Get an identifier by ID."""
    identifier = identifier_service.get_by_id(identifier_id)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.get("/by-value/{value}", response_model=IdentifierWithUser)
def get_identifier_by_value(
    value: str,
    identifier_service: IdentifierServiceDep,
):
    """Get an identifier by value."""
    identifier = identifier_service.get_by_value(value)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with value '{value}' not found",
        )

    return identifier


@router.patch("/{identifier_id}", response_model=IdentifierResponse)
def update_identifier(
    identifier_id: int,
    identifier_data: IdentifierUpdate,
    identifier_service: IdentifierServiceDep,
    user_service: UserServiceDep,
):
    """Update an identifier."""
    # Check if value is being changed to an existing one
    if identifier_data.value:
        existing = identifier_service.get_by_value(identifier_data.value)
        if existing and existing.id != identifier_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Identifier with value '{identifier_data.value}' already exists",
            )

    # Validate user_id if provided
    if identifier_data.user_id is not None and identifier_data.user_id != 0:
        user = user_service.get_by_id(identifier_data.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {identifier_data.user_id} not found",
            )

    identifier = identifier_service.update(identifier_id, identifier_data)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identifier(
    identifier_id: int,
    identifier_service: IdentifierServiceDep,
):
    """Delete an identifier."""
    if not identifier_service.delete(identifier_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )


@router.post("/{identifier_id}/assign/{user_id}", response_model=IdentifierWithUser)
def assign_identifier_to_user(
    identifier_id: int,
    user_id: int,
    identifier_service: IdentifierServiceDep,
    user_service: UserServiceDep,
):
    """Assign an identifier to a user."""
    # Validate user exists
    user = user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )

    identifier = identifier_service.assign_to_user(identifier_id, user_id)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.post("/{identifier_id}/unassign", response_model=IdentifierWithUser)
def unassign_identifier(
    identifier_id: int,
    identifier_service: IdentifierServiceDep,
):
    """Unassign an identifier from its user."""
    identifier = identifier_service.assign_to_user(identifier_id, None)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier
