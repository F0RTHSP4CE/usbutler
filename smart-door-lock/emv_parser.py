"""
EMV TLV Parser for extracting card data from EMV payment cards.
Based on the Unleashed Firmware EMV implementation.
"""

import struct
from typing import Dict, Optional, Tuple, List, Any


# EMV Tag definitions (from emv.h)
class EMVTags:
    # Card Information
    PAN = 0x5A
    CARDHOLDER_NAME = 0x5F20
    EXP_DATE = 0x5F24

    # Track Data
    TRACK_1_EQUIV = 0x56
    TRACK_2_EQUIV = 0x57
    TRACK_2_DATA = 0x9F6B

    # Application Data
    AID = 0x4F
    APPL_LABEL = 0x50
    APPL_NAME = 0x9F12
    APPL_INTERCHANGE_PROFILE = 0x82

    # Processing Data
    PDOL = 0x9F38
    AFL = 0x94
    GPO_FMT1 = 0x80

    # Transaction Data
    LOG_ENTRY = 0x9F4D
    LOG_FMT = 0x9F4F
    ATC = 0x9F36
    LOG_AMOUNT = 0x9F02
    LOG_DATE = 0x9A
    LOG_TIME = 0x9F21
    LOG_COUNTRY = 0x9F1A
    LOG_CURRENCY = 0x5F2A

    # Security Data
    PIN_TRY_COUNTER = 0x9F17
    LAST_ONLINE_ATC = 0x9F13

    # Additional tags
    PRIORITY = 0x87
    APPL_EFFECTIVE = 0x5F25
    COUNTRY_CODE = 0x5F28
    CURRENCY_CODE = 0x9F42


# Default PDOL values (matching Flipper implementation exactly)
PDOL_DEFAULT_VALUES = {
    0x9F59: bytes([0xC8, 0x80, 0x00]),  # Terminal transaction information
    0x9F5A: bytes([0x00]),  # Terminal transaction type
    0x9F58: bytes([0x01]),  # Merchant type indicator
    0x9F66: bytes([0x79, 0x00, 0x40, 0x80]),  # Terminal transaction qualifiers
    0x9F40: bytes([0x79, 0x00, 0x40, 0x80]),  # Additional terminal qualifiers
    0x9F02: bytes([0x00, 0x00, 0x00, 0x10, 0x00, 0x00]),  # Amount, authorised
    0x9F03: bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # Amount, other
    0x9F1A: bytes([0x01, 0x24]),  # Terminal country code
    0x9F1D: bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # Terminal risk management data
    0x5F2A: bytes([0x01, 0x24]),  # Transaction currency code
    0x95: bytes([0x00, 0x00, 0x00, 0x00, 0x00]),  # Terminal verification results
    0x9A: bytes([0x19, 0x01, 0x01]),  # Transaction date
    0x9C: bytes([0x00]),  # Transaction type
    0x98: bytes([0x00] * 20),  # Transaction certificate
    0x9F37: bytes([0x82, 0x3D, 0xDE, 0x7A]),  # Unpredictable number
}


