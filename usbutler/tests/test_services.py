"""
Unit tests for the separated Smart Door Lock services.
Demonstrates how the separated architecture makes testing easier.
"""

import unittest
import tempfile
import os
import time
from unittest.mock import Mock, patch
from urllib import parse
from app.services.auth_service import AuthenticationService, Identifier, User
from app.services.emv_service import is_mifare_like
from app.services.door_service import DoorControlService
try:
    from app.services.emv_service import CardScanResult, EMVCardService

    EMV_AVAILABLE = True
except ModuleNotFoundError as exc:
    EMV_AVAILABLE = False
    EMV_IMPORT_ERROR = exc
    CardScanResult = None  # type: ignore
    EMVCardService = None  # type: ignore


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
            primary = user.primary_identifier()
            self.assertIsNotNone(primary)
            if primary:
                self.assertEqual(primary.value, "1234567890123456")
                self.assertEqual(primary.type, "PAN")

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

    def test_multiple_identifiers_per_user(self):
        """Users can be linked to multiple identifiers."""
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        users = list(self.auth_service.list_users().values())
        self.assertEqual(len(users), 1)
        user = users[0]

        added = self.auth_service.add_identifier_to_user(user.user_id, "A1B2C3D4", "UID")
        self.assertTrue(added)

        refreshed = self.auth_service.get_user(user.user_id)
        self.assertIsNotNone(refreshed)
        if refreshed:
            identifiers = {identifier.value: identifier for identifier in refreshed.identifiers}
            self.assertIn("1234567890123456", identifiers)
            self.assertIn("A1B2C3D4", identifiers)
            self.assertTrue(identifiers["1234567890123456"].primary)
            self.assertFalse(identifiers["A1B2C3D4"].primary)

    def test_set_primary_identifier(self):
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        user = next(iter(self.auth_service.list_users().values()))
        self.auth_service.add_identifier_to_user(user.user_id, "A1B2C3D4", "UID")

        switched = self.auth_service.set_primary_identifier(user.user_id, "A1B2C3D4")
        self.assertTrue(switched)

        refreshed = self.auth_service.get_user(user.user_id)
        self.assertIsNotNone(refreshed)
        if refreshed:
            primaries = [identifier for identifier in refreshed.identifiers if identifier.primary]
            self.assertEqual(len(primaries), 1)
            self.assertEqual(primaries[0].value, "A1B2C3D4")

    def test_remove_identifier_removes_user_if_last(self):
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        user = next(iter(self.auth_service.list_users().values()))
        removed = self.auth_service.remove_identifier_from_user(user.user_id, "1234567890123456")
        self.assertTrue(removed)
        self.assertEqual(self.auth_service.get_user_count(), 0)

    def test_delete_user(self):
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        user = next(iter(self.auth_service.list_users().values()))
        result = self.auth_service.delete_user(user.user_id)
        self.assertTrue(result)
        self.assertEqual(self.auth_service.get_user_count(), 0)

    def test_refresh_from_disk_detects_external_changes(self):
        self.auth_service.add_user("1234567890123456", "Test User", "admin")
        # Ensure filesystem mtime differs on platforms with coarse resolution
        time.sleep(1.1)
        external = AuthenticationService(self.temp_file.name)
        external.add_user("9999999999999999", "Synced User", "user")

        reloaded = self.auth_service.refresh_from_disk()
        self.assertTrue(reloaded)
        refreshed = self.auth_service.authenticate_user("9999999999999999")
        self.assertIsNotNone(refreshed)


