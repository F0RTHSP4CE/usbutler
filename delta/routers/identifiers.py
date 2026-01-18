from fastapi import APIRouter, Depends, status

from schemas import (
    Identifier,
    IdentifierCreate,
    IdentifierUpdate,
    IdentifierResponse,
    IdentifierListResponse,
)
from services import IdentifierService, get_identifier_service

router = APIRouter(prefix="/identifiers", tags=["Identifiers"])


@router.get("", response_model=IdentifierListResponse)
def get_identifiers(
    service: IdentifierService = Depends(get_identifier_service),
) -> IdentifierListResponse:
    """Get all identifiers."""
    identifiers = service.get_all()
    return IdentifierListResponse(data=identifiers, total=len(identifiers))


@router.get("/{identifier_id}", response_model=IdentifierResponse)
def get_identifier(
    identifier_id: str, service: IdentifierService = Depends(get_identifier_service)
) -> IdentifierResponse:
    """Get an identifier by ID."""
    identifier = service.get_by_id(identifier_id)
    return IdentifierResponse(data=identifier)


@router.post("", response_model=IdentifierResponse, status_code=status.HTTP_201_CREATED)
def create_identifier(
    identifier_data: IdentifierCreate,
    service: IdentifierService = Depends(get_identifier_service),
) -> IdentifierResponse:
    """Create a new identifier."""
    identifier = service.create(identifier_data)
    return IdentifierResponse(data=identifier)


@router.put("/{identifier_id}", response_model=IdentifierResponse)
def update_identifier(
    identifier_id: str,
    identifier_data: IdentifierUpdate,
    service: IdentifierService = Depends(get_identifier_service),
) -> IdentifierResponse:
    """Update an existing identifier."""
    identifier = service.update(identifier_id, identifier_data)
    return IdentifierResponse(data=identifier)


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identifier(
    identifier_id: str, service: IdentifierService = Depends(get_identifier_service)
) -> None:
    """Delete an identifier."""
    service.delete(identifier_id)
