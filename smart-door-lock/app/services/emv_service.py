"""
EMV Card Service - Handles all EMV card reading operations.
Separated from business logic for better modularity and testing.
"""

from typing import Optional
from app.emv.emv_parser import EMVParser, EMVTags
from app.emv.nfc_reader import NFCReader


class EMVCardService:
    """Service for reading EMV cards and extracting PAN"""

    def __init__(self):
        self.nfc_reader = NFCReader()
        self.emv_parser = EMVParser()

    def wait_for_card(self, timeout: int = 10) -> bool:
        """Wait for an EMV card to be placed on reader"""
        return self.nfc_reader.wait_for_card(timeout=timeout)

    def get_card_info(self) -> Optional[str]:
        """Get basic card information (ATR)"""
        return self.nfc_reader.get_card_atr()

    def read_card_pan(self) -> Optional[str]:
        """
        Read EMV card and extract PAN
        Returns the PAN if successful, None otherwise
        """
        try:
            print("Reading EMV card...")

            # Step 1: SELECT PPSE
            ppse_response = self.nfc_reader.select_ppse()
            if not ppse_response:
                print("Failed to select PPSE")
                return None

            print(f"PPSE Response: {ppse_response.hex().upper()}")

            # Step 2: Extract AID from PPSE response
            aid = self._extract_aid_from_ppse(ppse_response)
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

            # Step 4: Extract PDOL and prepare data
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
            pan = self.emv_parser.extract_pan_from_tlv(all_data)
            if pan:
                print(f"✅ Extracted PAN: {pan}")
                return pan

            # Step 7: If no PAN found, try reading records
            print("PAN not found in initial responses, trying record reading...")
            pan = self._read_records_for_pan()
            if pan:
                print(f"✅ Extracted PAN from records: {pan}")
                return pan

            print("❌ Could not extract PAN from card")
            return None

        except Exception as e:
            print(f"Error reading EMV card: {e}")
            return None

    def disconnect(self):
        """Disconnect from the card reader"""
        self.nfc_reader.disconnect()

    def _extract_aid_from_ppse(self, ppse_response: bytes) -> Optional[bytes]:
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

    def _read_records_for_pan(self) -> Optional[str]:
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
