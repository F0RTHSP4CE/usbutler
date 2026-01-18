"""Dependency injection providers for FastAPI."""

from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.door_control_service import DoorControlService
from app.services.door_service import DoorService
from app.services.identifier_service import IdentifierService
from app.services.user_service import UserService

# Type alias for database session dependency
DbSession = Annotated[Session, Depends(get_db)]


def get_user_service(db: DbSession) -> UserService:
    """Dependency provider for UserService."""
    return UserService(db)


def get_door_service(db: DbSession) -> DoorService:
    """Dependency provider for DoorService."""
    return DoorService(db)


def get_identifier_service(db: DbSession) -> IdentifierService:
    """Dependency provider for IdentifierService."""
    return IdentifierService(db)


def get_door_control_service() -> DoorControlService:
    """Dependency provider for DoorControlService."""
    return DoorControlService()


# Type aliases for injected services
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
DoorServiceDep = Annotated[DoorService, Depends(get_door_service)]
IdentifierServiceDep = Annotated[IdentifierService, Depends(get_identifier_service)]
DoorControlServiceDep = Annotated[DoorControlService, Depends(get_door_control_service)]


# Card reader polling service - simple module-level reference
_card_reader_polling = None


def set_card_reader_polling(service) -> None:
    """Set the card reader polling service (called at startup)."""
    global _card_reader_polling
    _card_reader_polling = service


def get_card_reader_polling():
    """Dependency provider for card reader polling service."""
    return _card_reader_polling


CardReaderPollingDep = Annotated[Optional[object], Depends(get_card_reader_polling)]
