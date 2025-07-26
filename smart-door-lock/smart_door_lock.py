"""
EMV Card Reader for Smart Door Lock Authentication
Reads EMV cards via ACR PC/SC NFC reader and extracts PAN for user authentication.
"""

import json
import time
from typing import Dict, List, Optional
from emv_parser import EMVParser, EMVTags
from nfc_reader import NFCReader


class UserDatabase:
    """Simple JSON-based user database"""

    def __init__(self, db_file: str = "users.json"):
        self.db_file = db_file
        self.users = self.load_users()

    def load_users(self) -> Dict[str, Dict]:
        """Load users from JSON file"""
        try:
            with open(self.db_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            # Create default users if file doesn't exist
            default_users = {
                "4111111111111111": {
                    "name": "John Doe",
                    "access_level": "admin",
                    "active": True,
                },
                "5555555555554444": {
                    "name": "Jane Smith",
                    "access_level": "user",
                    "active": True,
                },
            }
            self.save_users(default_users)
            return default_users

    def save_users(self, users: Dict[str, Dict]):
        """Save users to JSON file"""
        with open(self.db_file, "w") as f:
            json.dump(users, f, indent=2)

    def add_user(self, pan: str, name: str, access_level: str = "user"):
        """Add a new user"""
        self.users[pan] = {"name": name, "access_level": access_level, "active": True}
        self.save_users(self.users)

    def authenticate_user(self, pan: str) -> Optional[Dict]:
        """Authenticate user by PAN"""
        if pan in self.users and self.users[pan]["active"]:
            return self.users[pan]
        return None

    def list_users(self) -> Dict[str, Dict]:
        """List all users"""
        return self.users


class DoorLock:
    """Smart door lock controller"""

    def __init__(self):
        self.is_open = False
        self.auto_lock_delay = 5  # seconds

    def open_door(self, user_info: Dict):
        """Open the door for authenticated user"""
        print(f"🔓 DOOR OPENED for {user_info['name']} ({user_info['access_level']})")
        self.is_open = True

        # Auto-lock after delay
        print(f"Door will auto-lock in {self.auto_lock_delay} seconds...")
        time.sleep(self.auto_lock_delay)
        self.lock_door()

    def lock_door(self):
        """Lock the door"""
        print("🔒 DOOR LOCKED")
        self.is_open = False


class SmartDoorLock:
    """Main smart door lock application"""

    def __init__(self):
        self.nfc_reader = NFCReader()
        self.emv_parser = EMVParser()
        self.user_db = UserDatabase()
        self.door_lock = DoorLock()
        self.running = False

    def extract_aid_from_ppse(self, ppse_response: bytes) -> Optional[bytes]:
        """Extract first available AID from PPSE response"""
        try:
            parsed_data = self.emv_parser.decode_response_tlv(ppse_response)

            # Look for AID in the parsed data
            if EMVTags.AID in parsed_data:
                aid_hex = parsed_data[EMVTags.AID]
                if isinstance(aid_hex, str):
                    return bytes.fromhex(aid_hex)

            # Alternative: scan for 0x4F tag manually in raw data
            offset = 0
            while offset < len(ppse_response) - 2:
                if ppse_response[offset] == 0x4F:  # AID tag
                    aid_len = ppse_response[offset + 1]
                    if offset + 2 + aid_len <= len(ppse_response):
                        return ppse_response[offset + 2 : offset + 2 + aid_len]
                offset += 1

            print("No AID found in PPSE response")
            return None

        except Exception as e:
            print(f"Error extracting AID: {e}")
            return None

    def read_emv_card(self) -> Optional[str]:
        """
        Read EMV card and extract PAN
        Implements the EMV reading flow from unleashed firmware
        """
        try:
            print("\n--- Reading EMV Card ---")

            # Step 1: SELECT PPSE
            ppse_response = self.nfc_reader.select_ppse()
            if not ppse_response:
                print("Failed to select PPSE")
                return None

            print(f"PPSE Response: {ppse_response.hex().upper()}")

            # Step 2: Extract AID from PPSE response
            aid = self.extract_aid_from_ppse(ppse_response)
            if not aid:
                print("Could not extract AID from PPSE")
                return None

            print(f"Found AID: {aid.hex().upper()}")

            # Step 3: SELECT Application
            app_response = self.nfc_reader.select_application(aid)
            if not app_response:
                print("Failed to select application")
                return None

            print(f"Application Response: {app_response.hex().upper()}")

            # Step 4: Extract PDOL from application response and prepare data
            pdol = self.emv_parser.extract_pdol(app_response)
            if pdol:
                print(f"Found PDOL: {pdol.hex().upper()}")
                pdol_data = self.emv_parser.prepare_pdol_data(pdol)
                print(f"Prepared PDOL data: {pdol_data.hex().upper()}")
            else:
                print("No PDOL found, using empty data")
                pdol_data = b""

            # Step 5: GET PROCESSING OPTIONS
            gpo_response = self.nfc_reader.get_processing_options(pdol_data)
            if not gpo_response:
                print("Failed to get processing options")
                return None

            print(f"GPO Response: {gpo_response.hex().upper()}")

            # Step 6: Try to extract PAN from available responses
            all_data = ppse_response + app_response + gpo_response

            # Parse all TLV data and extract PAN
            pan = self.emv_parser.extract_pan_from_tlv(all_data)
            if pan:
                print(f"✅ Extracted PAN: {pan}")
                return pan

            # Step 7: If no PAN found, try reading records (AFL-based)
            print("PAN not found in initial responses, trying record reading...")
            pan = self.try_read_records()
            if pan:
                print(f"✅ Extracted PAN from records: {pan}")
                return pan

            print("❌ Could not extract PAN from card")
            return None

        except Exception as e:
            print(f"Error reading EMV card: {e}")
            return None

    def try_read_records(self) -> Optional[str]:
        """
        Try reading common SFI records to find PAN
        Based on emv_poller_read_afl implementation
        """
        # Try common SFI values (2, 3) with records 1-5
        for sfi in range(2, 4):
            for record in range(1, 6):
                try:
                    record_data = self.nfc_reader.read_record(sfi, record)
                    if record_data:
                        print(f"SFI {sfi} Record {record}: {record_data.hex().upper()}")

                        # Try to extract PAN from this record
                        pan = self.emv_parser.extract_pan_from_tlv(record_data)
                        if pan:
                            return pan

                except Exception as e:
                    print(f"Failed to read SFI {sfi} record {record}: {e}")
                    continue

        return None

    def authenticate_and_open(self, pan: str) -> bool:
        """Authenticate user and open door if valid"""
        print(f"\n--- Authentication ---")
        print(f"Checking PAN: {pan}")

        user_info = self.user_db.authenticate_user(pan)
        if user_info:
            print(f"✅ Authentication successful!")
            print(f"Welcome, {user_info['name']}!")
            self.door_lock.open_door(user_info)
            return True
        else:
            print("❌ Authentication failed - Unknown card")
            return False

    def run_once(self) -> bool:
        """Run one authentication cycle"""
        print("\n" + "=" * 50)
        print("🚪 Smart Door Lock - Place EMV card on reader")
        print("=" * 50)

        # Wait for card
        if not self.nfc_reader.wait_for_card(timeout=10):
            return False

        try:
            # Show card info
            atr = self.nfc_reader.get_card_atr()
            if atr:
                print(f"Card ATR: {atr}")

            # Read and extract PAN
            pan = self.read_emv_card()
            if pan:
                # Authenticate and open door
                return self.authenticate_and_open(pan)
            else:
                print("❌ Failed to read card data")
                return False

        except Exception as e:
            print(f"Error during card processing: {e}")
            return False
        finally:
            # Always disconnect
            self.nfc_reader.disconnect()
            time.sleep(1)  # Brief pause before next cycle

    def run(self):
        """Main application loop"""
        print("🔧 Initializing Smart Door Lock System...")

        # Show registered users
        users = self.user_db.list_users()
        print(f"\n📋 Registered Users ({len(users)}):")
        for pan, info in users.items():
            print(f"  • {info['name']} ({info['access_level']}) - PAN: ****{pan[-4:]}")

        print("\n🎯 System ready! Waiting for cards...")

        self.running = True
        while self.running:
            try:
                self.run_once()
            except KeyboardInterrupt:
                print("\n\n👋 Shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"Unexpected error: {e}")
                time.sleep(2)

    def add_user_interactive(self):
        """Interactive user addition"""
        print("\n--- Add New User ---")

        print("Place the new user's EMV card on the reader...")
        if not self.nfc_reader.wait_for_card():
            print("No card detected")
            return

        try:
            pan = self.read_emv_card()
            if pan:
                name = input("Enter user name: ").strip()
                access_level = (
                    input("Enter access level (user/admin) [user]: ").strip() or "user"
                )

                self.user_db.add_user(pan, name, access_level)
                print(f"✅ User {name} added successfully!")
            else:
                print("❌ Could not read card")
        except Exception as e:
            print(f"Error adding user: {e}")
        finally:
            self.nfc_reader.disconnect()


def main():
    """Main entry point"""
    import sys

    app = SmartDoorLock()

    if len(sys.argv) > 1 and sys.argv[1] == "--add-user":
        app.add_user_interactive()
    else:
        app.run()


if __name__ == "__main__":
    main()
