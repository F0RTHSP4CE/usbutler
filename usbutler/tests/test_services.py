"""
Unit tests for the separated Smart Door Lock services.
Demonstrates how the separated architecture makes testing easier.
"""

import unittest
import tempfile
import os
import time
from unittest.mock import Mock, patch
from app.services.auth_service import AuthenticationService, User
from app.services.door_service import DoorControlService
from app.services.emv_service import EMVCardService


class TestAuthenticationService(unittest.TestCase):
    """Test the authentication service in isolation"""

    def setUp(self):
        # Create temporary file for testing with empty JSON object
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        )
        self.temp_file.write("{}")
        self.temp_file.close()
        self.auth_service = AuthenticationService(self.temp_file.name)

    def tearDown(self):
        # Clean up temp file
        os.unlink(self.temp_file.name)

    def test_add_user(self):
        """Test adding a new user"""
        result = self.auth_service.add_user("1234567890123456", "Test User", "admin")
        self.assertTrue(result)

        # Verify user was added
        user = self.auth_service.authenticate_user("1234567890123456")
        self.assertIsNotNone(user)
        if user:  # Type guard
            self.assertEqual(user.name, "Test User")
            self.assertEqual(user.access_level, "admin")

    def test_duplicate_user(self):
        """Test that duplicate users cannot be added"""
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        result = self.auth_service.add_user("1234567890123456", "Another User", "user")
        self.assertFalse(result)

    def test_authenticate_nonexistent_user(self):
        """Test authentication of non-existent user"""
        user = self.auth_service.authenticate_user("9999999999999999")
        self.assertIsNone(user)

    def test_deactivate_user(self):
        """Test user deactivation"""
        self.auth_service.add_user("1234567890123456", "Test User", "admin")

        # User should authenticate before deactivation
        user = self.auth_service.authenticate_user("1234567890123456")
        self.assertIsNotNone(user)

        # Deactivate user
        result = self.auth_service.deactivate_user("1234567890123456")
        self.assertTrue(result)

        # User should not authenticate after deactivation
        user = self.auth_service.authenticate_user("1234567890123456")
        self.assertIsNone(user)


class TestDoorControlService(unittest.TestCase):
    """Test the door control service in isolation"""

    def setUp(self):
        self.door_service = DoorControlService(
            auto_lock_delay=1
        )  # Short delay for testing
        self.test_user = User("1234567890123456", "Test User", "admin")

    def test_door_initial_state(self):
        """Test door starts in locked state"""
        self.assertFalse(self.door_service.is_open)

    def test_open_door(self):
        """Test opening the door"""
        event = self.door_service.open_door(self.test_user)
        self.assertTrue(self.door_service.is_open)
        self.assertEqual(event.user.name, "Test User")
        self.assertEqual(event.event_type, "open")

    def test_manual_lock_door(self):
        """Test manually locking the door"""
        self.door_service.open_door(self.test_user)
        self.assertTrue(self.door_service.is_open)

        event = self.door_service.lock_door(self.test_user)
        self.assertFalse(self.door_service.is_open)
        self.assertEqual(event.event_type, "close")

    def test_door_status(self):
        """Test getting door status"""
        status = self.door_service.get_door_status()
        self.assertIn("is_open", status)
        self.assertIn("auto_lock_delay", status)
        self.assertIn("last_user", status)

    def test_event_history(self):
        """Test event history tracking"""
        self.door_service.open_door(self.test_user)
        # Wait a moment for any threading to settle
        time.sleep(0.1)
        self.door_service.lock_door(self.test_user)

        events = self.door_service.get_recent_events(10)
        # Should have at least 2 events (open + close)
        # Auto-lock might create additional events
        self.assertGreaterEqual(len(events), 2)
        # Check that we have both open and close events
        event_types = [event.event_type for event in events]
        self.assertIn("open", event_types)
        self.assertIn("close", event_types)


class TestEMVCardService(unittest.TestCase):
    """Test the EMV card service in isolation"""

    def setUp(self):
        self.emv_service = EMVCardService()

    def test_read_card_pan_success(self):
        """Test successful PAN reading"""
        # Mock the dependencies
        with patch.object(
            self.emv_service.nfc_reader, "select_ppse"
        ) as mock_ppse, patch.object(
            self.emv_service.nfc_reader, "select_application"
        ) as mock_app, patch.object(
            self.emv_service.nfc_reader, "get_processing_options"
        ) as mock_gpo, patch.object(
            self.emv_service.emv_parser, "extract_pan_from_tlv"
        ) as mock_pan, patch.object(
            self.emv_service, "_extract_aid_from_ppse"
        ) as mock_aid:

            # Set up return values
            mock_ppse.return_value = b"\x6f\x1a\x84\x0e\x32\x50\x41\x59\x2e\x53\x59\x53\x2e\x44\x44\x46\x30\x31"
            mock_app.return_value = b"\x6f\x23\x84\x07\xa0\x00\x00\x00\x04\x10\x10"
            mock_gpo.return_value = b"\x80\x06\x00\x00\x10\x01\x01\x00"
            mock_pan.return_value = "4111111111111111"
            mock_aid.return_value = b"\xa0\x00\x00\x00\x04\x10\x10"

            result = self.emv_service.read_card_pan()
            self.assertEqual(result, "4111111111111111")

    def test_read_card_pan_no_ppse(self):
        """Test PAN reading when PPSE selection fails"""
        with patch.object(self.emv_service.nfc_reader, "select_ppse") as mock_ppse:
            mock_ppse.return_value = None
            result = self.emv_service.read_card_pan()
            self.assertIsNone(result)


class TestIntegration(unittest.TestCase):
    """Integration tests showing how services work together"""

    def setUp(self):
        # Create temporary file for auth service with empty JSON
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        )
        self.temp_file.write("{}")
        self.temp_file.close()

        self.auth_service = AuthenticationService(self.temp_file.name)
        self.door_service = DoorControlService(
            auto_lock_delay=0
        )  # No delay for testing

    def tearDown(self):
        os.unlink(self.temp_file.name)

    def test_complete_authentication_flow(self):
        """Test complete flow: add user, authenticate, open door"""
        # Step 1: Add user
        pan = "4111111111111111"
        self.auth_service.add_user(pan, "Test User", "admin")

        # Step 2: Authenticate user
        user = self.auth_service.authenticate_user(pan)
        self.assertIsNotNone(user)

        # Step 3: Open door for authenticated user
        if user:  # Type guard
            event = self.door_service.open_door(user)
            self.assertTrue(self.door_service.is_open)
            self.assertEqual(event.user.name, "Test User")

    def test_authentication_failure_flow(self):
        """Test flow when authentication fails"""
        # Try to authenticate non-existent user
        user = self.auth_service.authenticate_user("9999999999999999")
        self.assertIsNone(user)

        # Door should remain locked
        self.assertFalse(self.door_service.is_open)


if __name__ == "__main__":
    unittest.main()
