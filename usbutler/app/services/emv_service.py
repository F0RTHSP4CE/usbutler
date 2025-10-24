"""
Modernized EMV card service that supports both payment cards (PAN)
and general NFC tags (UID-based).

This implementation adapts the standalone d-pscs script to integrate
with the existing NFCReader abstraction used by the usbutler
application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from smartcard.util import toHexString

from app.emv.nfc_reader import NFCReader

ATR_MAP: Dict[str, str] = {
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 01": "Mifare Classic 1K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 02": "Mifare Classic 4K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 03": "Mifare Ultralight or Ultralight C",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 31": "NTAG213",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 32": "NTAG215",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 33": "NTAG216",
}

CONTACTLESS_ONLY_ATR_PREFIXES: Tuple[str, ...] = (
    "3B8F8001804F0CA000000306030001",
    "3B8F8001804F0CA000000306030002",
    "3B8F8001804F0CA000000306030003",
    "3B8F8001804F0CA000000306030031",
    "3B8F8001804F0CA000000306030032",
    "3B8F8001804F0CA000000306030033",
)


def parse_atr(atr_bytes: List[int]) -> Dict[str, object]:
    if not atr_bytes:
        return {"error": "Empty ATR"}

    atr_hex = toHexString(atr_bytes)
    parsed: Dict[str, object] = {
        "raw_atr_hex": atr_hex,
        "ts": None,
        "t0": None,
        "interface_chars": {},
        "historical_bytes_hex": "",
        "tck": None,
        "tck_valid": None,
        "protocol": "T=0",
        "summary": [],
    }

    parsed["ts"] = f"{atr_bytes[0]:02X}"
    if atr_bytes[0] == 0x3B:
        parsed["summary"].append(f"TS: {parsed['ts']} (Direct Convention)")
    elif atr_bytes[0] == 0x3F:
        parsed["summary"].append(f"TS: {parsed['ts']} (Inverse Convention)")
    else:
        parsed["summary"].append(f"TS: {parsed['ts']} (Unknown Convention)")

    if len(atr_bytes) < 2:
        return parsed

    t0 = atr_bytes[1]
    parsed["t0"] = f"{t0:02X}"
    num_historical_bytes = t0 & 0x0F
    parsed["summary"].append(
        f"T0: {parsed['t0']}, K = {num_historical_bytes} (historical bytes)"
    )

    i = 2
    y_indicator = t0 >> 4
    protocol_t = 0
    interface_char_index = 1

    while True:
        if y_indicator & 0x01:
            if i < len(atr_bytes):
                parsed["interface_chars"][f"TA{interface_char_index}"] = (
                    f"{atr_bytes[i]:02X}"
                )
                i += 1
            else:
                break
        if y_indicator & 0x02:
            if i < len(atr_bytes):
                parsed["interface_chars"][f"TB{interface_char_index}"] = (
                    f"{atr_bytes[i]:02X}"
                )
                i += 1
            else:
                break
        if y_indicator & 0x04:
            if i < len(atr_bytes):
                parsed["interface_chars"][f"TC{interface_char_index}"] = (
                    f"{atr_bytes[i]:02X}"
                )
                i += 1
            else:
                break
        if y_indicator & 0x08:
            if i < len(atr_bytes):
                td = atr_bytes[i]
                parsed["interface_chars"][f"TD{interface_char_index}"] = (
                    f"{td:02X}"
                )
                y_indicator = td >> 4
                protocol_t = td & 0x0F
                interface_char_index += 1
                i += 1
            else:
                break
        else:
            break

    parsed["protocol"] = f"T={protocol_t}"
    parsed["summary"].append(f"Protocol: T={protocol_t}")

    historical_start = i
    historical_end = historical_start + num_historical_bytes
    if historical_end <= len(atr_bytes):
        historical = atr_bytes[historical_start:historical_end]
        parsed["historical_bytes_hex"] = toHexString(historical)
        parsed["summary"].append(
            f"Historical Bytes: {parsed['historical_bytes_hex']}"
        )
        i = historical_end

    if protocol_t > 0 and i < len(atr_bytes):
        tck = atr_bytes[i]
        parsed["tck"] = f"{tck:02X}"
        checksum = 0
        for byte_val in atr_bytes[1 : i + 1]:
            checksum ^= byte_val
        parsed["tck_valid"] = checksum == 0
        validity = "Valid" if parsed["tck_valid"] else "Invalid!"
        parsed["summary"].append(f"TCK: {parsed['tck']} ({validity})")

    return parsed


def identify_card_type(parsed_atr: Optional[Dict[str, object]]) -> str:
    if not parsed_atr:
        return "Unknown Card Type"

    atr_hex = parsed_atr.get("raw_atr_hex", "")
    historical_hex = parsed_atr.get("historical_bytes_hex", "")

    for known_atr, card_type in ATR_MAP.items():
        if isinstance(atr_hex, str) and atr_hex.startswith(known_atr):
            return card_type

    if isinstance(historical_hex, str) and historical_hex.startswith("80"):
        return "EMV or ISO 14443-4 Compliant Card (e.g., DESFire)"

    protocol = parsed_atr.get("protocol")
    if protocol in {"T=1", "T=15"}:
        return "EMV Card (Visa, Mastercard, etc.)"

    atr_hex_str = atr_hex if isinstance(atr_hex, str) else ""
    if "71 D5" in atr_hex_str or "77 D5" in atr_hex_str:
        return "EMV Card (Likely)"

    return "Unknown Card Type"


def parse_tlv(data: List[int]) -> Dict[str, bytes]:
    i = 0
    tlv: Dict[str, bytes] = {}
    length_data = len(data)

    while i < length_data:
        tag = data[i]
        i += 1
        if (tag & 0x1F) == 0x1F:
            tag_bytes = [tag]
            while True:
                if i >= length_data:
                    raise ValueError("Invalid TLV: truncated tag bytes")
                b = data[i]
                tag_bytes.append(b)
                i += 1
                if not (b & 0x80):
                    break
            tag_hex = "".join(f"{b:02X}" for b in tag_bytes)
        else:
            tag_hex = f"{tag:02X}"

        if i >= length_data:
            raise ValueError("Invalid TLV: truncated length")

        length = data[i]
        i += 1
        if length & 0x80:
            num_len_bytes = length & 0x7F
            length = 0
            if i + num_len_bytes > length_data:
                raise ValueError("Invalid TLV: truncated length bytes")
            for _ in range(num_len_bytes):
                length = (length << 8) + data[i]
                i += 1

        if i + length > length_data:
            raise ValueError("Invalid TLV: truncated value")

        value = bytes(data[i : i + length])
        i += length

        tlv[tag_hex.upper()] = value

    return tlv


def find_tag_in_tlv_tree(tlv_bytes: bytes, tag_hex: str) -> Optional[bytes]:
    try:
        parsed = parse_tlv(list(tlv_bytes))
    except Exception:
        return None

    tag_hex = tag_hex.upper()
    if tag_hex in parsed:
        return parsed[tag_hex]

    for k, v in parsed.items():
        try:
            first_tag_byte = int(k[:2], 16)
        except Exception:
            continue
        if first_tag_byte & 0x20:
            found = find_tag_in_tlv_tree(v, tag_hex)
            if found:
                return found

    return None


AID_ISSUER_MAP: Dict[str, str] = {
    "A000000003": "Visa",
    "A0000000031010": "Visa Credit/Debit",
    "A0000000032010": "Visa Electron",
    "A0000000033010": "VPay",
    "A000000004": "Mastercard",
    "A0000000041010": "Mastercard Credit/Debit",
    "A0000000043060": "Maestro (Mastercard network)",
    "A000000025": "American Express",
    "A00000002501": "American Express",
    "A000000152": "Discover",
    "A000000042": "Diners Club / Discover",
    "A000000065": "JCB",
    "A000000333": "UnionPay",
    "A000000324": "MIR",
}


def issuer_from_aid(aid_bytes: bytes) -> Optional[str]:
    aid_hex = toHexString(list(aid_bytes)).replace(" ", "")
    best: Optional[Tuple[str, str]] = None
    for prefix, name in AID_ISSUER_MAP.items():
        if aid_hex.upper().startswith(prefix.upper()):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, name)
    return best[1] if best else None


def issuer_from_pan(pan: Optional[str]) -> Optional[str]:
    if not pan or len(pan) < 2:
        return None

    if pan.startswith("4"):
        return "Visa"
    if pan.startswith("34") or pan.startswith("37"):
        return "American Express"

    try:
        if 51 <= int(pan[:2]) <= 55:
            return "Mastercard"
    except Exception:
        pass

    try:
        if len(pan) >= 6:
            prefix6 = int(pan[:6])
            if 222100 <= prefix6 <= 272099:
                return "Mastercard"
    except Exception:
        pass

    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 2200 <= prefix4 <= 2204:
                return "MIR"
    except Exception:
        pass

    if pan.startswith("62"):
        return "UnionPay"

    if pan.startswith("6011") or pan.startswith("65") or pan.startswith("64") or pan.startswith("622"):
        return "Discover/UnionPay (check BIN)"

    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 3528 <= prefix4 <= 3589:
                return "JCB"
    except Exception:
        pass

    return None


def is_mifare_like(tag_type: Optional[str], atr_card_type: Optional[str]) -> bool:
    haystack = " ".join(filter(None, [tag_type or "", atr_card_type or ""])).upper()
    if "EMV" in haystack:
        return False
    keywords = ["MIFARE", "NTAG", "ULTRALIGHT", "CLASSIC", "TYPE2", "TYPE 2"]
    keywords += ["DESFIRE", "ISO 14443-4", "ISO14443-4", "NDEF"]
    return any(keyword in haystack for keyword in keywords)


def is_contactless_only_tag(atr_hex_compact: str, atr_card_type: Optional[str]) -> bool:
    if is_mifare_like(None, atr_card_type):
        return True
    if not atr_hex_compact:
        return False
    upper = atr_hex_compact.upper()
    return any(upper.startswith(prefix) for prefix in CONTACTLESS_ONLY_ATR_PREFIXES)


def derive_identifiers(
    pan: Optional[str],
    uid: Optional[str],
    tokenized: bool,
    tag_type: Optional[str],
    atr_card_type: Optional[str],
) -> Dict[str, Dict[str, str]]:
    identifiers: Dict[str, Dict[str, str]] = {}

    if tokenized:
        return identifiers

    if pan:
        identifiers["primary"] = {"type": "PAN", "value": pan}
        if uid:
            identifiers["secondary"] = {"type": "UID", "value": uid}
    elif uid:
        tag_upper = (tag_type or "").upper()
        if "UID" in tag_upper or is_mifare_like(tag_type, atr_card_type):
            identifiers["primary"] = {"type": "UID", "value": uid}

    return identifiers


def to_hex(data: Optional[bytes]) -> str:
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return toHexString(list(data))
    return str(data)


@dataclass
class CardScanResult:
    pan: Optional[str]
    expiry: Optional[str]
    issuer: Optional[str]
    tag_type: str
    uid: Optional[str]
    tokenized: bool
    atr_hex: str
    atr_hex_compact: str
    atr_summary: List[str] = field(default_factory=list)
    card_type: str = "Unknown Card Type"
    identifiers: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def primary_identifier(self) -> Optional[str]:
        primary = self.identifiers.get("primary")
        if primary:
            return primary.get("value")
        return None

    def primary_identifier_type(self) -> Optional[str]:
        primary = self.identifiers.get("primary")
        if primary:
            return primary.get("type")
        return None


class EMVCardService:
    """Service for reading NFC cards and extracting stable identifiers."""

    def __init__(self, nfc_reader: Optional[NFCReader] = None):
        self.nfc_reader = nfc_reader or NFCReader()
        self.last_scan: Optional[CardScanResult] = None

    def _ensure_connection(self, timeout: int = 3) -> bool:
        if self.nfc_reader.is_connected():
            return True
        try:
            return self.nfc_reader.wait_for_card(timeout=timeout)
        except Exception:
            return False

    def wait_for_card(self, timeout: int = 10) -> bool:
        return self.nfc_reader.wait_for_card(timeout=timeout)

    def get_card_info(self) -> Optional[str]:
        atr_bytes = self._get_atr_bytes()
        return toHexString(atr_bytes) if atr_bytes else None

    def disconnect(self) -> None:
        self.nfc_reader.disconnect()
        self.last_scan = None

    def read_card_pan(self) -> Optional[str]:
        try:
            scan_result = self.read_card_data()
            self.last_scan = scan_result
            return scan_result.primary_identifier()
        except Exception as exc:
            print(f"Error reading card identifier: {exc}")
            return None

    def get_last_scan(self) -> Optional[CardScanResult]:
        return self.last_scan

    def read_card_data(self) -> CardScanResult:
        if not self.nfc_reader.is_connected():
            raise RuntimeError("No card connection available. Call wait_for_card first.")

        atr_bytes = self._get_atr_bytes()
        parsed_atr = parse_atr(atr_bytes) if atr_bytes else None
        atr_hex_spaced = (
            parsed_atr.get("raw_atr_hex", "") if isinstance(parsed_atr, dict) else ""
        )
        atr_hex_compact = atr_hex_spaced.replace(" ", "") if atr_hex_spaced else ""
        atr_summary = (
            parsed_atr.get("summary", []) if isinstance(parsed_atr, dict) else []
        )
        atr_card_type = identify_card_type(parsed_atr)

        uid_hex = self._get_uid()

        result = CardScanResult(
            pan=None,
            expiry=None,
            issuer=None,
            tag_type="Unknown",
            uid=uid_hex,
            tokenized=False,
            atr_hex=atr_hex_spaced,
            atr_hex_compact=atr_hex_compact,
            atr_summary=atr_summary,
            card_type=atr_card_type,
            identifiers={},
        )

        # Fast-path for clearly non-EMV cards (e.g. MIFARE/NTAG) to avoid slow EMV retries
        if is_contactless_only_tag(atr_hex_compact, atr_card_type):
            tag_type, tokenized = self._detect_contactless_tag_type(
                uid_hex, atr_hex_compact, atr_card_type
            )
            result.tag_type = tag_type
            result.tokenized = tokenized
            result.identifiers = derive_identifiers(
                result.pan, uid_hex, result.tokenized, result.tag_type, result.card_type
            )
            return result

        ppse = b"2PAY.SYS.DDF01"
        pse = b"1PAY.SYS.DDF01"
        candidate_aids: List[bytes] = []
        tokenized_hint = False

        for name in (ppse, pse):
            data, sw1, sw2 = self._select_name(name)
            print(
                f"SELECT {name.decode('ascii', errors='ignore')} -> SW={sw1:02X}{sw2:02X} DATA={to_hex(data)}"
            )
            if (sw1, sw2) == (0x6A, 0x82):
                continue
            if data is None:
                continue

            resp_bytes = bytes(data)
            if b"A0000000041010" in resp_bytes or b"A0000000031010" in resp_bytes:
                print("PPSE indicates tokenized wallet (e.g., mobile pay).")
                result.tag_type = "HCE/Tokenized (via PPSE)"
                result.tokenized = True
                result.identifiers = derive_identifiers(
                    result.pan, uid_hex, result.tokenized, result.tag_type, result.card_type
                )
                return result

            try:
                aid_list = self._find_all_aids(resp_bytes)
                candidate_aids.extend(aid_list)
            except Exception:
                pass

            if candidate_aids:
                break

        if not candidate_aids:
            candidate_aids = [
                bytes.fromhex("A0000000031010"),
                bytes.fromhex("A0000000032010"),
                bytes.fromhex("A0000000041010"),
                bytes.fromhex("A0000000043060"),
                bytes.fromhex("A00000002501"),
                bytes.fromhex("A0000001524040"),
                bytes.fromhex("A0000000651010"),
                bytes.fromhex("A000000333010101"),
                bytes.fromhex("A0000003241010"),
            ]

        pan: Optional[str] = None
        expiry: Optional[str] = None
        detected_issuer: Optional[str] = None
        selected_aid: Optional[bytes] = None

        for aid in candidate_aids:
            print(f"Trying AID {toHexString(list(aid))} ...")
            data, sw1, sw2 = self._select_application(aid)
            print(f"  SELECT -> SW={sw1:02X}{sw2:02X} DATA={to_hex(data)}")

            if (sw1, sw2) == (0x67, 0x00):
                print("  Received 6700 — likely HCE token refusing standard SELECT.")
                tokenized_hint = True
                continue

            if (sw1, sw2) != (0x90, 0x00) or data is None:
                continue

            selected_aid = aid

            for sfi in range(1, 16):
                for rec in range(1, 8):
                    record = self._read_record(sfi, rec)
                    if record is None:
                        continue

                    v5a = find_tag_in_tlv_tree(record, "5A")
                    v57 = find_tag_in_tlv_tree(record, "57")
                    v5f24 = find_tag_in_tlv_tree(record, "5F24")

                    if v5a:
                        pan = toHexString(list(v5a)).replace(" ", "").rstrip("F")
                        print(f"  Found 5A in SFI {sfi} rec {rec}: PAN={pan}")
                    if v57 and not pan:
                        track2 = toHexString(list(v57)).replace(" ", "")
                        if "D" in track2:
                            pan = track2.split("D", 1)[0]
                            expiry = track2.split("D", 1)[1][:4]
                        elif "F" in track2:
                            pan = track2.split("F", 1)[0]
                        print(f"  Found 57 in SFI {sfi} rec {rec}: track2={track2}")
                    if v5f24 and not expiry:
                        expiry = toHexString(list(v5f24)).replace(" ", "")
                        print(f"  Found 5F24 expiry: {expiry}")

                    if pan:
                        break
                if pan:
                    break
            if pan:
                break

        if selected_aid:
            detected_issuer = issuer_from_aid(selected_aid)
        if not detected_issuer and pan:
            detected_issuer = issuer_from_pan(pan)

        tokenized = False
        tag_type: Optional[str] = None
        if pan:
            tag_type = "EMV"
        else:
            tag_type, tokenized = self._detect_contactless_tag_type(
                uid_hex, atr_hex_compact, atr_card_type
            )
            if not tokenized:
                if tokenized_hint or (
                    uid_hex is None
                    and selected_aid is None
                    and atr_card_type.upper().startswith("EMV")
                ):
                    tokenized = True
                    if not tag_type or tag_type == "Unknown":
                        tag_type = "HCE/Tokenized (mobile wallet)"

        result.pan = pan
        result.expiry = expiry
        result.issuer = detected_issuer
        result.tag_type = tag_type or result.tag_type or "Unknown"
        result.tokenized = tokenized or result.tokenized
        result.identifiers = derive_identifiers(
            result.pan, uid_hex, result.tokenized, result.tag_type, result.card_type
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_atr_bytes(self) -> List[int]:
        if getattr(self.nfc_reader, "connection", None):
            try:
                atr = self.nfc_reader.connection.getATR()
                return list(atr)
            except Exception:
                return []
        return []

    def _get_uid(self) -> Optional[str]:
        try:
            response, sw1, sw2 = self._transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
            if (sw1, sw2) == (0x90, 0x00) or sw1 == 0x91:
                if response:
                    return "".join(f"{b:02X}" for b in response)
        except Exception:
            pass
        return None

    def _select_name(self, name: bytes) -> Tuple[Optional[bytes], int, int]:
        apdu = [0x00, 0xA4, 0x04, 0x00, len(name)] + list(name)
        return self._transmit(apdu + [0x00])

    def _select_application(self, aid: bytes) -> Tuple[Optional[bytes], int, int]:
        apdu = [0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid)
        return self._transmit(apdu + [0x00])

    def _read_record(self, sfi: int, record: int) -> Optional[bytes]:
        p2 = (sfi << 3) | 0x04
        apdu = [0x00, 0xB2, record, p2, 0x00]
        response, sw1, sw2 = self._transmit(apdu)
        if (sw1, sw2) == (0x90, 0x00) and response:
            return response
        return None

    def _find_all_aids(self, data: bytes) -> List[bytes]:
        result: List[bytes] = []
        parsed = parse_tlv(list(data))
        for tag, val in parsed.items():
            if tag.upper() == "4F":
                result.append(val)
            else:
                first_byte = int(tag[:2], 16)
                if first_byte & 0x20:
                    result.extend(self._find_all_aids(val))
        return result

    def _transmit(self, apdu: List[int]) -> Tuple[Optional[bytes], int, int]:
        try:
            response, sw1, sw2 = self.nfc_reader.send_apdu(apdu)
            return (bytes(response) if response else b""), sw1, sw2
        except Exception as exc:
            print(f"APDU transmit error for {apdu}: {exc}")
            if self._ensure_connection():
                try:
                    response, sw1, sw2 = self.nfc_reader.send_apdu(apdu)
                    return (bytes(response) if response else b""), sw1, sw2
                except Exception as retry_exc:
                    print(f"APDU retry failed for {apdu}: {retry_exc}")
            return None, 0x6F, 0x00

    def _load_key_default(self, key_number: int = 0x00) -> bool:
        key = [0xFF] * 6
        apdu = [0xFF, 0x82, 0x00, key_number, 0x06] + key
        _, sw1, sw2 = self._transmit(apdu)
        return (sw1, sw2) == (0x90, 0x00)

    def _mifare_classic_authenticate_block(
        self, block_number: int, key_number: int = 0x00, key_type: int = 0x60
    ) -> Tuple[bool, Tuple[int, int]]:
        apdu = [
            0xFF,
            0x86,
            0x00,
            0x00,
            0x05,
            0x01,
            0x00,
            block_number,
            key_type,
            key_number,
        ]
        _, sw1, sw2 = self._transmit(apdu)
        return (sw1, sw2) == (0x90, 0x00), (sw1, sw2)

    def _read_block(self, block_or_page: int, length: int = 0x10) -> Tuple[Optional[bytes], Tuple[int, int]]:
        apdu = [0xFF, 0xB0, 0x00, block_or_page, length]
        response, sw1, sw2 = self._transmit(apdu)
        if (sw1, sw2) == (0x90, 0x00) and response:
            return response, (sw1, sw2)
        return None, (sw1, sw2)

    def _detect_contactless_tag_type(
        self, uid_hex: Optional[str], atr_hex_compact: str, card_type: Optional[str] = None
    ) -> Tuple[str, bool]:
        tokenized = False

        upper_card_type = (card_type or "").upper()
        iso14443_keywords = ("ISO 14443-4", "ISO14443-4", "DESFIRE", "TYPE4", "TYPE 4")
        is_iso14443_4 = any(keyword in upper_card_type for keyword in iso14443_keywords)

        is_classic = False
        if not is_iso14443_4:
            loaded = self._load_key_default(key_number=0x00)
            if loaded:
                for test_block in (1, 4, 8):
                    ok, _ = self._mifare_classic_authenticate_block(
                        test_block, key_number=0x00, key_type=0x60
                    )
                    if ok:
                        is_classic = True
                        break
        if is_classic:
            return "MIFARE Classic (likely)", False

        try:
            ndef_aid = bytes.fromhex("D2760000850101")
            data, sw1, sw2 = self._transmit(
                [0x00, 0xA4, 0x04, 0x00, len(ndef_aid)] + list(ndef_aid)
            )
            if (sw1, sw2) == (0x90, 0x00):
                return "Type4/NDEF (likely)", False
        except Exception:
            pass

        if not is_iso14443_4:
            raw3, _ = self._read_block(3, length=0x10)
            if raw3:
                if b"\xE1" in raw3 or b"\x03" in raw3:
                    p4, _ = self._read_block(4, length=0x10)
                    combined = raw3 + (p4 or b"")
                    if b"\x03" in combined or b"\xE1" in combined:
                        return "NTAG/Ultralight (likely)", False

        if uid_hex:
            if is_iso14443_4:
                return "Type4/ISO 14443-4 (UID only)", False
            return "Contactless (UID present, exact type unknown)", False

        if is_iso14443_4:
            return "Type4/ISO 14443-4 (unknown)", False

        return "Unknown", tokenized
