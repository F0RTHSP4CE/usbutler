"""
Smart Door Lock Controller - Orchestrates the separated services.
This is the main application logic that coordinates EMV reading, authentication, and door control.
"""

import time
import sys
from typing import Optional

from services.emv_service import EMVCardService
from services.auth_service import AuthenticationService
from services.door_service import DoorControlService


class SmartDoorLockController:
    """
    Main controller that orchestrates the smart door lock system.
    Coordinates between EMV reading, authentication, and door control services.
    """

    def __init__(self):
        # Initialize all services
        self.emv_service = EMVCardService()
        self.auth_service = AuthenticationService()
        self.door_service = DoorControlService()
        self.running = False

    def run_authentication_cycle(self) -> bool:
        """
        Run one complete authentication cycle
        Returns True if authentication was successful, False otherwise
        """
        print("\n" + "=" * 50)
        print("🚪 Smart Door Lock - Place EMV card on reader")
        print("=" * 50)

        # Step 1: Wait for card
        if not self.emv_service.wait_for_card(timeout=10):
            print("No card detected within timeout")
            return False

        try:
            # Step 2: Get card info (optional)
            atr = self.emv_service.get_card_info()
            if atr:
                print(f"Card ATR: {atr}")

            # Step 3: Read PAN from EMV card
            pan = self.emv_service.read_card_pan()
            if not pan:
                print("❌ Failed to read card data")
                return False

            # Step 4: Authenticate user
            user = self.auth_service.authenticate_user(pan)
            if not user:
                print("❌ Authentication failed - Unknown card")
                print(f"PAN: {pan}")
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
            time.sleep(1)  # Brief pause before next cycle

    def add_user_interactive(self) -> bool:
        """
        Interactive process to add a new user
        Returns True if user was added successfully
        """
        print("\n--- Add New User ---")
        print("Place the new user's EMV card on the reader...")

        if not self.emv_service.wait_for_card():
            print("No card detected")
            return False

        try:
            # Read PAN from card
            pan = self.emv_service.read_card_pan()
            if not pan:
                print("❌ Could not read card")
                return False

            # Check if user already exists
            existing_user = self.auth_service.authenticate_user(pan)
            if existing_user:
                print(f"⚠️ User already exists: {existing_user.name}")
                return False

            # Get user details
            name = input("Enter user name: ").strip()
            if not name:
                print("❌ Name cannot be empty")
                return False

            access_level = input("Enter access level (user/admin) [user]: ").strip() or "user"
            if access_level not in ["user", "admin"]:
                print("❌ Invalid access level")
                return False

            # Add user
            if self.auth_service.add_user(pan, name, access_level):
                print(f"✅ User {name} added successfully!")
                print(f"PAN: ****{pan[-4:]}")
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
            for pan, user in users.items():
                status = "✅" if user.active else "❌"
                print(f"  {status} {user.name} ({user.access_level}) - PAN: ****{pan[-4:]}")

    def run(self):
        """Main application loop"""
        print("🔧 Initializing Smart Door Lock System...")
        
        # Show initial status
        self.show_system_status()
        
        print("\n🎯 System ready! Waiting for cards...")

        self.running = True
        while self.running:
            try:
                self.run_authentication_cycle()
            except KeyboardInterrupt:
                print("\n\n👋 Shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"Unexpected error: {e}")
                time.sleep(2)

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
        users = self.auth_service.list_users()
        if not users:
            print("No users registered")
            return

        print(f"\n📋 All Users ({len(users)} total):")
        print("-" * 60)
        for pan, user in users.items():
            status = "ACTIVE" if user.active else "INACTIVE"
            print(f"Name: {user.name}")
            print(f"PAN: ****{pan[-4:]} (Full: {pan})")
            print(f"Access Level: {user.access_level}")
            print(f"Status: {status}")
            print("-" * 60)


def main():
    """Main entry point"""
    controller = SmartDoorLockController()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--add-user":
            controller.add_user_interactive()
        elif sys.argv[1] == "--status":
            controller.show_system_status()
        elif sys.argv[1] == "--manage":
            controller.run_management_mode()
        else:
            print("Usage: python smart_door_lock_controller.py [--add-user|--status|--manage]")
    else:
        controller.run()


if __name__ == "__main__":
    main()
