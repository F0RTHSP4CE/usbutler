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
from app.utils.masking import mask_identifier

router = APIRouter(prefix="/identifiers", tags=["identifiers"])


@router.get("", response_model=List[IdentifierWithUser])
def list_identifiers(s: ServicesDep, skip: int = 0, limit: int = 100):
    return s.identifiers.get_all(skip=skip, limit=limit)


@router.post("", response_model=IdentifierResponse, status_code=status.HTTP_201_CREATED)
def create_identifier(identifier_data: IdentifierCreate, s: ServicesDep):
    if s.identifiers.get_by_value(identifier_data.value):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Identifier '{mask_identifier(identifier_data.value)}' exists",
        )
    if not s.users.get_by_id(identifier_data.user_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"User {identifier_data.user_id} not found"
        )
    return s.identifiers.create(identifier_data)


@router.get("/last-scan", response_model=LastScanResponse)
def get_last_scan(s: ServicesDep):
    if not s.card_reader_polling:
        return LastScanResponse()
    last_scan = s.card_reader_polling.get_last_scan()
    if not last_scan:
        return LastScanResponse()
    identifier = s.identifiers.get_by_value(last_scan["value"])
    user_id, username = None, None
    if identifier and identifier.user:
        user_id, username = identifier.user.id, identifier.user.username
    return LastScanResponse(
        value=last_scan["value"],
        type=last_scan["type"],
        scanned_at=last_scan["scanned_at"],
        user_id=user_id,
        username=username,
    )


@router.get("/{identifier_id}", response_model=IdentifierWithUser)
def get_identifier(identifier_id: int, s: ServicesDep):
    if identifier := s.identifiers.get_by_id(identifier_id):
        return identifier
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"Identifier {identifier_id} not found"
    )


@router.get("/by-value/{value}", response_model=IdentifierWithUser)
def get_identifier_by_value(value: str, s: ServicesDep):
    if identifier := s.identifiers.get_by_value(value):
        return identifier
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"Identifier '{mask_identifier(value)}' not found"
    )


@router.patch("/{identifier_id}", response_model=IdentifierResponse)
def update_identifier(
    identifier_id: int, identifier_data: IdentifierUpdate, s: ServicesDep
):
    if identifier_data.value:
        existing = s.identifiers.get_by_value(identifier_data.value)
        if existing and existing.id != identifier_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Identifier '{mask_identifier(identifier_data.value)}' exists",
            )
    if identifier_data.user_id is not None and identifier_data.user_id != 0:
        if not s.users.get_by_id(identifier_data.user_id):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"User {identifier_data.user_id} not found"
            )
    if identifier := s.identifiers.update(identifier_id, identifier_data):
        return identifier
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"Identifier {identifier_id} not found"
    )


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identifier(identifier_id: int, s: ServicesDep):
    if not s.identifiers.delete(identifier_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Identifier {identifier_id} not found"
        )


@router.post("/{identifier_id}/assign/{user_id}", response_model=IdentifierWithUser)
def assign_identifier_to_user(identifier_id: int, user_id: int, s: ServicesDep):
    if not s.users.get_by_id(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found")
    if identifier := s.identifiers.assign_to_user(identifier_id, user_id):
        return identifier
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"Identifier {identifier_id} not found"
    )


@router.post("/{identifier_id}/unassign", response_model=IdentifierWithUser)
def unassign_identifier(identifier_id: int, s: ServicesDep):
    if identifier := s.identifiers.assign_to_user(identifier_id, None):
        return identifier
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"Identifier {identifier_id} not found"
    )
