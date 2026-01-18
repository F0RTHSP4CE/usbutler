"""Identifiers API router."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.identifier import (
    IdentifierCreate,
    IdentifierResponse,
    IdentifierUpdate,
    IdentifierWithUser,
    LastScanResponse,
)
from app.services.identifier_service import IdentifierService
from app.services.user_service import UserService

router = APIRouter(prefix="/identifiers", tags=["identifiers"])

# Reference to the card reader polling service (will be set by main.py)
_card_reader_polling = None


def set_card_reader_polling(polling_service):
    """Set the card reader polling service reference."""
    global _card_reader_polling
    _card_reader_polling = polling_service


@router.get("", response_model=List[IdentifierWithUser])
def list_identifiers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all identifiers."""
    service = IdentifierService(db)
    return service.get_all(skip=skip, limit=limit)


@router.post("", response_model=IdentifierResponse, status_code=status.HTTP_201_CREATED)
def create_identifier(
    identifier_data: IdentifierCreate,
    db: Session = Depends(get_db),
):
    """Create a new identifier."""
    service = IdentifierService(db)
    user_service = UserService(db)

    # Check if value already exists
    existing = service.get_by_value(identifier_data.value)
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

    return service.create(identifier_data)


@router.get("/last-scan", response_model=LastScanResponse)
def get_last_scan(db: Session = Depends(get_db)):
    """
    Get the last scanned card/identifier.

    This is useful for quickly assigning a recently scanned card to a user.
    """
    if _card_reader_polling is None:
        return LastScanResponse()

    last_scan = _card_reader_polling.get_last_scan()
    if not last_scan:
        return LastScanResponse()

    # Check if identifier exists and has a user
    service = IdentifierService(db)
    identifier = service.get_by_value(last_scan["value"])

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
    db: Session = Depends(get_db),
):
    """Get an identifier by ID."""
    service = IdentifierService(db)
    identifier = service.get_by_id(identifier_id)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.get("/by-value/{value}", response_model=IdentifierWithUser)
def get_identifier_by_value(
    value: str,
    db: Session = Depends(get_db),
):
    """Get an identifier by value."""
    service = IdentifierService(db)
    identifier = service.get_by_value(value)

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
    db: Session = Depends(get_db),
):
    """Update an identifier."""
    service = IdentifierService(db)
    user_service = UserService(db)

    # Check if value is being changed to an existing one
    if identifier_data.value:
        existing = service.get_by_value(identifier_data.value)
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

    identifier = service.update(identifier_id, identifier_data)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identifier(
    identifier_id: int,
    db: Session = Depends(get_db),
):
    """Delete an identifier."""
    service = IdentifierService(db)

    if not service.delete(identifier_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )


@router.post("/{identifier_id}/assign/{user_id}", response_model=IdentifierWithUser)
def assign_identifier_to_user(
    identifier_id: int,
    user_id: int,
    db: Session = Depends(get_db),
):
    """Assign an identifier to a user."""
    service = IdentifierService(db)
    user_service = UserService(db)

    # Validate user exists
    user = user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )

    identifier = service.assign_to_user(identifier_id, user_id)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier


@router.post("/{identifier_id}/unassign", response_model=IdentifierWithUser)
def unassign_identifier(
    identifier_id: int,
    db: Session = Depends(get_db),
):
    """Unassign an identifier from its user."""
    service = IdentifierService(db)

    identifier = service.assign_to_user(identifier_id, None)

    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )

    return identifier
