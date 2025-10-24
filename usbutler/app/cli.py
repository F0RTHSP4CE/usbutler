"""
Smart Door Lock Controller - Orchestrates the separated services.
This is the main application logic that coordinates EMV reading, authentication, and door control.
"""

import sys
import os
import argparse
import threading
from typing import Optional

from app.services.emv_service import EMVCardService
from app.services.auth_service import AuthenticationService
from app.services.door_service import DoorControlService
from app.services.reader_control import ReaderControl


class SmartDoorLockController:
    """
    Main controller that orchestrates the smart door lock system.
    Coordinates between EMV reading, authentication, and door control services.
    """

    def __init__(self, reader_control: Optional[ReaderControl] = None, ensure_owner: bool = True):
        # Initialize all services
        self.emv_service = EMVCardService()
        db_path = os.getenv("USBUTLER_USERS_DB", "users.json")
        self.auth_service = AuthenticationService(db_path)
        self.door_service = DoorControlService()
        self.reader_control = reader_control or ReaderControl()
        if ensure_owner:
            initial_owner = self.reader_control.get_owner()
            if initial_owner != "door":
                previous_owner = initial_owner
                self.reader_control.set_owner("door", {"previous_owner": previous_owner})
                print(
                    "\n🔁 Reader ownership reset to door service (previous owner: "
                    f"{previous_owner or 'unknown'})."
                )
        self.running = False
        self._reader_reserved = False
        self._pause_condition = threading.Condition()

    def run_authentication_cycle(self) -> bool:
        """
        Run one complete authentication cycle
        Returns True if authentication was successful, False otherwise
        """
        owner = self.reader_control.get_owner()
        if owner != "door":
            if not self._reader_reserved:
                print(
                    "\n⏸️  Reader currently reserved by web UI (owner: "
                    f"{owner}). Waiting for release..."
                )
                self._reader_reserved = True
            return False

        if self._reader_reserved:
            print("✅ Reader ownership returned to door service. Resuming scans.")
            self._reader_reserved = False

        print("\n" + "=" * 50)
        print("🚪 Smart Door Lock - Place EMV card on reader")
        print("=" * 50)

        # Step 1: Wait for card
        if self.reader_control.get_owner() != "door":
            return False

        if not self.emv_service.wait_for_card(timeout=5):
            print("No card detected within timeout")
            return False

        try:
            # Step 2: Get card info (optional)
            atr = self.emv_service.get_card_info()
            if atr:
                print(f"Card ATR: {atr}")

            # Step 3: Read card data (PAN or UID)
            scan_result = self.emv_service.read_card_data()
            identifier = scan_result.primary_identifier()
            identifier_type = scan_result.primary_identifier_type() or "Identifier"

            if not identifier:
                print("❌ Failed to read card data")
                return False

            masked_identifier = (
                identifier if len(identifier) <= 4 else f"****{identifier[-4:]}"
            )

            print(f"Card type (ATR-derived): {scan_result.card_type}")
            print(f"Tag type: {scan_result.tag_type}")
            if scan_result.uid and identifier_type != "UID" and not scan_result.tokenized:
                print(f"UID: {scan_result.uid}")
            if scan_result.pan and identifier_type == "PAN":
                print(f"PAN: {masked_identifier}")
            elif identifier_type == "UID":
                print(f"UID: {masked_identifier}")
            else:
                print(f"{identifier_type}: {masked_identifier}")
            if scan_result.tokenized:
                print("⚠️ Tokenized/HCE card detected; identifier may be unstable.")

            # Step 4: Authenticate user
            user = self.auth_service.authenticate_user(identifier)
            if not user:
                print("❌ Authentication failed - Unknown card")
                print(f"{identifier_type}: {masked_identifier}")
                return False

            # Step 5: Open door for authenticated user
            print(f"\n--- Authentication Successful ---")
            print(f"✅ Welcome, {user.name}!")
            print(f"Access Level: {user.access_level}")

            self.door_service.open_door(user)
            return True

        except Exception as e:
            print(f"Error during authentication cycle: {e}")
            return False
        finally:
            # Always disconnect from card
            self.emv_service.disconnect()
            self._cooperative_pause(1)

    def add_user_interactive(self) -> bool:
        """
        Interactive process to add a new user
        Returns True if user was added successfully
        """
        self._refresh_users_if_changed()

        print("\n--- Add New User ---")
        print("Place the new user's EMV card on the reader...")

        if not self.emv_service.wait_for_card():
            print("No card detected")
            return False

        try:
            scan_result = self.emv_service.read_card_data()
            identifier = scan_result.primary_identifier()
            identifier_type = scan_result.primary_identifier_type() or "Identifier"

            if not identifier:
                print("❌ Could not read card")
                return False

            masked_identifier = (
                identifier if len(identifier) <= 4 else f"****{identifier[-4:]}"
            )

            print(f"Card type (ATR-derived): {scan_result.card_type}")
            print(f"Tag type: {scan_result.tag_type}")
            print(
                f"Primary identifier ({identifier_type}): {identifier}"
                if identifier_type
                else f"Primary identifier: {identifier}"
            )
            if scan_result.uid and scan_result.uid != identifier:
                print(f"UID (raw): {scan_result.uid}")
            if scan_result.pan and scan_result.pan != identifier:
                print(f"PAN (raw): {scan_result.pan}")
            if scan_result.tokenized:
                print("⚠️ Tokenized/HCE card detected; identifier may change between taps.")

            # Check if user already exists
            existing_user = self.auth_service.authenticate_user(identifier)
            if existing_user:
                print(f"⚠️ User already exists: {existing_user.name}")
                return False

            # Get user details
            name = input("Enter user name: ").strip()
            if not name:
                print("❌ Name cannot be empty")
                return False

            access_level = (
                input("Enter access level (user/admin) [user]: ").strip() or "user"
            )
            if access_level not in ["user", "admin"]:
                print("❌ Invalid access level")
                return False

            # Add user
            if self.auth_service.add_user(identifier, name, access_level):
                print(f"✅ User {name} added successfully!")
                print(f"{identifier_type}: {masked_identifier}")
                print(f"Access Level: {access_level}")
                return True
            else:
                print("❌ Failed to add user")
                return False

        except Exception as e:
            print(f"Error adding user: {e}")
            return False
        finally:
            self.emv_service.disconnect()

    def show_system_status(self):
        """Display current system status"""
        self._refresh_users_if_changed()

        print("\n" + "=" * 50)
        print("📊 System Status")
        print("=" * 50)

        # Authentication service status
        total_users = self.auth_service.get_user_count()
        active_users = self.auth_service.get_active_user_count()
        print(f"👥 Users: {active_users}/{total_users} active")

        # Door service status
        door_status = self.door_service.get_door_status()
        status_icon = "🔓" if door_status["is_open"] else "🔒"
        print(f"{status_icon} Door: {'OPEN' if door_status['is_open'] else 'LOCKED'}")

        if door_status["last_user"]:
            print(f"👤 Last User: {door_status['last_user']}")

        print(f"⏱️ Auto-lock Delay: {door_status['auto_lock_delay']} seconds")

        # Show registered users
        users = self.auth_service.list_users()
        if users:
            print(f"\n📋 Registered Users:")
            for user in users.values():
                status = "✅" if user.active else "❌"
                primary = user.primary_identifier()
                if primary:
                    masked = primary.mask()
                    ident_info = f"{primary.type}: {masked}"
                else:
                    ident_info = "No identifiers"
                print(f"  {status} {user.name} ({user.access_level}) - {ident_info}")
                if len(user.identifiers) > 1:
                    for identifier in user.identifiers:
                        if identifier is primary:
                            continue
                        print(
                            f"     ↳ {identifier.type}: {identifier.mask()}"
                        )

    def run(self):
        """Main application loop"""
        print("🔧 Initializing Smart Door Lock System...")

        # Show initial status
        self.show_system_status()

        print("\n🎯 System ready! Waiting for cards...")

        self.running = True
        while self.running:
            try:
                if self._refresh_users_if_changed():
                    print("🔄 User database reloaded from disk.")

                if self.reader_control.get_owner() != "door":
                    if not self._reader_reserved:
                        print("🔌 Reader reserved by web UI; pausing door service scans.")
                        self._reader_reserved = True
                    self._cooperative_pause(1)
                    continue

                if self._reader_reserved:
                    print("✅ Reader ownership returned to door service; resuming scans.")
                    self._reader_reserved = False

                self.run_authentication_cycle()
            except KeyboardInterrupt:
                print("\n\n👋 Shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"Unexpected error: {e}")
                self._cooperative_pause(2)

    def stop(self):
        """Signal the controller loop to stop."""
        self.running = False
        with self._pause_condition:
            self._pause_condition.notify_all()

    def _refresh_users_if_changed(self, force: bool = False) -> bool:
        return self.auth_service.refresh_from_disk(force=force)

    def _cooperative_pause(self, duration: float) -> None:
        if duration <= 0:
            return
        with self._pause_condition:
            self._pause_condition.wait(timeout=duration)

    def run_management_mode(self):
        """Run in management mode for adding users, checking status, etc."""
        while True:
            print("\n" + "=" * 50)
            print("🛠️ Smart Door Lock - Management Mode")
            print("=" * 50)
            print("1. Add new user")
            print("2. Show system status")
            print("3. List all users")
            print("4. Exit")

            choice = input("\nSelect option (1-4): ").strip()

            if choice == "1":
                self.add_user_interactive()
            elif choice == "2":
                self.show_system_status()
            elif choice == "3":
                self._list_users_detailed()
            elif choice == "4":
                print("👋 Exiting management mode...")
                break
            else:
                print("❌ Invalid option")

    def _list_users_detailed(self):
        """Show detailed user list"""
        self._refresh_users_if_changed()

        users = self.auth_service.list_users()
        if not users:
            print("No users registered")
            return

        print(f"\n📋 All Users ({len(users)} total):")
        print("-" * 60)
        for user in users.values():
            status = "ACTIVE" if user.active else "INACTIVE"
            print(f"Name: {user.name}")
            if user.identifiers:
                for identifier in user.identifiers:
                    masked = identifier.mask()
                    marker = " (Primary)" if identifier.primary else ""
                    print(
                        f"Identifier [{identifier.type}]: {masked}{marker}"
                    )
            else:
                print("Identifier: (none)")
            print(f"Access Level: {user.access_level}")
            print(f"Status: {status}")
            print("-" * 60)


def _run_web_server(reader_control: ReaderControl, host: str, port: int, debug: bool) -> None:
    from app.web.server import create_app

    app = create_app(reader_control)
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smart Door Controller")
    parser.add_argument("--add-user", action="store_true", help="Interactively enroll a new user")
    parser.add_argument("--status", action="store_true", help="Print system status and exit")
    parser.add_argument("--manage", action="store_true", help="Enter interactive management menu")
    parser.add_argument(
        "--door-only",
        action="store_true",
        help="Run only the door controller loop (legacy behaviour)",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Run only the web management UI",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help="Run door controller and web UI together (default)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("USBUTLER_WEB_HOST", "0.0.0.0"),
        help="Host interface for the web UI (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("USBUTLER_WEB_PORT", "8000")),
        help="Port for the web UI (default: 8000)",
    )
    parser.add_argument(
        "--web-debug",
        action="store_true",
        help="Run the Flask development server in debug mode",
    )
    return parser.parse_args()


def main():
    """Main entry point"""
    args = _parse_args()

    mode_flags = [args.door_only, args.web_only, args.combined]
    if sum(1 for flag in mode_flags if flag) > 1:
        print("❌ Only one of --door-only, --web-only, or --combined may be specified.")
        sys.exit(2)

    shared_reader_control = ReaderControl()

    # Handle single-action commands first
    if args.add_user or args.status or args.manage:
        controller = SmartDoorLockController(shared_reader_control)
        if args.add_user:
            controller.add_user_interactive()
            return
        if args.status:
            controller.show_system_status()
            return
        controller.run_management_mode()
        return

    if args.web_only:
        print("🌐 Starting web UI (web-only mode)...")
        _run_web_server(shared_reader_control, args.host, args.port, args.web_debug)
        return

    controller = SmartDoorLockController(shared_reader_control)

    if args.door_only:
        controller.run()
        return

    # Default or explicit combined mode
    print("🔀 Starting door service and web UI (combined mode)...")
    door_thread = threading.Thread(target=controller.run, name="DoorController", daemon=True)
    door_thread.start()

    try:
        _run_web_server(shared_reader_control, args.host, args.port, args.web_debug)
    except KeyboardInterrupt:
        print("\n👋 Shutting down services...")
    finally:
        controller.stop()
        door_thread.join(timeout=5)


if __name__ == "__main__":
    main()