class TestDoorControlService(unittest.TestCase):
    """Test the door control service in isolation"""

    def setUp(self):
        self.pigpio_patcher = patch("app.services.door_service.pigpio")
        self.mock_pigpio = self.pigpio_patcher.start()
        self.mock_pigpio.OUTPUT = 1
        mock_pi = Mock()
        mock_pi.connected = True
        self.mock_pigpio.pi.return_value = mock_pi

        self.door_service = DoorControlService(
            auto_lock_delay=0.2
        )  # Short delay for testing
        self.test_user = User("1234567890123456", "Test User", "admin")
        self.test_user.add_identifier(Identifier("1234567890123456", "PAN", primary=True))

    def tearDown(self):
        self.pigpio_patcher.stop()

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
        # Wait for auto-lock timer to fire
        time.sleep(0.4)
        self.door_service.lock_door(self.test_user)

        events = self.door_service.get_recent_events(10)
        # Should have at least 2 events (open + close)
        # Auto-lock might create additional events
        self.assertGreaterEqual(len(events), 2)
        # Check that we have both open and close events
        event_types = [event.event_type for event in events]
        self.assertIn("open", event_types)
        self.assertIn("close", event_types)

    @patch("app.services.door_service.pigpio")
    def test_gpio_levels_toggle_with_active_high(self, pigpio_module):
        class StubPi:
            def __init__(self):
                self.connected = True
                self.modes = []
                self.writes = []

            def set_mode(self, pin, mode):
                self.modes.append((pin, mode))

            def write(self, pin, level):
                self.writes.append((pin, level))

        stub = StubPi()
        pigpio_module.pi.return_value = stub
        pigpio_module.OUTPUT = 1

        os.environ["USBUTLER_DOOR_GPIO"] = "22"
        os.environ["USBUTLER_DOOR_ACTIVE_HIGH"] = "1"

        service = DoorControlService(auto_lock_delay=0)
        service.open_door(self.test_user)
        service.lock_door(self.test_user)

        self.assertEqual(stub.modes[-1], (22, pigpio_module.OUTPUT))
        self.assertEqual(stub.writes, [(22, 0), (22, 1), (22, 0)])

        os.environ.pop("USBUTLER_DOOR_GPIO", None)
        os.environ.pop("USBUTLER_DOOR_ACTIVE_HIGH", None)

    @patch.dict(
        os.environ,
        {
            "USBUTLER_LED_ENDPOINT": "http://led.example/text",
            "USBUTLER_TG_BASE_URL": "https://api.telegram.org/botTEST/sendMessage",
            "USBUTLER_TG_CHAT_ID": "-1001234567890",
        },
        clear=False,
    )
    @patch("app.services.door_service.request.urlopen")
    def test_open_door_sends_notifications(self, mock_urlopen):
        mock_urlopen.return_value = Mock()

        with patch.object(self.door_service, "_notify_unlock") as mock_notify:
            event = self.door_service.open_door(self.test_user)

        mock_notify.assert_called_once_with(event)

        self.door_service._dispatch_unlock_notifications(event)

        self.assertEqual(mock_urlopen.call_count, 2)

        led_call = mock_urlopen.call_args_list[0]
        led_request = led_call.args[0]
        self.assertEqual(led_request.get_method(), "POST")
        self.assertIn("Welcome+Test+User", led_request.get_full_url())

        telegram_call = mock_urlopen.call_args_list[1]
        telegram_request = telegram_call.args[0]
        payload = telegram_request.data.decode("utf-8")
        self.assertIn("chat_id=-1001234567890", payload)
        self.assertIn("Test+User", payload)
        self.assertIn("****3456", parse.unquote_plus(payload))

    @patch.dict(os.environ, {"USBUTLER_DOOR_REOPEN_DELAY": "5"}, clear=False)
    def test_open_door_skips_within_cooldown(self):
        service = DoorControlService(auto_lock_delay=0)
        user = User("repeat-user", "Repeat User", "user")
        user.add_identifier(Identifier("REPEAT1234", "UID", primary=True))

        time_sequence = [0.0, 0.0, 0.1]

        def fake_time():
            return time_sequence.pop(0)

        with patch("app.services.door_service.time.time", side_effect=fake_time), patch.object(
            service, "_notify_unlock"
        ) as mock_notify:
            first_event = service.open_door(user)
            second_event = service.open_door(user)

        self.assertEqual(first_event.event_type, "open")
        self.assertEqual(second_event.event_type, "cooldown_skip")
        mock_notify.assert_called_once_with(first_event)
        self.assertEqual(
            service._last_open_by_identifier[user.primary_identifier().value], first_event.timestamp
        )
        self.assertIs(service.event_history[-1], second_event)


