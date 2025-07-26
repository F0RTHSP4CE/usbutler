"""
NFC Card Reader interface for ACR PC/SC USB readers.
Handles EMV card communication using PC/SC protocol.
"""

import time
from typing import Optional, List, Tuple
from smartcard.System import readers
from smartcard.CardConnection import CardConnection
from smartcard.util import toHexString, toBytes
from smartcard.Exceptions import CardConnectionException, NoCardException


class NFCReader:
    """NFC Card Reader for EMV cards using PC/SC"""

    def __init__(self):
        self.connection: Optional[CardConnection] = None
        self.reader = None

    def connect(self) -> bool:
        """Connect to the first available PC/SC reader"""
        try:
            reader_list = readers()
            if not reader_list:
                print("No PC/SC readers found")
                return False

            # Use the first available reader
            self.reader = reader_list[0]
            print(f"Found reader: {self.reader}")

            # Try to connect to a card
            self.connection = self.reader.createConnection()
            self.connection.connect()
            print("Connected to card")
            return True

        except Exception as e:
            print(f"Failed to connect to reader: {e}")
            return False

    def disconnect(self):
        """Disconnect from the card and reader"""
        if self.connection:
            try:
                self.connection.disconnect()
            except:
                pass
            self.connection = None

    def wait_for_card(self, timeout: int = 30) -> bool:
        """Wait for a card to be present"""
        print("Waiting for card...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                reader_list = readers()
                if reader_list:
                    self.reader = reader_list[0]
                    self.connection = self.reader.createConnection()
                    self.connection.connect()
                    print("Card detected!")
                    return True
            except (CardConnectionException, NoCardException):
                time.sleep(0.5)
                continue
            except Exception as e:
                print(f"Error waiting for card: {e}")
                time.sleep(0.5)
                continue

        print("Timeout waiting for card")
        return False

    def send_apdu(self, apdu: List[int]) -> Tuple[List[int], int, int]:
        """
        Send APDU command to the card
        Returns: (response_data, sw1, sw2)
        """
        if not self.connection:
            raise Exception("Not connected to card")

        try:
            response, sw1, sw2 = self.connection.transmit(apdu)
            return response, sw1, sw2
        except Exception as e:
            print(f"APDU transmission error: {e}")
            raise

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
