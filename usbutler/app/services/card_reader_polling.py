"""Card reader polling service for background authentication."""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import settings
from app.models.door_event import DoorEventType
from app.models.identifier import IdentifierType
from app.services.card_reader import CardReaderService, CardScanResult
from app.services.door_control_service import DoorControlService, SessionFactory
from app.services.mifare_block import MifareBlockStore
from app.services.mifare_rotation_service import MifareRotationService
from app.utils.masking import mask_identifier

logger = logging.getLogger(__name__)


@dataclass
class LastScan:
    value: str
    type: IdentifierType
    scanned_at: datetime


class CardReaderPollingService:
    """Polls the card reader and processes scans for authentication."""

    def __init__(
        self,
        card_reader_service: CardReaderService,
        door_control_service: DoorControlService,
        session_factory: SessionFactory,
        poll_interval: float = 1.0,
        default_door_id: int = 1,
        mifare_store: Optional[MifareBlockStore] = None,
    ):
        self._reader = card_reader_service
        self._door_control = door_control_service
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.default_door_id = default_door_id
        self._mifare_store = mifare_store or card_reader_service.mifare_store

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_scan: Optional[LastScan] = None
        self._lock = threading.Lock()

        self._last_id: Optional[str] = None
        self._last_time: float = 0
        self._debounce = 3.0
        self._consecutive_read_failures = 0

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
            except Exception as exc:
                logger.error("Card polling error: %s", exc)
                self._restart_pcscd()
            time.sleep(self.poll_interval)

    def _poll_once(self) -> None:
        if not self._reader.wait_for_card(timeout=5):
            return

        restart_reader = False
        completed_read = False
        try:
            result = self._reader.read_card_data()
            value = result.identifier()
            type_str = result.identifier_type()
            mifare_only = result.mifare_classic and result.mifare_uuid is not None

            if (not value or not type_str) and not mifare_only:
                self._consecutive_read_failures += 1
                logger.warning(
                    "Card detected without a readable identifier (failure %s)",
                    self._consecutive_read_failures,
                )
                if self._consecutive_read_failures >= 3:
                    restart_reader = True
                    self._consecutive_read_failures = 0
                return

            completed_read = True
            self._consecutive_read_failures = 0
            if type_str:
                try:
                    id_type = IdentifierType(type_str)
                except ValueError:
                    return
            else:
                id_type = IdentifierType.UID

            # Never publish a raw rolling UUID through the last-scan API. A
            # UUID-only scan can still authenticate, but cannot be assigned by
            # the legacy UID administration flow until its UID is readable.
            if value:
                with self._lock:
                    self._last_scan = LastScan(
                        value=value, type=id_type, scanned_at=datetime.now()
                    )

            now = time.monotonic()
            debounce_id = value or f"mifare:{result.mifare_uuid}"
            if (
                debounce_id == self._last_id
                and (now - self._last_time) < self._debounce
            ):
                return
            self._last_id = debounce_id
            self._last_time = now

            logger.info(
                "Card scanned: %s=%s",
                id_type.value,
                mask_identifier(value or "data-uuid"),
            )
            self._authenticate(result)

        except Exception as exc:
            logger.error("Card read error: %s", exc)
            self._consecutive_read_failures += 1
            if self._consecutive_read_failures >= 3:
                restart_reader = True
                self._consecutive_read_failures = 0
        finally:
            if completed_read:
                self._reader.wait_for_card_removal(timeout=2)
            self._reader.disconnect()
            if restart_reader:
                self._restart_pcscd()

    def _authenticate(self, scan: CardScanResult) -> None:
        from app.services.auth_service import AuthService

        display_value = scan.identifier() or scan.uid or ""
        with self.session_factory() as services:
            auth = AuthService(services.users, services.identifiers)
            success, user, identifier, message = auth.authenticate_card(scan)

            if not success or not user or not identifier:
                logger.info(
                    "Auth failed for %s: %s",
                    mask_identifier(display_value),
                    message,
                )
                return

            logger.info("Auth OK for '%s'", user.username)
            door = services.doors.get_by_id(self.default_door_id)
            if not door:
                logger.error("Door %s not found", self.default_door_id)
                return

            # Access is authorized before any best-effort database/card mutation.
            logger.info("Opening door '%s' for '%s'", door.name, user.username)
            self._door_control.open_door_async(
                door, user.username, DoorEventType.CARD, user.id
            )

            if not scan.mifare_classic:
                return

            rotation = MifareRotationService(services.db)
            prepared = None
            try:
                if scan.mifare_uuid and rotation.confirm_observed(
                    identifier.id,
                    scan.mifare_uuid,
                    settings.MIFARE_UUID_HISTORY_LIMIT,
                ):
                    logger.info("Confirmed pending MIFARE UUID for '%s'", user.username)

                if not (
                    settings.MIFARE_DATA_ROTATION_ENABLED
                    and user.mifare_rotation_enabled
                    and self._mifare_store is not None
                ):
                    return

                prepared = rotation.prepare_write(identifier.id)
                if not prepared:
                    return

                result = self._mifare_store.write_and_verify(
                    prepared.target_uuid, expected_uid=scan.uid
                )
                rotation.record_attempt(
                    prepared.credential_id,
                    None if result.verified else result.detail,
                )
                if result.verified:
                    rotation.confirm_observed(
                        identifier.id,
                        prepared.target_uuid,
                        settings.MIFARE_UUID_HISTORY_LIMIT,
                    )
                    logger.info(
                        "Verified MIFARE UUID rotation for '%s' after %s attempt(s)",
                        user.username,
                        result.attempts,
                    )
                else:
                    logger.warning(
                        "MIFARE UUID rotation remains pending for '%s': %s",
                        user.username,
                        result.detail,
                    )
            except Exception as exc:
                services.db.rollback()
                logger.exception(
                    "MIFARE UUID rotation failed for '%s'; door access was preserved",
                    user.username,
                )
                if prepared is not None:
                    try:
                        rotation.record_attempt(prepared.credential_id, str(exc))
                    except Exception:
                        logger.exception("Failed to persist MIFARE write failure")

    def _restart_pcscd(self) -> None:
        try:
            result = subprocess.run(
                ["supervisorctl", "restart", "pcscd"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                time.sleep(2.0)
                return
            subprocess.run(
                ["systemctl", "restart", "pcscd"],
                capture_output=True,
                timeout=10,
            )
            time.sleep(2.0)
        except Exception as exc:
            logger.warning("pcscd restart failed: %s", exc)
