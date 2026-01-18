"""Dependency injection providers for FastAPI."""

from dataclasses import dataclass
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


@dataclass
class Services:
    """Container for all injected services."""

    db: Session
    users: UserService
    doors: DoorService
    identifiers: IdentifierService
    door_control: DoorControlService
    card_reader_polling: Optional[object] = None


# Module-level reference for card reader polling (set at startup)
_card_reader_polling = None


def set_card_reader_polling(service) -> None:
    """Set the card reader polling service (called at startup)."""
    global _card_reader_polling
    _card_reader_polling = service


def get_services(db: DbSession) -> Services:
    """Dependency provider for all services."""
    return Services(
        db=db,
        users=UserService(db),
        doors=DoorService(db),
        identifiers=IdentifierService(db),
        door_control=DoorControlService(),
        card_reader_polling=_card_reader_polling,
    )


ServicesDep = Annotated[Services, Depends(get_services)]
