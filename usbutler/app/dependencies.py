"""Dependency injection for FastAPI."""

import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Annotated[str | None, Depends(api_key_header)]) -> bool:
    if not settings.API_PASSWORD:
        return True
    if not api_key or not secrets.compare_digest(api_key, settings.API_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return True


ApiKeyAuth = Annotated[bool, Depends(verify_api_key)]


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class Services:
    """Container for all services."""

    db: Session
    users: "UserService"
    doors: "DoorService"
    door_events: "DoorEventService"
    identifiers: "IdentifierService"
    door_control: "DoorControlService"
    card_reader_polling: Optional["CardReaderPollingService"] = None


# Singleton registry for hardware services
class ServiceRegistry:
    _instance: Optional["ServiceRegistry"] = None

    def __init__(self):
        self._door_control: Optional["DoorControlService"] = None
        self._notification: Optional["NotificationService"] = None
        self.card_reader_polling: Optional["CardReaderPollingService"] = None

    @classmethod
    def get(cls) -> "ServiceRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def notification_service(self) -> "NotificationService":
        if self._notification is None:
            from app.services.notification_service import NotificationService

            self._notification = NotificationService()
        return self._notification

    @property
    def door_control_service(self) -> "DoorControlService":
        if self._door_control is None:
            from app.services.door_control_service import DoorControlService

            self._door_control = DoorControlService(
                self.notification_service, create_services_for_thread
            )
        return self._door_control


def get_registry() -> ServiceRegistry:
    return ServiceRegistry.get()


def _create_services(db: Session) -> Services:
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
    """Create services for background threads."""
    db = SessionLocal()
    try:
        yield _create_services(db)
    finally:
        db.close()


def get_services(db: DbSession, _auth: ApiKeyAuth) -> Services:
    """Get services with API key authentication."""
    return _create_services(db)


def get_services_ui(db: DbSession) -> Services:
    """Get services for UI routes (no API key header check)."""
    return _create_services(db)


ServicesDep = Annotated[Services, Depends(get_services)]
ServicesDepUI = Annotated[Services, Depends(get_services_ui)]


# Type hints for lazy imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.card_reader_polling import CardReaderPollingService
    from app.services.door_control_service import DoorControlService
    from app.services.door_event_service import DoorEventService
    from app.services.door_service import DoorService
    from app.services.identifier_service import IdentifierService
    from app.services.notification_service import NotificationService
    from app.services.user_service import UserService
