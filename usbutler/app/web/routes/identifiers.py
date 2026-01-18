"""Identifier (card) management routes."""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Body, Depends, Path, Response, status

from app.services.auth_service import AuthServiceError
from app.web.common import (
    AddIdentifierRequest,
    UserResponse,
    IdentifierListResponse,
    ErrorResponse,
    SuccessResponse,
    UserOut,
    IdentifierOut,
    AuthService,
    get_auth_service,
)

router = APIRouter(tags=["Identifiers"])


def _map_auth_error_to_status(code: str) -> int:
    """Map auth service error codes to HTTP status codes."""
    return {
        "missing_identifier": status.HTTP_400_BAD_REQUEST,
        "missing_name": status.HTTP_400_BAD_REQUEST,
        "invalid_access_level": status.HTTP_400_BAD_REQUEST,
        "user_exists": status.HTTP_409_CONFLICT,
        "identifier_exists": status.HTTP_409_CONFLICT,
        "not_found": status.HTTP_404_NOT_FOUND,
    }.get(code, status.HTTP_400_BAD_REQUEST)


def _handle_auth_error(response: Response, exc: AuthServiceError) -> ErrorResponse:
    """Convert an AuthServiceError to an ErrorResponse."""
    response.status_code = _map_auth_error_to_status(exc.code)
    existing_user = getattr(exc, "existing_user", None)
    return ErrorResponse(
        error=exc.code,
        message=exc.message,
        existing_user=(
            UserOut.model_validate(existing_user, from_attributes=True)
            if existing_user
            else None
        ),
    )


@router.get(
    "/users/{user_id}/identifiers",
    response_model=Union[IdentifierListResponse, ErrorResponse],
    summary="List user identifiers",
)
async def list_user_identifiers(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    auth_service: AuthService = Depends(get_auth_service),
) -> IdentifierListResponse | ErrorResponse:
    """Get all identifiers (cards) for a user."""
    try:
        user = auth_service.get_user_or_raise(user_id)
        identifiers = [
            IdentifierOut.model_validate(ident, from_attributes=True)
            for ident in user.identifiers
        ]
        return IdentifierListResponse(data=identifiers, user_id=user_id)
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.post(
    "/users/{user_id}/identifiers",
    response_model=Union[UserResponse, ErrorResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add identifier to user",
)
async def add_identifier(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    payload: AddIdentifierRequest = Body(...),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | ErrorResponse:
    """Add a new identifier (card) to an existing user."""
    if not payload.value:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return ErrorResponse(
            error="missing_identifier", message="Identifier value is required"
        )

    try:
        user = auth_service.add_identifier_to_user_or_raise(
            user_id=user_id,
            identifier_value=payload.value,
            identifier_type=payload.type or "UID",
            metadata=payload.metadata,
        )
        response.status_code = status.HTTP_201_CREATED
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.delete(
    "/users/{user_id}/identifiers/{identifier_value:path}",
    response_model=Union[UserResponse, SuccessResponse, ErrorResponse],
    summary="Remove identifier from user",
)
async def remove_identifier(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    identifier_value: str = Path(..., description="Identifier value"),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | SuccessResponse | ErrorResponse:
    """Remove an identifier from a user. If it's the last identifier, the user is deleted."""
    try:
        user, user_removed = auth_service.remove_identifier_from_user_or_raise(
            user_id, identifier_value
        )
        if user_removed:
            return SuccessResponse(message="User deleted (last identifier removed)")
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.get(
    "/identifiers/{identifier_value:path}",
    response_model=Union[UserResponse, ErrorResponse],
    summary="Find user by identifier",
)
async def find_by_identifier(
    response: Response,
    identifier_value: str = Path(..., description="Identifier value to search"),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | ErrorResponse:
    """Find the user associated with a specific identifier (card)."""
    value = identifier_value.strip()
    if not value:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return ErrorResponse(
            error="missing_identifier", message="Identifier value is required"
        )

    try:
        user = auth_service.find_user_by_identifier_or_raise(value)
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)
