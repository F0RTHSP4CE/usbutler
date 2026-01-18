"""Identifiers API router."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ServicesDep
from app.schemas.identifier import (
    IdentifierCreate,
    IdentifierResponse,
    IdentifierUpdate,
    IdentifierWithUser,
    LastScanResponse,
)

router = APIRouter(prefix="/identifiers", tags=["identifiers"])


@router.get("", response_model=List[IdentifierWithUser])
def list_identifiers(s: ServicesDep, skip: int = 0, limit: int = 100):
    """List all identifiers."""
    return s.identifiers.get_all(skip=skip, limit=limit)


@router.post("", response_model=IdentifierResponse, status_code=status.HTTP_201_CREATED)
def create_identifier(identifier_data: IdentifierCreate, s: ServicesDep):
    """Create a new identifier."""
    if s.identifiers.get_by_value(identifier_data.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Identifier with value '{identifier_data.value}' already exists",
        )
    if identifier_data.user_id and not s.users.get_by_id(identifier_data.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {identifier_data.user_id} not found",
        )
    return s.identifiers.create(identifier_data)


@router.get("/last-scan", response_model=LastScanResponse)
def get_last_scan(s: ServicesDep):
    """Get the last scanned card/identifier."""
    if not s.card_reader_polling:
        return LastScanResponse()

    last_scan = s.card_reader_polling.get_last_scan()
    if not last_scan:
        return LastScanResponse()

    identifier = s.identifiers.get_by_value(last_scan["value"])
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
def get_identifier(identifier_id: int, s: ServicesDep):
    """Get an identifier by ID."""
    if identifier := s.identifiers.get_by_id(identifier_id):
        return identifier
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Identifier with id {identifier_id} not found",
    )


@router.get("/by-value/{value}", response_model=IdentifierWithUser)
def get_identifier_by_value(value: str, s: ServicesDep):
    """Get an identifier by value."""
    if identifier := s.identifiers.get_by_value(value):
        return identifier
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Identifier with value '{value}' not found",
    )


@router.patch("/{identifier_id}", response_model=IdentifierResponse)
def update_identifier(
    identifier_id: int, identifier_data: IdentifierUpdate, s: ServicesDep
):
    """Update an identifier."""
    if identifier_data.value:
        existing = s.identifiers.get_by_value(identifier_data.value)
        if existing and existing.id != identifier_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Identifier with value '{identifier_data.value}' already exists",
            )
    if identifier_data.user_id is not None and identifier_data.user_id != 0:
        if not s.users.get_by_id(identifier_data.user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {identifier_data.user_id} not found",
            )
    if identifier := s.identifiers.update(identifier_id, identifier_data):
        return identifier
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Identifier with id {identifier_id} not found",
    )


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identifier(identifier_id: int, s: ServicesDep):
    """Delete an identifier."""
    if not s.identifiers.delete(identifier_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identifier with id {identifier_id} not found",
        )


@router.post("/{identifier_id}/assign/{user_id}", response_model=IdentifierWithUser)
def assign_identifier_to_user(identifier_id: int, user_id: int, s: ServicesDep):
    """Assign an identifier to a user."""
    if not s.users.get_by_id(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found",
        )
    if identifier := s.identifiers.assign_to_user(identifier_id, user_id):
        return identifier
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Identifier with id {identifier_id} not found",
    )


@router.post("/{identifier_id}/unassign", response_model=IdentifierWithUser)
def unassign_identifier(identifier_id: int, s: ServicesDep):
    """Unassign an identifier from its user."""
    if identifier := s.identifiers.assign_to_user(identifier_id, None):
        return identifier
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Identifier with id {identifier_id} not found",
    )