class EMVParser:
    """EMV TLV parser based on Unleashed Firmware implementation"""

    def __init__(self):
        self.extracted_data = {}

    def parse_tag(self, data: bytes, offset: int) -> Tuple[int, int, int]:
        """
        Parse TLV tag and length (emv_parse_tag implementation)
        Returns: (tag, length, new_offset)
        """
        if offset >= len(data):
            return 0, 0, offset

        first_byte = data[offset]
        tag_offset = offset

        # Parse tag (1 or 2 bytes)
        if (first_byte & 0x1F) == 0x1F:  # 2-byte tag
            if offset + 1 >= len(data):
                return 0, 0, offset
            tag = (data[offset] << 8) | data[offset + 1]
            tag_offset += 2
        else:  # 1-byte tag
            tag = data[offset]
            tag_offset += 1

        if tag_offset >= len(data):
            return tag, 0, tag_offset

        # Parse length (1 or 2 bytes)
        length_byte = data[tag_offset]
        if (length_byte & 0x80) == 0x80:  # Long form length
            if tag_offset + 1 >= len(data):
                return tag, 0, tag_offset + 1
            length = data[tag_offset + 1]
            tag_offset += 2
        else:  # Short form length
            length = length_byte
            tag_offset += 1

        return tag, length, tag_offset

    def decode_tlv_tag(self, data: bytes, tag: int, length: int) -> Any:
        """
        Decode specific EMV tag data (emv_decode_tlv_tag implementation)
        """
        if length == 0 or len(data) < length:
            return None

        try:
            if tag == EMVTags.PAN:
                # Primary Account Number
                return data[:length].hex().upper()

            elif tag == EMVTags.CARDHOLDER_NAME:
                # Cardholder name with space termination
                name = data[:length].decode("ascii", errors="ignore").rstrip("\x00")
                # Use space as terminator
                space_pos = name.find(" ")
                if space_pos > 0:
                    name = name[:space_pos]
                return name

            elif tag == EMVTags.EXP_DATE:
                # Expiration date (YYMMDD or YYMM)
                if length >= 2:
                    year = data[0]
                    month = data[1]
                    day = data[2] if length > 2 else 0
                    return f"20{year:02d}-{month:02d}" + (f"-{day:02d}" if day else "")

            elif tag in [EMVTags.TRACK_2_EQUIV, EMVTags.TRACK_2_DATA]:
                # Track 2 data parsing
                return self.parse_track2_data(data[:length])

            elif tag == EMVTags.TRACK_1_EQUIV:
                # Track 1 equivalent data
                return data[:length].decode("ascii", errors="ignore")

            elif tag == EMVTags.AID:
                # Application Identifier
                return data[:length].hex().upper()

            elif tag in [EMVTags.APPL_LABEL, EMVTags.APPL_NAME]:
                # Application label/name
                return data[:length].decode("ascii", errors="ignore").rstrip("\x00")

            elif tag == EMVTags.CURRENCY_CODE:
                # Currency code (2 bytes)
                if length >= 2:
                    return (data[0] << 8) | data[1]

            elif tag == EMVTags.COUNTRY_CODE:
                # Country code (2 bytes)
                if length >= 2:
                    return (data[0] << 8) | data[1]

            elif tag == EMVTags.PIN_TRY_COUNTER:
                # PIN try counter
                return data[0] if length > 0 else 0

            elif tag == EMVTags.ATC:
                # Application Transaction Counter
                if length >= 2:
                    return (data[0] << 8) | data[1]

            elif tag == EMVTags.PDOL:
                # Processing Options Data Object List - return as raw bytes
                return data[:length]

            else:
                # Unknown tag - return raw hex
                return data[:length].hex().upper()

        except Exception as e:
            print(f"Error decoding tag 0x{tag:04X}: {e}")
            return data[:length].hex().upper()

    def parse_track2_data(self, data: bytes) -> Dict[str, Any]:
        """
        Parse Track 2 equivalent data (special handling from emv_decode_tlv_tag)
        """
        result = {}

        # Convert to hex string for easier processing
        hex_data = data.hex().upper()

        # Look for 'D' delimiter (0xD0 in BCD becomes 'D' in hex)
        delimiter_pos = hex_data.find("D")
        if delimiter_pos > 0:
            # Extract PAN (before delimiter)
            pan_hex = hex_data[:delimiter_pos]
            result["pan"] = pan_hex

            # Extract expiry date (4 digits after delimiter: YYMM)
            if len(hex_data) > delimiter_pos + 4:
                exp_data = hex_data[delimiter_pos + 1 : delimiter_pos + 5]
                year = int(exp_data[:2])
                month = int(exp_data[2:4])
                result["expiry"] = f"20{year:02d}-{month:02d}"

        # Also store the full track data
        result["track2_equiv"] = hex_data

        return result

    def decode_response_tlv(self, data: bytes) -> Dict[int, Any]:
        """
        Recursive TLV parser (emv_decode_response_tlv implementation)
        """
        result = {}
        offset = 0

        while offset < len(data):
            if offset >= len(data):
                break

            first_byte = data[offset]
            tag, length, new_offset = self.parse_tag(data, offset)

            if tag == 0 or new_offset >= len(data):
                break

            # Check if constructed (contains nested TLV)
            if (first_byte & 0x20) == 0x20:
                # Constructed - recursively parse nested TLV
                if new_offset + length <= len(data):
                    nested_data = data[new_offset : new_offset + length]
                    nested_result = self.decode_response_tlv(nested_data)
                    result.update(nested_result)
            else:
                # Primitive - decode the tag data
                if new_offset + length <= len(data):
                    tag_data = data[new_offset : new_offset + length]
                    decoded_value = self.decode_tlv_tag(tag_data, tag, length)
                    if decoded_value is not None:
                        result[tag] = decoded_value

            offset = new_offset + length

        return result

    def extract_pan_from_tlv(self, tlv_data: bytes) -> Optional[str]:
        """
        Extract PAN from TLV data with multiple fallback methods
        """
        parsed_data = self.decode_response_tlv(tlv_data)

        # Method 1: Direct PAN tag
        if EMVTags.PAN in parsed_data:
            pan = parsed_data[EMVTags.PAN]
            if isinstance(pan, str):
                # Remove any 'F' padding
                return pan.rstrip("F")

        # Method 2: Track 2 equivalent data
        if EMVTags.TRACK_2_EQUIV in parsed_data:
            track2_data = parsed_data[EMVTags.TRACK_2_EQUIV]
            if isinstance(track2_data, dict) and "pan" in track2_data:
                return track2_data["pan"].rstrip("F")

        # Method 3: Track 2 data
        if EMVTags.TRACK_2_DATA in parsed_data:
            track2_data = parsed_data[EMVTags.TRACK_2_DATA]
            if isinstance(track2_data, dict) and "pan" in track2_data:
                return track2_data["pan"].rstrip("F")

        return None

    def parse_emv_response(self, response_data: bytes) -> Dict[str, Any]:
        """
        Parse complete EMV response and extract all available data
        """
        self.extracted_data = self.decode_response_tlv(response_data)

        # Convert tag numbers to readable format
        readable_data = {}

        for tag, value in self.extracted_data.items():
            tag_name = self.get_tag_name(tag)
            readable_data[tag_name] = value

        return readable_data

    def get_tag_name(self, tag: int) -> str:
        """Convert tag number to readable name"""
        tag_names = {
            EMVTags.PAN: "PAN",
            EMVTags.CARDHOLDER_NAME: "Cardholder_Name",
            EMVTags.EXP_DATE: "Expiration_Date",
            EMVTags.TRACK_1_EQUIV: "Track1_Equivalent",
            EMVTags.TRACK_2_EQUIV: "Track2_Equivalent",
            EMVTags.TRACK_2_DATA: "Track2_Data",
            EMVTags.AID: "Application_ID",
            EMVTags.APPL_LABEL: "Application_Label",
            EMVTags.APPL_NAME: "Application_Name",
            EMVTags.CURRENCY_CODE: "Currency_Code",
            EMVTags.COUNTRY_CODE: "Country_Code",
            EMVTags.PIN_TRY_COUNTER: "PIN_Try_Counter",
            EMVTags.ATC: "Transaction_Counter",
        }

        return tag_names.get(tag, f"Tag_0x{tag:04X}")

    def extract_pdol(self, tlv_data: bytes) -> bytes:
        """Extract PDOL from TLV response data"""
        parsed = self.decode_response_tlv(tlv_data)
        if EMVTags.PDOL in parsed:
            pdol_data = parsed[EMVTags.PDOL]
            if isinstance(pdol_data, str):
                # Convert hex string back to bytes
                return bytes.fromhex(pdol_data)
            elif isinstance(pdol_data, bytes):
                return pdol_data
        return b""

    def prepare_pdol_data(self, pdol: bytes) -> bytes:
        """
        Prepare PDOL data for GET PROCESSING OPTIONS command
        Based on emv_prepare_pdol implementation from C code
        
        PDOL format: tag1 length1 tag2 length2 ...
        We need to prepare data values for each tag/length pair
        """
        if not pdol:
            return b""

        result = b""
        offset = 0

        print(f"DEBUG: PDOL bytes: {pdol.hex().upper()}")

        while offset < len(pdol):
            if offset >= len(pdol):
                break
                
            # Parse tag manually for PDOL structure
            first_byte = pdol[offset]
            
            # Check if 2-byte tag
            if (first_byte & 0x1F) == 0x1F:  # 2-byte tag
                if offset + 1 >= len(pdol):
                    break
                tag = (pdol[offset] << 8) | pdol[offset + 1]
                offset += 2
            else:  # 1-byte tag
                tag = pdol[offset]
                offset += 1
            
            # Get data length (next byte)
            if offset >= len(pdol):
                break
            data_length = pdol[offset]
            offset += 1
            
            print(f"DEBUG: Tag: 0x{tag:04X}, Length: {data_length}")

            # Find matching value in our defaults
            if tag in PDOL_DEFAULT_VALUES:
                value = PDOL_DEFAULT_VALUES[tag]
                # Truncate or pad to required length
                if len(value) >= data_length:
                    result += value[:data_length]
                else:
                    result += value + b"\x00" * (data_length - len(value))
                print(f"DEBUG: Added {len(value[:data_length])} bytes for tag 0x{tag:04X}")
            else:
                # Unknown tag, fill with zeros
                result += b"\x00" * data_length
                print(f"DEBUG: Added {data_length} zero bytes for unknown tag 0x{tag:04X}")

        print(f"DEBUG: Final PDOL data length: {len(result)}")
        return result
