"""Dependency injection providers for FastAPI."""

import secrets
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.door_control_service import DoorControlService
from app.services.door_service import DoorService
from app.services.identifier_service import IdentifierService
from app.services.notification_service import NotificationService
from app.services.user_service import UserService

# API Key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Annotated[str | None, Depends(api_key_header)]) -> bool:
    """Verify the API key from the X-API-Key header.

    If API_PASSWORD is not set, authentication is disabled.
    """
    if not settings.API_PASSWORD:
        # No password configured, allow all requests
        return True

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not secrets.compare_digest(api_key, settings.API_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return True


# Type alias for API key authentication dependency
ApiKeyAuth = Annotated[bool, Depends(verify_api_key)]

# Type alias for database session dependency
DbSession = Annotated[Session, Depends(get_db)]


# Singletons (stateless services)
_notification_service = NotificationService()
_door_control_service = DoorControlService(_notification_service)
_card_reader_polling = None


def get_door_control_service() -> DoorControlService:
    """Get the singleton door control service."""
    return _door_control_service


def set_card_reader_polling(service) -> None:
    """Set the card reader polling service (called at startup)."""
    global _card_reader_polling
    _card_reader_polling = service


@dataclass
class Services:
    """Container for all injected services."""

    db: Session
    users: UserService
    doors: DoorService
    identifiers: IdentifierService
    door_control: DoorControlService
    card_reader_polling: Optional[object] = None


def _create_services(db: Session) -> Services:
    """Create a Services instance with all dependencies."""
    return Services(
        db=db,
        users=UserService(db),
        doors=DoorService(db),
        identifiers=IdentifierService(db),
        door_control=_door_control_service,
        card_reader_polling=_card_reader_polling,
    )


def get_services(db: DbSession, _auth: ApiKeyAuth) -> Services:
    """Dependency provider for all services.

    Requires valid API key authentication if API_PASSWORD is configured.
    """
    return _create_services(db)


def get_services_no_auth(db: DbSession) -> Services:
    """Dependency provider for services without API authentication.

    Used for UI routes that handle their own authentication.
    """
    return _create_services(db)


ServicesDep = Annotated[Services, Depends(get_services)]
ServicesDepNoAuth = Annotated[Services, Depends(get_services_no_auth)]
