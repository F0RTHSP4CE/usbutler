"""Dependency injection for FastAPI."""

import ipaddress
import logging
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from html import escape as html_escape

from app.config import settings
from app.database import SessionLocal
from app.services.api_token_service import TOKEN_PREFIX, hash_token

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(
    name="X-API-Key", scheme_name="ApiKey", auto_error=False,
    description="User API token (ubt_...) or admin password",
)
pos_password_header = APIKeyHeader(
    name="X-POS-Password", scheme_name="PosPassword", auto_error=False,
    description="POS endpoint password",
)


def _client_ip(request: Request) -> str:
    """Extract client IP from the socket connection.

    X-Forwarded-For is NOT trusted because there is no reverse proxy
    in front of this service — any client could spoof the header.
    Host networking ensures request.client.host is the real peer IP.
    """
    return request.client.host if request.client else "unknown"


def _ip_in_cidrs(ip: str, cidrs_csv: str) -> bool:
    """Check if an IP is within any of the comma-separated CIDRs."""
    if not cidrs_csv:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs_csv.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def verify_api_key(
    request: Request,
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> Optional["User"]:
    """Authenticate via per-user token or ADMIN_PASSWORD.

    Returns the authenticated User, or None for admin password access.
    """
    client_ip = _client_ip(request)

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key"
        )

    # Admin password bypass (bootstrap / emergency access)
    if settings.ADMIN_PASSWORD and secrets.compare_digest(
        api_key, settings.ADMIN_PASSWORD
    ):
        return None

    # Per-user token authentication
    if api_key.startswith(TOKEN_PREFIX):
        from app.models.user import User

        token_hash = hash_token(api_key)
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.api_token_hash == token_hash).first()
        finally:
            db.close()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token"
            )

        # IP/subnet restriction
        if user.api_allowed_sources:
            if not _ip_in_cidrs(client_ip, user.api_allowed_sources):
                logger.warning(
                    "Token for user '%s' used from unauthorized IP %s",
                    user.username,
                    client_ip,
                )
                try:
                    registry = get_registry()
                    registry.notification_service.notify_security_alert_async(
                        f"⚠️ API token for <b>{html_escape(user.username)}</b> used from "
                        f"unauthorized IP <code>{html_escape(client_ip)}</code>"
                    )
                except Exception:
                    logger.exception("Failed to send security alert")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Request not allowed from this IP",
                )

        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
    )


def verify_pos_password(
    request: Request,
    pos_password: Annotated[str | None, Depends(pos_password_header)],
) -> bool:
    """Authenticate with POS password for restricted public endpoints."""
    if not settings.POS_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="POS password not configured",
        )
    if not pos_password or not secrets.compare_digest(
        pos_password, settings.POS_PASSWORD
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid POS password"
        )
    return True


ApiKeyAuth = Annotated[Optional["User"], Depends(verify_api_key)]
CallerUser = ApiKeyAuth
PosPasswordAuth = Annotated[bool, Depends(verify_pos_password)]


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


def get_caller(caller: CallerUser) -> Optional["User"]:
    """Get the authenticated caller (User or None for admin)."""
    return caller


def get_services_pos(db: DbSession, _auth: PosPasswordAuth) -> Services:
    """Get services with POS password authentication."""
    return _create_services(db)


def get_services_ui(db: DbSession) -> Services:
    """Get services for UI routes (no API key header check)."""
    return _create_services(db)


ServicesDep = Annotated[Services, Depends(get_services)]
ServicesDepPOS = Annotated[Services, Depends(get_services_pos)]
ServicesDepUI = Annotated[Services, Depends(get_services_ui)]
CallerDep = Annotated[Optional["User"], Depends(get_caller)]


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
