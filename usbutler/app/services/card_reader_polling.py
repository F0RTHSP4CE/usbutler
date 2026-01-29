"""Card reader polling service for background authentication."""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from app.models.door_event import DoorEventType
from app.models.identifier import IdentifierType
from app.services.card_reader import CardReaderService
from app.services.door_control_service import DoorControlService, SessionFactory
from app.utils.masking import mask_identifier

logger = logging.getLogger(__name__)


@dataclass
class LastScan:
    value: str
    type: IdentifierType
    scanned_at: datetime


class CardReaderPollingService:
    """Polls card reader and processes scans for authentication."""

    def __init__(
        self,
        card_reader_service: CardReaderService,
        door_control_service: DoorControlService,
        session_factory: SessionFactory,
        poll_interval: float = 1.0,
        default_door_id: int = 1,
    ):
        self._reader = card_reader_service
        self._door_control = door_control_service
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.default_door_id = default_door_id

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_scan: Optional[LastScan] = None
        self._lock = threading.Lock()

        self._last_id: Optional[str] = None
        self._last_time: float = 0
        self._debounce = 3.0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Card reader polling started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Card reader polling stopped")

    def get_last_scan(self) -> Optional[dict]:
        with self._lock:
            if not self._last_scan:
                return None
            return {
                "value": self._last_scan.value,
                "type": self._last_scan.type,
                "scanned_at": self._last_scan.scanned_at,
            }

    def _loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"Card polling error: {e}")
                self._restart_pcscd()
            time.sleep(self.poll_interval)

    def _poll_once(self) -> None:
        if not self._reader.wait_for_card(timeout=5):
            return

        try:
            result = self._reader.read_card_data()
            value = result.identifier()
            type_str = result.identifier_type()

            if not value or not type_str:
                return

            try:
                id_type = IdentifierType(type_str)
            except ValueError:
                return

            with self._lock:
                self._last_scan = LastScan(
                    value=value, type=id_type, scanned_at=datetime.now()
                )

            # Debounce
            now = time.time()
            if value == self._last_id and (now - self._last_time) < self._debounce:
                return
            self._last_id = value
            self._last_time = now

            logger.info(f"Card scanned: {id_type.value}={mask_identifier(value)}")
            self._authenticate(value)

        except Exception as e:
            logger.error(f"Card read error: {e}")
        finally:
            self._reader.disconnect()
            self._restart_pcscd()

    def _authenticate(self, identifier: str) -> None:
        from app.services.auth_service import AuthService

        with self.session_factory() as s:
            auth = AuthService(s.users, s.identifiers)
            success, user, _, msg = auth.authenticate(identifier)

            if not success or not user:
                logger.info(f"Auth failed for {mask_identifier(identifier)}: {msg}")
                return

            logger.info(f"Auth OK for '{user.username}'")

            door = s.doors.get_by_id(self.default_door_id)
            if not door:
                logger.error(f"Door {self.default_door_id} not found")
                return

            logger.info(f"Opening door '{door.name}' for '{user.username}'")
            # Use blocking call since we're already in a background thread
            # and the door object will be detached after session closes
            self._door_control.open_door_blocking(
                door, user.username, DoorEventType.CARD, user.id
            )

    def _restart_pcscd(self) -> None:
        try:
            result = subprocess.run(
                ["supervisorctl", "restart", "pcscd"], capture_output=True, timeout=10
            )
            if result.returncode == 0:
                time.sleep(2.0)
                return
            subprocess.run(
                ["systemctl", "restart", "pcscd"], capture_output=True, timeout=10
            )
            time.sleep(2.0)
        except Exception as e:
            logger.warning(f"pcscd restart failed: {e}")
