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
from app.services.auth_service import AuthService
from app.services.card_reader import CardReaderService, CardScanResult
from app.services.door_control_service import DoorControlService

logger = logging.getLogger(__name__)


@dataclass
class LastScan:
    """Information about the last scanned card."""

    value: str
    type: IdentifierType
    scanned_at: datetime


class CardReaderPollingService:
    """
    Background service that polls the card reader and processes scans.

    This service:
    1. Continuously polls the NFC reader for cards
    2. Extracts the identifier (PAN or UID)
    3. Authenticates the user
    4. Opens the configured door if authentication succeeds
    5. Stores the last scan for the web panel
    """

    def __init__(
        self,
        card_reader_service: CardReaderService,
        door_control_service: DoorControlService,
        poll_interval: float = 1.0,
        default_door_id: int = 1,
        on_scan_callback: Optional[Callable[[CardScanResult], None]] = None,
    ):
        self._card_reader_service = card_reader_service
        self._door_control_service = door_control_service
        self.poll_interval = poll_interval
        self.default_door_id = default_door_id
        self.on_scan_callback = on_scan_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_scan: Optional[LastScan] = None
        self._last_scan_lock = threading.Lock()

        # Debounce: track last processed identifier to avoid rapid re-auth
        self._last_processed_identifier: Optional[str] = None
        self._last_processed_time: float = 0
        self._debounce_seconds = 3.0

    def start(self) -> None:
        """Start the polling thread."""
        if self._running:
            logger.warning("Card reader polling already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._polling_loop,
            name="card-reader-polling",
            daemon=True,
        )
        self._thread.start()
        logger.info("Card reader polling started")

    def stop(self) -> None:
        """Stop the polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Card reader polling stopped")

    def get_last_scan(self) -> Optional[dict]:
        """Get the last scanned card information."""
        with self._last_scan_lock:
            if self._last_scan:
                return {
                    "value": self._last_scan.value,
                    "type": self._last_scan.type,
                    "scanned_at": self._last_scan.scanned_at,
                }
            return None

    def _set_last_scan(self, value: str, id_type: IdentifierType) -> None:
        """Store the last scanned card information."""
        with self._last_scan_lock:
            self._last_scan = LastScan(
                value=value,
                type=id_type,
                scanned_at=datetime.now(),
            )

    def _polling_loop(self) -> None:
        """Main polling loop running in a separate thread."""
        logger.info("Card reader polling loop started")

        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                # Exceptions that escape _poll_once (not caught inside)
                # e.g., errors from wait_for_card() before the try block
                logger.error(f"Unexpected error in card reader polling: {e}")
                # Restart pcscd to recover from stuck reader state
                self._restart_pcscd()

            time.sleep(self.poll_interval)

        logger.info("Card reader polling loop ended")

    def _poll_once(self) -> None:
        """Perform a single poll of the card reader."""
        # Wait for a card to be present
        card_detected = self._card_reader_service.wait_for_card(timeout=1)

        if not card_detected:
            return

        # Once a card is detected, always restart pcscd after processing
        # to prevent phantom reads (even on errors)
        try:
            # Read card data
            scan_result = self._card_reader_service.read_card_data()

            # Get identifier
            identifier_value = scan_result.identifier()
            identifier_type_str = scan_result.identifier_type()

            if not identifier_value or not identifier_type_str:
                logger.debug("No valid identifier found on card")
                return

            # Map to IdentifierType enum
            try:
                identifier_type = IdentifierType(identifier_type_str)
            except ValueError:
                logger.warning(f"Unknown identifier type: {identifier_type_str}")
                return

            # Store last scan
            self._set_last_scan(identifier_value, identifier_type)

            # Debounce check
            current_time = time.time()
            if (
                identifier_value == self._last_processed_identifier
                and (current_time - self._last_processed_time) < self._debounce_seconds
            ):
                logger.debug(f"Debouncing identifier {identifier_value}")
                return

            self._last_processed_identifier = identifier_value
            self._last_processed_time = current_time

            logger.info(f"Card scanned: {identifier_type.value}={identifier_value}")

            # Call optional callback
            if self.on_scan_callback:
                self.on_scan_callback(scan_result)

            # Process authentication
            self._process_authentication(identifier_value)

        except Exception as e:
            logger.error(f"Error reading card: {e}")
            # Don't re-raise - we handle it in finally by restarting pcscd

        finally:
            # Disconnect from card
            self._card_reader_service.disconnect()

            # Restart pcscd to fully reset USB reader and prevent phantom reads
            self._restart_pcscd()

    def _process_authentication(self, identifier_value: str) -> None:
        """Process authentication for a scanned identifier."""
        from app.dependencies import create_services_for_thread

        with create_services_for_thread() as services:
            auth = AuthService(services.users, services.identifiers)

            success, user, _, message = auth.authenticate_by_identifier(
                identifier_value
            )

            if not success or user is None:
                logger.info(f"Authentication failed for {identifier_value}: {message}")
                return

            logger.info(f"Authentication successful for user '{user.username}'")

            door = services.doors.get_by_id(self.default_door_id)
            if not door:
                logger.error(f"Default door {self.default_door_id} not found")
                return

            # Record the event in database
            services.door_events.create(
                door_id=door.id,
                event_type=DoorEventType.CARD,
                user_id=user.id,
                username=user.username,
            )

            self._door_control_service.open_door_for_card(door, user.username)

    def _restart_pcscd(self) -> None:
        """Restart pcscd to fully reset USB reader state.

        This is a nuclear option to prevent phantom reads by forcing
        a complete re-initialization of the PC/SC subsystem.
        """
        try:
            logger.info("Restarting pcscd to reset reader...")
            # Try supervisorctl first (container environment)
            result = subprocess.run(
                ["supervisorctl", "restart", "pcscd"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("pcscd restarted via supervisorctl")
                # Give pcscd time to fully restart and detect the reader
                time.sleep(2.0)
                return

            # Fallback: try systemctl (host environment)
            result = subprocess.run(
                ["systemctl", "restart", "pcscd"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("pcscd restarted via systemctl")
                time.sleep(2.0)
                return

            # Last resort: kill and let supervisor restart
            subprocess.run(["pkill", "-9", "pcscd"], timeout=5)
            logger.info("pcscd killed, waiting for restart...")
            time.sleep(3.0)

        except subprocess.TimeoutExpired:
            logger.warning("pcscd restart timed out")
        except Exception as e:
            logger.error(f"Failed to restart pcscd: {e}")
