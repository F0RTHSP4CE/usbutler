"""Dependency injection providers for FastAPI."""

import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Generator, Optional, TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal


if TYPE_CHECKING:
    from app.services.card_reader_polling import CardReaderPollingService
    from app.services.door_control_service import DoorControlService
    from app.services.door_event_service import DoorEventService
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


ApiKeyAuth = Annotated[bool, Depends(verify_api_key)]


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class Services:
    """Container for all injected services."""

    db: Session
    users: "UserService"
    doors: "DoorService"
    door_events: "DoorEventService"
    identifiers: "IdentifierService"
    door_control: "DoorControlService"
    card_reader_polling: Optional["CardReaderPollingService"] = None


class ServiceRegistry:
    """
    Central registry for singleton services.

    This provides a clean way to access singletons that need to be shared
    across the application without polluting the module namespace with globals.
    """

    _instance: Optional["ServiceRegistry"] = None

    def __init__(self) -> None:
        self._door_control_service: Optional["DoorControlService"] = None
        self._card_reader_polling: Optional["CardReaderPollingService"] = None
        self._notification_service: Optional["NotificationService"] = None

    @classmethod
    def get(cls) -> "ServiceRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def notification_service(self) -> "NotificationService":
        if self._notification_service is None:
            from app.services.notification_service import NotificationService

            self._notification_service = NotificationService()
        return self._notification_service

    @property
    def door_control_service(self) -> "DoorControlService":
        if self._door_control_service is None:
            from app.services.door_control_service import DoorControlService

            self._door_control_service = DoorControlService(self.notification_service)
        return self._door_control_service

    @property
    def card_reader_polling(self) -> Optional["CardReaderPollingService"]:
        return self._card_reader_polling

    @card_reader_polling.setter
    def card_reader_polling(self, service: "CardReaderPollingService") -> None:
        self._card_reader_polling = service


def get_registry() -> ServiceRegistry:
    """Get the service registry."""
    return ServiceRegistry.get()


def _create_services(db: Session) -> Services:
    """Create a Services instance with all dependencies."""
    from app.services.door_event_service import DoorEventService
    from app.services.door_service import DoorService
    from app.services.identifier_service import IdentifierService
    from app.services.user_service import UserService

    registry = get_registry()
    return Services(
        db=db,
        users=UserService(db),
        doors=DoorService(db),
        door_events=DoorEventService(db),
        identifiers=IdentifierService(db),
        door_control=registry.door_control_service,
        card_reader_polling=registry.card_reader_polling,
    )


@contextmanager
def create_services_for_thread() -> Generator[Services, None, None]:
    """Create services for use in background threads.

    Background threads cannot use FastAPI's request-scoped dependency injection,
    so they need to create their own database sessions and services.

    Usage:
        with create_services_for_thread() as services:
            services.doors.get_all()
    """
    db = SessionLocal()
    try:
        yield _create_services(db)
    finally:
        db.close()


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
