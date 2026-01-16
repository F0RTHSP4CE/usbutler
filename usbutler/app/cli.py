"""Start the door controller and web UI with no flags."""

from __future__ import annotations

import os
import threading

from app.services.reader_control import ReaderControl
from app.services.door_service import DoorControlService
from app.services.emv_service import EMVCardService
from app.services.auth_service import AuthenticationService


class SmartDoorLockController:
    """Door controller service loop."""

    def __init__(self, reader_control: ReaderControl) -> None:
        self.emv_service = EMVCardService()
        db_path = os.getenv("USBUTLER_USERS_DB", "users.json")
        self.auth_service = AuthenticationService(db_path)
        self.door_service = DoorControlService()
        self.reader_control = reader_control
        self.running = False
        self._pause_condition = threading.Condition()

    def run_authentication_cycle(self) -> bool:
        owner = self.reader_control.get_owner()
        if owner != "door":
            return False

        if self.reader_control.get_owner() != "door":
            return False

        if not self.emv_service.wait_for_card(timeout=5):
            return False

        try:
            scan_result = self.emv_service.read_card_data()
            identifier = scan_result.primary_identifier()
            if not identifier:
                return False

            user = self.auth_service.authenticate_user(identifier)
            if not user:
                return False

            self.door_service.open_door(user)
            return True
        finally:
            self.emv_service.wait_for_card_removal(timeout=10)
            self.emv_service.disconnect()
            self._cooperative_pause(1)

    def run(self) -> None:
        self.running = True
        while self.running:
            try:
                if self.reader_control.get_owner() != "door":
                    self._cooperative_pause(1)
                    continue
                self.run_authentication_cycle()
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception:
                self._cooperative_pause(2)

    def stop(self) -> None:
        self.running = False
        with self._pause_condition:
            self._pause_condition.notify_all()

    def _cooperative_pause(self, duration: float) -> None:
        if duration <= 0:
            return
        with self._pause_condition:
            self._pause_condition.wait(timeout=duration)


def main() -> None:
    from app.web.app import create_app
    import uvicorn

    shared_reader_control = ReaderControl()
    controller = SmartDoorLockController(shared_reader_control)

    door_thread = threading.Thread(
        target=controller.run, name="DoorController", daemon=True
    )
    door_thread.start()

    host = os.getenv("USBUTLER_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("USBUTLER_WEB_PORT", "8000"))

    try:
        app = create_app()
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        controller.stop()
        door_thread.join(timeout=5)


if __name__ == "__main__":
    main()
