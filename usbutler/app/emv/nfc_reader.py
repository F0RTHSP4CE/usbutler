"""
NFC Card Reader interface for ACR PC/SC USB readers.
Handles EMV card communication using PC/SC protocol.
"""

import time
import threading
from typing import Optional, List, Tuple

from smartcard.System import readers
from smartcard.CardConnection import CardConnection
from smartcard.util import toHexString, toBytes
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.scard import SCARD_STATE_PRESENT


class NFCReader:
    """NFC Card Reader for EMV cards using PC/SC"""

    def __init__(self):
        self.connection: Optional[CardConnection] = None
        self.reader = None
        self.reader_name: Optional[str] = None
        self._last_reader_snapshot: Optional[Tuple[str, ...]] = None
        self._io_lock = threading.RLock()
        self._pause_condition = threading.Condition()

    def disconnect(self):
        """Disconnect from the card and reader"""
        with self._io_lock:
            if self.connection:
                try:
                    self.connection.disconnect()
                except:
                    pass
                self.connection = None
            self.reader = None
            self.reader_name = None
        with self._pause_condition:
            self._pause_condition.notify_all()

    def _refresh_readers(self) -> bool:
        """Refresh the reader list and check for available readers"""
        try:
            with self._io_lock:
                reader_list = readers()
                reader_names = tuple(str(reader) for reader in reader_list)

            if not reader_list:
                if self._last_reader_snapshot != ():
                    print("No card readers found. Make sure the USB card reader is connected.")
                self._last_reader_snapshot = ()
                return False

            if self._last_reader_snapshot != reader_names:
                print(f"Found {len(reader_list)} reader(s):")
                for i, reader in enumerate(reader_list):
                    print(f"  {i}: {reader}")

            self._last_reader_snapshot = reader_names
            return True
        except Exception as e:
            print(f"Error refreshing readers: {e}")
            return False

    def _connect_to_reader(self, reader) -> bool:
        """Attempt to connect to the provided reader. Returns True when a card is present."""
        try:
            with self._io_lock:
                connection = reader.createConnection()
                try:
                    connection.connect(CardConnection.T1_protocol)
                except Exception:
                    try:
                        connection.connect(CardConnection.T0_protocol)
                    except Exception:
                        connection.connect()

                self.connection = connection
                self.reader = reader
                self.reader_name = str(reader)
            print(f"Card detected on reader: {self.reader_name}")
            with self._pause_condition:
                self._pause_condition.notify_all()
            return True
        except (CardConnectionException, NoCardException):
            return False

    def _attempt_reconnect(self) -> bool:
        """Try to re-establish a connection after a transient failure."""
        with self._io_lock:
            reader_list = readers()

        # Prefer the previously used reader if we know its name.
        if self.reader_name:
            for reader in reader_list:
                if str(reader) == self.reader_name and self._connect_to_reader(reader):
                    return True

        # Fallback to any available reader.
        for reader in reader_list:
            if str(reader) == self.reader_name:
                continue
            if self._connect_to_reader(reader):
                return True

        return False

    def wait_for_card(self, timeout: int = 30) -> bool:
        """Wait for a card to be present"""
        print("Waiting for card...")
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                print("Timeout waiting for card")
                return False
            remaining = timeout - elapsed
            try:
                # Refresh readers list each time to detect reconnected devices
                if not self._refresh_readers():
                    self._timed_pause(min(remaining, 1.0))
                    continue

                with self._io_lock:
                    reader_list = readers()
                for reader in reader_list:
                    if self._connect_to_reader(reader):
                        return True
            except (CardConnectionException, NoCardException):
                # Reader found but no card present
                self._timed_pause(min(remaining, 0.5))
                continue
            except Exception as e:
                print(f"Error waiting for card: {e}")
                print("This might indicate the USB card reader was disconnected.")
                self._timed_pause(min(remaining, 2.0))
                continue

    def wait_for_card_removal(self, timeout: int = 30) -> bool:
        """Wait until the currently connected card is removed."""
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                return False

            with self._io_lock:
                connection = self.connection

            if connection is None:
                return True

            if hasattr(connection, "wait_for_card_remove"):
                try:
                    connection.wait_for_card_remove()
                except Exception:
                    pass

            removed = False
            try:
                state, _protocol, _atr = connection.getStatus()
                removed = not (state & SCARD_STATE_PRESENT)
            except Exception:
                try:
                    atr = connection.getATR()
                    removed = not atr
                except Exception:
                    removed = True

            if removed:
                self.disconnect()
                return True

            self._timed_pause(0.2)

    def is_connected(self) -> bool:
        """Check if we have an active connection to a card"""
        return self.connection is not None

    def send_apdu(self, apdu: List[int]) -> Tuple[List[int], int, int]:
        """
        Send APDU command to the card
        Returns: (response_data, sw1, sw2)
        """
        if not self.connection:
            raise Exception("Not connected to card")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            with self._io_lock:
                connection = self.connection

            if connection is None:
                if not self._attempt_reconnect():
                    print("Failed to reconnect after APDU error: no readers available")
                    if attempt == max_retries:
                        raise Exception("APDU transmission failed: connection unavailable")
                    self._timed_pause(0.1)
                    continue

                with self._io_lock:
                    connection = self.connection

                if connection is None:
                    if attempt == max_retries:
                        raise Exception("APDU transmission failed: connection unavailable")
                    self._timed_pause(0.1)
                    continue

            try:
                with self._io_lock:
                    response, sw1, sw2 = connection.transmit(apdu)
                return response, sw1, sw2

            except CardConnectionException as e:
                # Transient transport/protocol error - try to reconnect and retry
                print(f"APDU transmission error (attempt {attempt}): {e}")
                # Disconnect and attempt to re-establish connection
                self.disconnect()
                self._timed_pause(0.05)
                continue

            except Exception as e:
                # Non-CardConnectionException - treat as fatal after retries
                print(f"APDU transmission error (attempt {attempt}): {e}")
                self.disconnect()
                if attempt == max_retries:
                    raise
                self._timed_pause(0.1)
                continue

        # If we get here, all retries failed
        raise Exception("APDU transmission failed after retries")

    def _timed_pause(self, duration: float):
        if duration <= 0:
            return
        with self._pause_condition:
            self._pause_condition.wait(timeout=duration)

    def select_ppse(self) -> Optional[bytes]:
        """
        SELECT PPSE (Payment System Environment)
        Based on emv_poller_select_ppse implementation
        """
        # SELECT PPSE APDU: 00 A4 04 00 0E 325041592E5359532E4444463031 00
        ppse_name = "2PAY.SYS.DDF01"  # PPSE application name
        ppse_bytes = ppse_name.encode("ascii")

        apdu = [0x00, 0xA4, 0x04, 0x00, len(ppse_bytes)] + list(ppse_bytes) + [0x00]

        try:
            response, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x90 and sw2 == 0x00:
                print("SELECT PPSE successful")
                return bytes(response)
            else:
                print(f"SELECT PPSE failed: {sw1:02X} {sw2:02X}")
                return None

        except Exception as e:
            print(f"SELECT PPSE error: {e}")
            return None

    def select_application(self, aid: bytes) -> Optional[bytes]:
        """
        SELECT application by AID
        Based on emv_poller_select_application implementation
        """
        # SELECT application APDU: 00 A4 04 00 [AID_LEN] [AID] 00
        apdu = [0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid) + [0x00]

        try:
            response, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x90 and sw2 == 0x00:
                print(f"SELECT application successful: {aid.hex().upper()}")
                return bytes(response)
            else:
                print(f"SELECT application failed: {sw1:02X} {sw2:02X}")
                return None

        except Exception as e:
            print(f"SELECT application error: {e}")
            return None

    def get_processing_options(self, pdol_data: bytes = b"") -> Optional[bytes]:
        """
        GET PROCESSING OPTIONS command
        Based on emv_poller_get_processing_options implementation
        """
        # GPO APDU: 80 A8 00 00 [LEN] 83 [PDOL_LEN] [PDOL_DATA] 00
        # If no PDOL data, send minimal command with empty PDOL
        if not pdol_data:
            # Empty PDOL: 80 A8 00 00 02 83 00 00
            apdu = [0x80, 0xA8, 0x00, 0x00, 0x02, 0x83, 0x00, 0x00]
        else:
            pdol_len = len(pdol_data)
            total_len = 2 + pdol_len  # 0x83 + pdol_len + pdol_data
            apdu = (
                [0x80, 0xA8, 0x00, 0x00, total_len, 0x83, pdol_len]
                + list(pdol_data)
                + [0x00]
            )

        try:
            response, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x90 and sw2 == 0x00:
                print("GET PROCESSING OPTIONS successful")
                return bytes(response)
            else:
                print(f"GET PROCESSING OPTIONS failed: {sw1:02X} {sw2:02X}")

                # If card says INS not supported (6D00), try with empty PDOL as fallback
                if sw1 == 0x6D and sw2 == 0x00 and pdol_data:
                    print("Card returned 6D00 for GPO with PDOL - trying empty PDOL fallback")
                    try:
                        empty_apdu = [0x80, 0xA8, 0x00, 0x00, 0x02, 0x83, 0x00, 0x00]
                        response2, sw1b, sw2b = self.send_apdu(empty_apdu)
                        if sw1b == 0x90 and sw2b == 0x00:
                            print("GET PROCESSING OPTIONS successful with empty PDOL")
                            return bytes(response2)
                        else:
                            print(f"Fallback GPO failed: {sw1b:02X} {sw2b:02X}")
                            return None
                    except Exception as e2:
                        print(f"Fallback GPO error: {e2}")
                        return None

                return None

        except Exception as e:
            print(f"GET PROCESSING OPTIONS error: {e}")
            return None

    def read_record(self, sfi: int, record: int) -> Optional[bytes]:
        """
        READ RECORD command for reading application data
        Based on emv_poller_read_sfi_record implementation
        """
        # READ RECORD APDU: 00 B2 [RECORD] [SFI<<3|0x04] 00
        p2 = (sfi << 3) | 0x04
        apdu = [0x00, 0xB2, record, p2, 0x00]

        try:
            response, sw1, sw2 = self.send_apdu(apdu)

            if sw1 == 0x90 and sw2 == 0x00:
                print(f"READ RECORD SFI {sfi:02X} record {record} successful")
                return bytes(response)
            else:
                print(f"READ RECORD failed: {sw1:02X} {sw2:02X}")
                return None

        except Exception as e:
            print(f"READ RECORD error: {e}")
            return None

    def get_card_atr(self) -> Optional[str]:
        """Get the card's Answer To Reset (ATR)"""
        if self.connection:
            try:
                atr = self.connection.getATR()
                return toHexString(atr)
            except:
                return None
        return None