@unittest.skipUnless(EMV_AVAILABLE, "smartcard/pyscard dependency not available")
class TestEMVCardService(unittest.TestCase):
    """Test the EMV card service in isolation"""

    def setUp(self):
        self.mock_reader = Mock()
        self.mock_reader.is_connected.return_value = True
        self.emv_service = EMVCardService(nfc_reader=self.mock_reader)

    def test_read_card_pan_prefers_pan_identifier(self):
        scan = CardScanResult(
            pan="4111111111111111",
            expiry=None,
            issuer="Visa",
            tag_type="EMV",
            uid="A1B2C3D4",
            tokenized=False,
            atr_hex="",
            atr_hex_compact="",
            card_type="EMV Card",
            identifiers={
                "primary": {"type": "PAN", "value": "4111111111111111"},
                "secondary": {"type": "UID", "value": "A1B2C3D4"},
            },
        )

        with patch.object(self.emv_service, "read_card_data", return_value=scan):
            identifier = self.emv_service.read_card_pan()


            class TestEmvHelpers(unittest.TestCase):
                def test_is_mifare_like_recognises_emv(self):
                    self.assertFalse(
                        is_mifare_like(
                            None,
                            "EMV or ISO 14443-4 (e.g., DESFire)",
                        )
                    )
            self.assertEqual(identifier, "4111111111111111")
            self.assertEqual(self.emv_service.last_scan, scan)

    def test_read_card_pan_falls_back_to_uid(self):
        scan = CardScanResult(
            pan=None,
            expiry=None,
            issuer=None,
            tag_type="MIFARE Classic (likely)",
            uid="01020304",
            tokenized=False,
            atr_hex="",
            atr_hex_compact="",
            card_type="Mifare Classic 1K",
            identifiers={"primary": {"type": "UID", "value": "01020304"}},
        )

        with patch.object(self.emv_service, "read_card_data", return_value=scan):
            identifier = self.emv_service.read_card_pan()
            self.assertEqual(identifier, "01020304")

    def test_read_card_pan_returns_none_when_no_identifier(self):
        scan = CardScanResult(
            pan=None,
            expiry=None,
            issuer=None,
            tag_type="Unknown",
            uid=None,
            tokenized=False,
            atr_hex="",
            atr_hex_compact="",
            identifiers={},
        )

        with patch.object(self.emv_service, "read_card_data", return_value=scan):
            identifier = self.emv_service.read_card_pan()
            self.assertIsNone(identifier)

    def test_mifare_fast_path_skips_emv_probing(self):
        mifare_atr = [
            0x3B,
            0x8F,
            0x80,
            0x01,
            0x80,
            0x4F,
            0x0C,
            0xA0,
            0x00,
            0x00,
            0x03,
            0x06,
            0x03,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            0x6A,
        ]

        with patch.object(self.emv_service, "_get_atr_bytes", return_value=mifare_atr), patch.object(
            self.emv_service, "_get_uid", return_value="01020304"
        ), patch.object(
            self.emv_service,
            "_detect_contactless_tag_type",
            return_value=("MIFARE Classic (likely)", False),
        ) as detect_mock, patch.object(
            self.emv_service,
            "_select_name",
            side_effect=AssertionError("EMV probing should be skipped for MIFARE"),
        ):
            result = self.emv_service.read_card_data()

        detect_mock.assert_called_once()
        self.assertEqual(result.tag_type, "MIFARE Classic (likely)")
        self.assertEqual(result.primary_identifier(), "01020304")

    def test_iso14443_type4_skips_mifare_operations(self):
        iso_atr = [0x3B, 0x01, 0x80]

        with patch.object(
            self.emv_service, "_get_atr_bytes", return_value=iso_atr
        ), patch.object(
            self.emv_service, "_get_uid", return_value="DEADBEEF"
        ), patch.object(
            self.emv_service,
            "_transmit",
            return_value=(b"", 0x6A, 0x82),
        ), patch.object(
            self.emv_service,
            "_load_key_default",
            side_effect=AssertionError("MIFARE auth should be skipped for Type4"),
        ) as load_mock, patch.object(
            self.emv_service,
            "_mifare_classic_authenticate_block",
            side_effect=AssertionError("Classic auth should not run for Type4"),
        ) as auth_mock, patch.object(
            self.emv_service,
            "_read_block",
            side_effect=AssertionError("Block reads should be skipped for Type4"),
        ) as read_mock:
            result = self.emv_service.read_card_data()

        load_mock.assert_not_called()
        auth_mock.assert_not_called()
        read_mock.assert_not_called()
        self.assertEqual(result.tag_type, "Type4/ISO 14443-4 (UID only)")
        self.assertEqual(result.primary_identifier(), "DEADBEEF")
        self.assertEqual(
            result.identifiers.get("primary"), {"type": "UID", "value": "DEADBEEF"}
        )


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
