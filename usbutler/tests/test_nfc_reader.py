import unittest
from unittest.mock import MagicMock, patch

from smartcard.Exceptions import CardConnectionException, NoCardException

from app.emv.nfc_reader import NFCReader


class NFCReaderTests(unittest.TestCase):
    @patch("app.emv.nfc_reader.readers")
    def test_wait_for_card_checks_all_readers(self, mock_readers):
        reader_without_card = MagicMock(name="ReaderWithoutCard")
        connection_without_card = MagicMock()
        connection_without_card.connect.side_effect = NoCardException("No card present", 0)
        reader_without_card.createConnection.return_value = connection_without_card

        reader_with_card = MagicMock(name="ReaderWithCard")
        connection_with_card = MagicMock()
        connection_with_card.connect.return_value = None
        reader_with_card.createConnection.return_value = connection_with_card

        # Every call to readers() should return both readers.
        mock_readers.return_value = [reader_without_card, reader_with_card]

        nfc_reader = NFCReader()
        found = nfc_reader.wait_for_card(timeout=1)

        self.assertTrue(found)
        self.assertIs(nfc_reader.reader, reader_with_card)
        self.assertEqual(nfc_reader.reader_name, str(reader_with_card))

    @patch("app.emv.nfc_reader.readers")
    def test_send_apdu_reconnects_to_alternate_reader(self, mock_readers):
        # Existing reader/connection that will fail during transmit
        failing_reader = MagicMock(name="FailingReader")
        failing_connection = MagicMock()
        failing_connection.transmit.side_effect = CardConnectionException("Link failure")
        failing_connection.disconnect = MagicMock()

        # Alternate reader that succeeds
        alternate_reader = MagicMock(name="AlternateReader")
        alternate_connection = MagicMock()
        alternate_connection.connect.return_value = None
        alternate_connection.transmit.return_value = ([0x90], 0x90, 0x00)
        alternate_reader.createConnection.return_value = alternate_connection

        mock_readers.return_value = [alternate_reader]

        nfc_reader = NFCReader()
        nfc_reader.reader = failing_reader
        nfc_reader.reader_name = str(failing_reader)
        nfc_reader.connection = failing_connection

        response, sw1, sw2 = nfc_reader.send_apdu([0x00])

        self.assertEqual(response, [0x90])
        self.assertEqual(sw1, 0x90)
        self.assertEqual(sw2, 0x00)
        alternate_reader.createConnection.assert_called()
        self.assertIs(nfc_reader.connection, alternate_connection)
        self.assertIs(nfc_reader.reader, alternate_reader)
        self.assertEqual(nfc_reader.reader_name, str(alternate_reader))

    @patch("app.emv.nfc_reader.readers")
    def test_send_apdu_does_not_retry_with_missing_connection(self, mock_readers):
        reader = MagicMock(name="Reader")
        connection = MagicMock()
        connection.transmit.side_effect = CardConnectionException("No response")
        reader.createConnection.return_value = connection
        mock_readers.return_value = [reader]

        nfc_reader = NFCReader()
        nfc_reader.reader = reader
        nfc_reader.reader_name = str(reader)
        nfc_reader.connection = connection

        with patch.object(nfc_reader, "_attempt_reconnect", return_value=False), patch.object(
            nfc_reader, "_timed_pause", return_value=None
        ) as mock_pause:
            with self.assertRaises(Exception):
                nfc_reader.send_apdu([0x00])

        self.assertEqual(connection.transmit.call_count, 1)
        mock_pause.assert_called()


if __name__ == "__main__":
    unittest.main()
