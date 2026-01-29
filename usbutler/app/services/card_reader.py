"""Card reader service for NFC cards - extracts PAN or UID."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from smartcard.util import toHexString

from app.emv.nfc_reader import NFCReader

# Known Mifare/NTAG ATR prefixes (contactless-only tags)
CONTACTLESS_ATR_PREFIXES = (
    "3B8F8001804F0CA000000306030001",  # Mifare Classic 1K
    "3B8F8001804F0CA000000306030002",  # Mifare Classic 4K
    "3B8F8001804F0CA000000306030003",  # Mifare Ultralight
    "3B8F8001804F0CA000000306030031",  # NTAG213
    "3B8F8001804F0CA000000306030032",  # NTAG215
    "3B8F8001804F0CA000000306030033",  # NTAG216
)


def parse_tlv(data: List[int]) -> Dict[str, bytes]:
    """Parse TLV data into tag -> value dict."""
    result: Dict[str, bytes] = {}
    i = 0
    while i < len(data):
        tag = data[i]
        i += 1
        if (tag & 0x1F) == 0x1F:  # Multi-byte tag
            tag_bytes = [tag]
            while i < len(data) and data[i] & 0x80:
                tag_bytes.append(data[i])
                i += 1
            if i < len(data):
                tag_bytes.append(data[i])
                i += 1
            tag_hex = "".join(f"{b:02X}" for b in tag_bytes)
        else:
            tag_hex = f"{tag:02X}"

        if i >= len(data):
            break
        length = data[i]
        i += 1
        if length & 0x80:
            num_bytes = length & 0x7F
            length = 0
            for _ in range(num_bytes):
                if i < len(data):
                    length = (length << 8) + data[i]
                    i += 1

        if i + length <= len(data):
            result[tag_hex.upper()] = bytes(data[i : i + length])
        i += length
    return result


def find_tag(data: bytes, tag: str) -> Optional[bytes]:
    """Find a tag in TLV data (recursive)."""
    try:
        parsed = parse_tlv(list(data))
    except Exception:
        return None

    tag = tag.upper()
    if tag in parsed:
        return parsed[tag]

    for k, v in parsed.items():
        try:
            if int(k[:2], 16) & 0x20:  # Constructed tag
                found = find_tag(v, tag)
                if found:
                    return found
        except Exception:
            pass
    return None


@dataclass
class CardScanResult:
    pan: Optional[str] = None
    uid: Optional[str] = None
    tokenized: bool = False
    identifiers: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def identifier(self) -> Optional[str]:
        if id := self.identifiers.get("identifier"):
            return id.get("value")
        return None

    def identifier_type(self) -> Optional[str]:
        if id := self.identifiers.get("identifier"):
            return id.get("type")
        return None


class CardReaderService:
    """Reads NFC cards and extracts stable identifiers (PAN or UID)."""

    def __init__(self, nfc_reader: Optional[NFCReader] = None):
        self.nfc_reader = nfc_reader or NFCReader()

    def wait_for_card(self, timeout: int = 10) -> bool:
        return self.nfc_reader.wait_for_card(timeout=timeout)

    def disconnect(self) -> None:
        self.nfc_reader.disconnect()

    def read_card_data(self) -> CardScanResult:
        if not self.nfc_reader.is_connected():
            raise RuntimeError("No card connected")

        atr = self._get_atr_hex()
        uid = self._get_uid()
        result = CardScanResult(uid=uid)

        # Fast path: contactless-only tags (Mifare, NTAG) - just use UID
        if any(atr.startswith(p) for p in CONTACTLESS_ATR_PREFIXES):
            if uid:
                result.identifiers = {"identifier": {"type": "UID", "value": uid}}
            return result

        # Try EMV: read PAN from payment card
        pan = self._try_read_emv_pan()
        if pan:
            result.pan = pan
            result.identifiers = {"identifier": {"type": "PAN", "value": pan}}
            if uid:
                result.identifiers["secondary"] = {"type": "UID", "value": uid}
        elif uid:
            result.identifiers = {"identifier": {"type": "UID", "value": uid}}

        return result

    def _get_atr_hex(self) -> str:
        if self.nfc_reader.connection:
            try:
                atr = self.nfc_reader.connection.getATR()
                return "".join(f"{b:02X}" for b in atr)
            except Exception:
                pass
        return ""

    def _get_uid(self) -> Optional[str]:
        try:
            response, sw1, sw2 = self._transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
            if sw1 == 0x90 and response:
                return "".join(f"{b:02X}" for b in response)
        except Exception:
            pass
        return None

    def _try_read_emv_pan(self) -> Optional[str]:
        """Try to read PAN from EMV card via PPSE/PSE."""
        # Try PPSE (contactless) and PSE (contact)
        for name in (b"2PAY.SYS.DDF01", b"1PAY.SYS.DDF01"):
            data, sw1, sw2 = self._select_name(name)
            if (sw1, sw2) != (0x90, 0x00) or not data:
                continue

            # Find AIDs in response
            aids = self._extract_aids(data)
            if not aids:
                aids = self._default_aids()

            # Try each AID
            for aid in aids:
                pan = self._read_pan_from_aid(aid)
                if pan:
                    return pan
        return None

    def _extract_aids(self, data: bytes) -> List[bytes]:
        """Extract AID list from PPSE/PSE response."""
        result = []
        try:
            parsed = parse_tlv(list(data))
            for tag, val in parsed.items():
                if tag == "4F":
                    result.append(val)
                elif int(tag[:2], 16) & 0x20:  # Constructed
                    result.extend(self._extract_aids(val))
        except Exception:
            pass
        return result

    def _default_aids(self) -> List[bytes]:
        """Common payment AIDs to try."""
        return [
            bytes.fromhex("A0000000031010"),  # Visa
            bytes.fromhex("A0000000041010"),  # Mastercard
            bytes.fromhex("A0000000043060"),  # Maestro
            bytes.fromhex("A00000002501"),  # Amex
            bytes.fromhex("A0000003241010"),  # MIR
        ]

    def _read_pan_from_aid(self, aid: bytes) -> Optional[str]:
        """Select AID and read PAN from records."""
        data, sw1, sw2 = self._select_aid(aid)
        if (sw1, sw2) != (0x90, 0x00):
            return None

        # Read records from SFI 1-10, record 1-5
        for sfi in range(1, 11):
            for rec in range(1, 6):
                record = self._read_record(sfi, rec)
                if not record:
                    continue

                # Look for PAN (tag 5A) or Track 2 (tag 57)
                if pan_bytes := find_tag(record, "5A"):
                    return toHexString(list(pan_bytes)).replace(" ", "").rstrip("F")

                if track2 := find_tag(record, "57"):
                    track2_hex = toHexString(list(track2)).replace(" ", "")
                    if "D" in track2_hex:
                        return track2_hex.split("D")[0]
        return None

    def _select_name(self, name: bytes) -> Tuple[Optional[bytes], int, int]:
        apdu = [0x00, 0xA4, 0x04, 0x00, len(name)] + list(name) + [0x00]
        return self._transmit(apdu)

    def _select_aid(self, aid: bytes) -> Tuple[Optional[bytes], int, int]:
        apdu = [0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid) + [0x00]
        return self._transmit(apdu)

    def _read_record(self, sfi: int, record: int) -> Optional[bytes]:
        p2 = (sfi << 3) | 0x04
        response, sw1, sw2 = self._transmit([0x00, 0xB2, record, p2, 0x00])
        if sw1 == 0x90 and response:
            return response
        return None

    def _transmit(self, apdu: List[int]) -> Tuple[Optional[bytes], int, int]:
        try:
            response, sw1, sw2 = self.nfc_reader.send_apdu(apdu)
            return (bytes(response) if response else b"", sw1, sw2)
        except Exception:
            return None, 0x6F, 0x00
