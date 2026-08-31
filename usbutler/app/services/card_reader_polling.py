"""Card reader polling service for background authentication."""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.models.door_event import DoorEventType
from app.models.identifier import IdentifierState, IdentifierType
from app.config import settings
from app.services.card_reader import CardReaderService, CardScanResult
from app.services.door_control_service import DoorControlService, SessionFactory
from app.services.uid_rotation_service import UidRotationService, is_rotatable_uid
from app.services.uid_writer import (
    ACR122UidWriter,
    UidWriter,
    classify_writer_exception,
)
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
        uid_writer: Optional[UidWriter] = None,
    ):
        self._reader = card_reader_service
        self._door_control = door_control_service
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.default_door_id = default_door_id
        self._uid_writer = uid_writer or ACR122UidWriter(
            card_reader_service.nfc_reader,
            settings.MIFARE_CLASSIC_KEY_A,
            max_attempts=settings.UID_WRITE_MAX_ATTEMPTS,
            retry_delay_seconds=settings.UID_WRITE_RETRY_DELAY_SECONDS,
        )

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
            except Exception as e:
                logger.error(f"Card polling error: {e}")
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

            if not value or not type_str:
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

            try:
                id_type = IdentifierType(type_str)
            except ValueError:
                return

            with self._lock:
                self._last_scan = LastScan(
                    value=value, type=id_type, scanned_at=datetime.now()
                )

            # Debounce
            now = time.monotonic()
            if value == self._last_id and (now - self._last_time) < self._debounce:
                return
            self._last_id = value
            self._last_time = now

            logger.info(f"Card scanned: {id_type.value}={mask_identifier(value)}")
            self._authenticate(value, result)

        except Exception as e:
            logger.error(f"Card read error: {e}")
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

    def _authenticate(self, identifier: str, scan: CardScanResult) -> None:
        from app.services.auth_service import AuthService

        with self.session_factory() as s:
            auth = AuthService(s.users, s.identifiers)
            success, user, matched_identifier, msg = auth.authenticate(identifier)

            if not success or not user or not matched_identifier:
                logger.info(f"Auth failed for {mask_identifier(identifier)}: {msg}")
                return

            logger.info(f"Auth OK for '{user.username}'")

            door = s.doors.get_by_id(self.default_door_id)
            if not door:
                logger.error(f"Door {self.default_door_id} not found")
                return

            logger.info(f"Opening door '{door.name}' for '{user.username}'")
            self._door_control.open_door_async(
                door, user.username, DoorEventType.CARD, user.id
            )

            rotation = UidRotationService(s.db)
            if matched_identifier.state == IdentifierState.PENDING:
                try:
                    promoted = rotation.promote_pending(
                        matched_identifier.id,
                        create_successor=(
                            settings.UID_ROTATION_ENABLED and user.uid_rotation_enabled
                        ),
                    )
                    if promoted:
                        matched_identifier = promoted
                        logger.info(
                            "Confirmed a pending UID for '%s' lineage %s",
                            user.username,
                            promoted.chain_root_id,
                        )
                except Exception:
                    s.db.rollback()
                    logger.exception(
                        "Failed to promote UID for '%s'; door access was preserved",
                        user.username,
                    )
                    return

            if not (
                settings.UID_ROTATION_ENABLED
                and user.uid_rotation_enabled
                and scan.mifare_classic
                and matched_identifier.state == IdentifierState.CURRENT
                and is_rotatable_uid(matched_identifier.value)
            ):
                return

            try:
                minimum_interval = (
                    None if user.uid_rotation_every_read else timedelta(hours=24)
                )
                prepared = rotation.prepare_write(
                    matched_identifier.id,
                    minimum_interval=minimum_interval,
                )
                if not prepared:
                    logger.info(
                        "UID rotation skipped for '%s': 24-hour write limit is active",
                        user.username,
                    )
                    return
                logger.info(
                    "Attempting UID rotation for '%s' lineage %s (%s policy)",
                    user.username,
                    prepared.chain_root_id,
                    "every read" if user.uid_rotation_every_read else "24-hour",
                )
                result = self._uid_writer.write_uid(
                    prepared.source_uid, prepared.target_uid
                )
                rotation.complete_attempt(
                    prepared.attempt_id,
                    result.protocol,
                    result.outcome,
                    result.detail,
                )
                logger.info(
                    "UID rotation attempt for '%s': protocol=%s outcome=%s",
                    user.username,
                    result.protocol.value,
                    result.outcome.value,
                )
            except Exception as exc:
                s.db.rollback()
                logger.exception(
                    "UID rotation failed for '%s'; door access was preserved",
                    user.username,
                )
                if "prepared" in locals() and prepared:
                    try:
                        from app.models.identifier import UidRotationProtocol

                        rotation.complete_attempt(
                            prepared.attempt_id,
                            UidRotationProtocol.UNKNOWN,
                            classify_writer_exception(exc),
                            str(exc),
                        )
                    except Exception:
                        logger.exception("Failed to persist UID rotation failure")

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
