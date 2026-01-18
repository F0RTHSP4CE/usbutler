"""User management routes."""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Body, Depends, Path, Response, status

from app.services.auth_service import AuthServiceError
from app.web.common import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
    UserListResponse,
    ErrorResponse,
    SuccessResponse,
    UserOut,
    AuthService,
    get_auth_service,
)

router = APIRouter(prefix="/users", tags=["Users"])


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
    "",
    response_model=UserListResponse,
    summary="List all users",
)
async def list_users(
    auth_service: AuthService = Depends(get_auth_service),
) -> UserListResponse:
    """Get a list of all registered users."""
    users = auth_service.list_users()
    serialized = [UserOut.model_validate(user, from_attributes=True) for user in users]
    serialized.sort(key=lambda u: u.name.lower())
    return UserListResponse(data=serialized)


@router.post(
    "",
    response_model=Union[UserResponse, ErrorResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
)
async def create_user(
    response: Response,
    payload: CreateUserRequest = Body(...),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | ErrorResponse:
    """Create a new user with an initial identifier (card)."""
    if not payload.identifier:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return ErrorResponse(
            error="missing_identifier", message="Identifier is required"
        )

    if not payload.name:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return ErrorResponse(error="missing_name", message="Name is required")

    try:
        user = auth_service.create_user_or_raise(
            identifier_value=payload.identifier,
            name=payload.name,
            access_level=payload.access_level or "user",
            identifier_type=payload.identifier_type or "UID",
            metadata=payload.metadata,
        )
        response.status_code = status.HTTP_201_CREATED
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.get(
    "/{user_id}",
    response_model=Union[UserResponse, ErrorResponse],
    summary="Get user by ID",
)
async def get_user(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | ErrorResponse:
    """Get a specific user by their ID."""
    try:
        user = auth_service.get_user_or_raise(user_id)
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.patch(
    "/{user_id}",
    response_model=Union[UserResponse, ErrorResponse],
    summary="Update user",
)
async def update_user(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    payload: UpdateUserRequest = Body(...),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse | ErrorResponse:
    """Update user details (name, access_level, active status)."""
    try:
        user = auth_service.update_user_or_raise(
            user_id=user_id,
            name=payload.name,
            access_level=payload.access_level,
            active=payload.active,
        )
        return UserResponse(data=UserOut.model_validate(user, from_attributes=True))
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)


@router.delete(
    "/{user_id}",
    response_model=Union[SuccessResponse, ErrorResponse],
    summary="Delete user",
)
async def delete_user(
    response: Response,
    user_id: str = Path(..., description="User ID"),
    auth_service: AuthService = Depends(get_auth_service),
) -> SuccessResponse | ErrorResponse:
    """Delete a user and all their identifiers."""
    try:
        auth_service.delete_user_or_raise(user_id)
        return SuccessResponse(message="User deleted successfully")
    except AuthServiceError as exc:
        return _handle_auth_error(response, exc)
