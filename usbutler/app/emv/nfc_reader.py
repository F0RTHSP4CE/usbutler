"""NFC Card Reader interface using PC/SC."""

import time
import threading
from typing import Optional, List, Tuple
from smartcard.System import readers
from smartcard.CardConnection import CardConnection
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.scard import SCARD_STATE_PRESENT


class NFCReader:
    def __init__(self):
        self.connection: Optional[CardConnection] = None
        self.reader = None
        self.reader_name: Optional[str] = None
        self._last_reader_snapshot: Optional[Tuple[str, ...]] = None
        self._io_lock = threading.RLock()
        self._pause_condition = threading.Condition()

    def disconnect(self):
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
        try:
            with self._io_lock:
                reader_list = readers()
                reader_names = tuple(str(r) for r in reader_list)
            if not reader_list:
                if self._last_reader_snapshot != ():
                    print("No card readers found")
                self._last_reader_snapshot = ()
                return False
            if self._last_reader_snapshot != reader_names:
                print(f"Found {len(reader_list)} reader(s)")
            self._last_reader_snapshot = reader_names
            return True
        except Exception as e:
            print(f"Error refreshing readers: {e}")
            return False

    def _connect_to_reader(self, reader) -> bool:
        try:
            with self._io_lock:
                conn = reader.createConnection()
                try:
                    conn.connect(CardConnection.T1_protocol)
                except:
                    try:
                        conn.connect(CardConnection.T0_protocol)
                    except:
                        conn.connect()
                self.connection = conn
                self.reader = reader
                self.reader_name = str(reader)
            print(f"Card detected on: {self.reader_name}")
            with self._pause_condition:
                self._pause_condition.notify_all()
            return True
        except (CardConnectionException, NoCardException):
            return False

    def _attempt_reconnect(self) -> bool:
        with self._io_lock:
            reader_list = readers()
        if self.reader_name:
            for r in reader_list:
                if str(r) == self.reader_name and self._connect_to_reader(r):
                    return True
        for r in reader_list:
            if str(r) != self.reader_name and self._connect_to_reader(r):
                return True
        return False

    def wait_for_card(self, timeout: int = 30) -> bool:
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                return False
            remaining = timeout - elapsed
            try:
                if not self._refresh_readers():
                    self._timed_pause(min(remaining, 0.05))
                    continue
                with self._io_lock:
                    reader_list = readers()
                for r in reader_list:
                    if self._connect_to_reader(r):
                        return True
            except (CardConnectionException, NoCardException):
                pass
            except Exception as e:
                print(f"Error waiting for card: {e}")
                self._timed_pause(min(remaining, 0.1))

    def wait_for_card_removal(self, timeout: int = 30) -> bool:
        start = time.monotonic()
        while True:
            if time.monotonic() - start >= timeout:
                return False
            with self._io_lock:
                conn = self.connection
            if conn is None:
                return True
            removed = False
            try:
                state, _, _ = conn.getStatus()  # type: ignore
                removed = not (state & SCARD_STATE_PRESENT)
            except:
                try:
                    removed = not conn.getATR()
                except:
                    removed = True
            if removed:
                self.disconnect()
                return True
            self._timed_pause(0.2)

    def is_connected(self) -> bool:
        return self.connection is not None

    def send_apdu(self, apdu: List[int]) -> Tuple[List[int], int, int]:
        if not self.connection:
            raise Exception("Not connected to card")
        for attempt in range(3):
            with self._io_lock:
                conn = self.connection
            if conn is None:
                if not self._attempt_reconnect():
                    self._timed_pause(0.02)
                    continue
                with self._io_lock:
                    conn = self.connection
                if conn is None:
                    self._timed_pause(0.02)
                    continue
            try:
                with self._io_lock:
                    return conn.transmit(apdu)
            except Exception as e:
                print(f"APDU error (attempt {attempt+1}): {e}")
                self.disconnect()
                self._timed_pause(0.02)
        raise Exception("APDU transmission failed after retries")

    def _timed_pause(self, duration: float):
        if duration > 0:
            with self._pause_condition:
                self._pause_condition.wait(timeout=duration)

    def select_ppse(self) -> Optional[bytes]:
        ppse = "2PAY.SYS.DDF01".encode("ascii")
        apdu = [0x00, 0xA4, 0x04, 0x00, len(ppse)] + list(ppse) + [0x00]
        try:
            response, sw1, sw2 = self.send_apdu(apdu)
            if sw1 == 0x90 and sw2 == 0x00:
                return bytes(response)
            return None
        except:
            return None

    def select_application(self, aid: bytes) -> Optional[bytes]:
        apdu = [0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid) + [0x00]
        try:
            response, sw1, sw2 = self.send_apdu(apdu)
            if sw1 == 0x90 and sw2 == 0x00:
                return bytes(response)
            return None
        except:
            return None

    def get_processing_options(self, pdol_data: bytes = b"") -> Optional[bytes]:
        if not pdol_data:
            apdu = [0x80, 0xA8, 0x00, 0x00, 0x02, 0x83, 0x00, 0x00]
        else:
            total_len = 2 + len(pdol_data)
            apdu = (
                [0x80, 0xA8, 0x00, 0x00, total_len, 0x83, len(pdol_data)]
                + list(pdol_data)
                + [0x00]
            )
        try:
            response, sw1, sw2 = self.send_apdu(apdu)
            if sw1 == 0x90 and sw2 == 0x00:
                return bytes(response)
            if sw1 == 0x6D and sw2 == 0x00 and pdol_data:
                response, sw1, sw2 = self.send_apdu(
                    [0x80, 0xA8, 0x00, 0x00, 0x02, 0x83, 0x00, 0x00]
                )
                if sw1 == 0x90 and sw2 == 0x00:
                    return bytes(response)
            return None
        except:
            return None

    def read_record(self, sfi: int, record: int) -> Optional[bytes]:
        apdu = [0x00, 0xB2, record, (sfi << 3) | 0x04, 0x00]
        try:
            response, sw1, sw2 = self.send_apdu(apdu)
            if sw1 == 0x90 and sw2 == 0x00:
                return bytes(response)
            return None
        except:
            return None

    def get_card_atr(self) -> Optional[str]:
        if self.connection:
            try:
                return toHexString(self.connection.getATR())
            except:
                pass
        return None
