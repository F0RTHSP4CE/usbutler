#!/usr/bin/env python3
"""
read_emv_pan_full_with_contact_and_tag_detection.py

Improvements:
 - Better contactless tag-type detection:
    * Attempts to load a default MIFARE key and perform MIFARE Classic auth (positive indicator of Classic).
    * Selects NDEF AID (Type-4) as before.
    * Reads raw pages/blocks and looks for NDEF Capability Container (0xE1.. or NDEF TLV 0x03) to detect NTAG/Ultralight.
 - Better token/HCE filtering (checks PPSE content and ATR patterns).
 - Cleaned structure and clearer return values:
    (pan, expiry, issuer, tag_type, uid_hex, tokenized_flag)
 - Non-destructive; uses standard "load key" + "auth" APDUs for Classic detection which are commonly supported
   by PC/SC readers like ACR122U.
"""

import sys
import time
from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.scard import SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1


def to_hex(data):
    """Robust helper that accepts lists, tuples, bytes, or None."""
    if data is None:
        return ''
    if isinstance(data, (bytes, bytearray)):
        return toHexString(list(data))
    if isinstance(data, (list, tuple)):
        return toHexString(list(data))
    try:
        return toHexString(data)
    except Exception:
        return str(data)

# ---------- ATR parsing & card identification (borrowed from check.py) ----------
ATR_MAP = {
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 01": "Mifare Classic 1K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 02": "Mifare Classic 4K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 03": "Mifare Ultralight or Ultralight C",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 31": "NTAG213",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 32": "NTAG215",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 33": "NTAG216",
}


def parse_atr(atr_bytes):
    if not atr_bytes:
        return {"error": "Empty ATR"}

    atr_hex = toHexString(atr_bytes)
    parsed_data = {
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

    parsed_data["ts"] = f"{atr_bytes[0]:02X}"
    if atr_bytes[0] == 0x3B:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Direct Convention)")
    elif atr_bytes[0] == 0x3F:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Inverse Convention)")
    else:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Unknown Convention)")

    if len(atr_bytes) < 2:
        return parsed_data

    t0 = atr_bytes[1]
    parsed_data["t0"] = f"{t0:02X}"
    num_historical_bytes = t0 & 0x0F
    parsed_data["summary"].append(f"T0: {parsed_data['t0']}, K = {num_historical_bytes} (historical bytes)")

    i = 2
    y_indicator = t0 >> 4
    protocol_t = 0
    interface_char_index = 1

    while True:
        if y_indicator & 0x01:
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TA{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else:
                break
        if y_indicator & 0x02:
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TB{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else:
                break
        if y_indicator & 0x04:
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TC{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else:
                break
        if y_indicator & 0x08:
            if i < len(atr_bytes):
                td = atr_bytes[i]
                parsed_data["interface_chars"][f"TD{interface_char_index}"] = f"{td:02X}"
                y_indicator = td >> 4
                protocol_t = td & 0x0F
                interface_char_index += 1
                i += 1
            else:
                break
        else:
            break

    parsed_data["protocol"] = f"T={protocol_t}"
    parsed_data["summary"].append(f"Protocol: T={protocol_t}")

    historical_start_index = i
    historical_end_index = historical_start_index + num_historical_bytes
    if historical_end_index <= len(atr_bytes):
        historical = atr_bytes[historical_start_index:historical_end_index]
        parsed_data["historical_bytes_hex"] = toHexString(historical)
        parsed_data["summary"].append(
            f"Historical Bytes: {parsed_data['historical_bytes_hex']}"
        )
        i = historical_end_index

    if protocol_t > 0 and i < len(atr_bytes):
        tck = atr_bytes[i]
        parsed_data["tck"] = f"{tck:02X}"
        checksum = 0
        for byte_val in atr_bytes[1 : i + 1]:
            checksum ^= byte_val
        parsed_data["tck_valid"] = checksum == 0
        validity = "Valid" if parsed_data["tck_valid"] else "Invalid!"
        parsed_data["summary"].append(f"TCK: {parsed_data['tck']} ({validity})")

    return parsed_data


def identify_card_type(parsed_atr):
    atr_hex = parsed_atr.get("raw_atr_hex", "") if parsed_atr else ""
    historical_hex = parsed_atr.get("historical_bytes_hex", "") if parsed_atr else ""

    for known_atr, card_type in ATR_MAP.items():
        if atr_hex.startswith(known_atr):
            return card_type

    if historical_hex.startswith("80"):
        return "EMV or ISO 14443-4 Compliant Card (e.g., DESFire)"

    protocol = parsed_atr.get("protocol") if parsed_atr else None
    if protocol in ["T=1", "T=15"]:
        return "EMV Card (Visa, Mastercard, etc.)"

    if "71 D5" in atr_hex or "77 D5" in atr_hex:
        return "EMV Card (Likely)"

    return "Unknown Card Type"

# ---------- TLV parsing helpers ----------
def parse_tlv(data):
    """Simple BER-TLV parser returning dict of tag(hex)->value(bytes)."""
    i = 0
    tlv = {}
    n = len(data)
    while i < n:
        tag = data[i]
        i += 1
        # multi-byte tag
        if (tag & 0x1F) == 0x1F:
            tag_bytes = [tag]
            while True:
                if i >= n:
                    raise ValueError("Invalid TLV: truncated tag bytes")
                b = data[i]
                tag_bytes.append(b)
                i += 1
                if not (b & 0x80):
                    break
            tag_hex = ''.join(f'{b:02X}' for b in tag_bytes)
        else:
            tag_hex = f'{tag:02X}'

        if i >= n:
            raise ValueError("Invalid TLV: truncated length")

        length = data[i]
        i += 1
        if length & 0x80:
            num_len_bytes = length & 0x7F
            length = 0
            if i + num_len_bytes > n:
                raise ValueError("Invalid TLV: truncated length bytes")
            for _ in range(num_len_bytes):
                length = (length << 8) + data[i]
                i += 1

        if i + length > n:
            raise ValueError("Invalid TLV: truncated value")
        value = bytes(data[i:i+length])
        i += length

        tlv[tag_hex.upper()] = value
    return tlv

def find_tag_in_tlv_tree(tlv_bytes, tag_hex):
    """Recursively search TLV bytes for a tag (tag_hex like '5A' or '57')."""
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
        if first_tag_byte & 0x20:  # constructed
            found = find_tag_in_tlv_tree(v, tag_hex)
            if found:
                return found
    return None

# ---------- AID mappings (expanded) ----------
AID_ISSUER_MAP = {
    'A000000003': 'Visa',
    'A0000000031010': 'Visa Credit/Debit',
    'A0000000032010': 'Visa Electron',
    'A0000000033010': 'VPay',
    'A000000004': 'Mastercard',
    'A0000000041010': 'Mastercard Credit/Debit',
    'A0000000043060': 'Maestro (Mastercard network)',
    'A000000025': 'American Express',
    'A00000002501': 'American Express',
    'A000000152': 'Discover',
    'A000000042': 'Diners Club / Discover',
    'A000000065': 'JCB',
    'A000000333': 'UnionPay',
    'A000000324': 'MIR',
    # Additional examples...
}

def issuer_from_aid(aid_bytes):
    aid_hex = toHexString(list(aid_bytes)).replace(' ', '')
    best = None
    for prefix, name in AID_ISSUER_MAP.items():
        if aid_hex.upper().startswith(prefix.upper()):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, name)
    return best[1] if best else None

def issuer_from_pan(pan):
    if not pan or len(pan) < 2:
        return None
    if pan.startswith('4'):
        return 'Visa'
    if pan.startswith('34') or pan.startswith('37'):
        return 'American Express'
    try:
        if 51 <= int(pan[:2]) <= 55:
            return 'Mastercard'
    except Exception:
        pass
    try:
        if len(pan) >= 6:
            prefix6 = int(pan[:6])
            if 222100 <= prefix6 <= 272099:
                return 'Mastercard'
    except Exception:
        pass
    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 2200 <= prefix4 <= 2204:
                return 'MIR'
    except Exception:
        pass
    if pan.startswith('62'):
        return 'UnionPay'
    if pan.startswith('6011') or pan.startswith('65') or pan.startswith('64') or pan.startswith('622'):
        return 'Discover/UnionPay (check BIN)'
    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 3528 <= prefix4 <= 3589:
                return 'JCB'
    except Exception:
        pass
    return None


def is_mifare_like(tag_type, atr_card_type):
    haystack = " ".join(filter(None, [tag_type, atr_card_type])).upper()
    keywords = ["MIFARE", "NTAG", "ULTRALIGHT", "CLASSIC", "TYPE2", "TYPE 2"]
    return any(word in haystack for word in keywords)


def derive_identifiers(pan, uid, tokenized, tag_type, atr_card_type):
    identifiers = {}
    if tokenized:
        return identifiers
    if pan:
        identifiers["primary"] = {"type": "PAN", "value": pan}
        if uid:
            identifiers["secondary"] = {"type": "UID", "value": uid}
    elif uid and is_mifare_like(tag_type, atr_card_type):
        identifiers["primary"] = {"type": "UID", "value": uid}
    return identifiers

# ---------- Contactless tag detection helpers ----------
def load_key_default(connection, key_number=0x00):
    """
    Load a key (6 bytes) into the reader volatile memory.
    Uses APDU: FF 82 00 <key_number> 06 <K0..K5>
    Default key: 6x 0xFF
    """
    key = [0xFF] * 6
    apdu = [0xFF, 0x82, 0x00, key_number, 0x06] + key
    try:
        resp, sw1, sw2 = connection.transmit(apdu)
        return (sw1, sw2) == (0x90, 0x00)
    except Exception:
        return False

def mifare_classic_authenticate_block(connection, block_number, key_number=0x00, key_type=0x60):
    """
    Try the PC/SC MIFARE auth command:
    FF 86 00 00 05 01 00 <block> <key-type> <key-number>
    key-type 0x60 = Key A, 0x61 = Key B
    Returns True if authentication succeeded (SW=9000).
    """
    apdu = [0xFF, 0x86, 0x00, 0x00, 0x05,
            0x01, 0x00, block_number, key_type, key_number]
    try:
        resp, sw1, sw2 = connection.transmit(apdu)
        return (sw1, sw2) == (0x90, 0x00), (sw1, sw2)
    except Exception:
        return False, (0x6F, 0x00)

def read_block(connection, block_or_page, length=0x10):
    """
    Generic raw read via FF B0 (common for ACR122-like readers).
    Use block_or_page as the P2 low byte.
    Returns (data_bytes or None, (sw1,sw2))
    """
    apdu = [0xFF, 0xB0, 0x00, block_or_page, length]
    try:
        resp, sw1, sw2 = connection.transmit(apdu)
        if (sw1, sw2) == (0x90, 0x00):
            return bytes(resp), (sw1, sw2)
        else:
            return None, (sw1, sw2)
    except Exception:
        return None, (0x6F, 0x00)

def detect_contactless_tag_type(connection, uid_hex, atr_hex):
    """
    Heuristic detection of contactless tag type.
    Returns (tag_type_string, tokenized_bool)
    """
    tokenized = False

    # --- Step 1: Try MIFARE Classic authentication first ---
    loaded = load_key_default(connection, key_number=0x00)
    is_classic = False
    if loaded:
        for test_block in (1, 4, 8):  # try a few blocks
            ok, sw = mifare_classic_authenticate_block(connection, test_block, key_number=0x00, key_type=0x60)
            if ok:
                is_classic = True
                break
    if is_classic:
        return 'MIFARE Classic (likely)', False

    # --- Step 2: Try NDEF AID (Type 4) ---
    try:
        ndef_aid = bytes.fromhex('D2760000850101')
        data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(ndef_aid)] + list(ndef_aid))
        if (sw1, sw2) == (0x90, 0x00):
            return 'Type4/NDEF (likely)', False
    except Exception:
        pass

    # --- Step 3: NTAG/Ultralight / Type2 heuristic ---
    raw3, sw3 = read_block(connection, 3, length=0x10)
    if raw3:
        if b'\xE1' in raw3 or b'\x03' in raw3:
            p4, _ = read_block(connection, 4, length=0x10)
            combined = raw3 + (p4 or b'')
            if b'\x03' in combined or b'\xE1' in combined:
                return 'NTAG/Ultralight (likely)', False

    # --- Step 4: Fallback ---
    if uid_hex:
        return 'Contactless (UID present, exact type unknown)', False

    return 'Unknown', False

# ---------- The main combined function ----------
def read_emv_pan_and_info(connection):
    """
    Attempts to read PAN and expiry, detect issuer, tag type, uid and whether tokenized.
    Returns: dict with keys pan, expiry, issuer, tag_type, uid, tokenized, atr_hex, atr_summary, card_type, identifiers
    """
    uid_hex = None

    # 0) Try to get UID via reader-specific GET UID (FF CA 00 00 00) — supported by many readers (ACR122U)
    try:
        resp, sw1, sw2 = connection.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if (sw1, sw2) == (0x90, 0x00) or sw1 == 0x91:
            uid_bytes = bytes(resp)
            uid_hex = ''.join(f'{b:02X}' for b in uid_bytes)
    except Exception:
        uid_hex = None

    atr_bytes = []
    parsed_atr = None
    atr_hex_spaced = ''
    atr_hex_compact = ''
    atr_card_type = 'Unknown Card Type'
    try:
        atr = connection.getATR()
        if atr:
            atr_bytes = list(atr)
            parsed_atr = parse_atr(atr_bytes)
            atr_hex_spaced = parsed_atr.get('raw_atr_hex', '') if isinstance(parsed_atr, dict) else ''
            atr_hex_compact = atr_hex_spaced.replace(' ', '')
            atr_card_type = identify_card_type(parsed_atr)
    except Exception:
        parsed_atr = None

    result = {
        "pan": None,
        "expiry": None,
        "issuer": None,
        "tag_type": None,
        "uid": uid_hex,
        "tokenized": False,
        "atr_hex": atr_hex_spaced,
        "atr_hex_compact": atr_hex_compact,
        "atr_summary": parsed_atr.get('summary', []) if isinstance(parsed_atr, dict) else [],
        "card_type": atr_card_type,
        "identifiers": {},
    }

    # 1) EMV discovery (PPSE / PSE)
    ppse = b'2PAY.SYS.DDF01'
    pse = b'1PAY.SYS.DDF01'
    candidate_aids = []
    tokenized_hint = False

    for name in (ppse, pse):
        try:
            data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(name)] + list(name))
        except Exception:
            data, sw1, sw2 = b'', 0x6A, 0x82
        print(f'SELECT {name.decode("ascii", errors="ignore")} -> SW={sw1:02X}{sw2:02X} DATA={to_hex(data)}')
        if (sw1, sw2) == (0x6A, 0x82):
            continue
        resp_bytes = bytes(data)
        if b'A0000000041010' in resp_bytes or b'A0000000031010' in resp_bytes:
            print('PPSE indicates tokenized wallet (e.g., Google Pay / tokenized app). Will not attempt to extract PAN.')
            result["tag_type"] = 'HCE/Tokenized (via PPSE)'
            result["tokenized"] = True
            result["identifiers"] = derive_identifiers(result["pan"], uid_hex, result["tokenized"], result["tag_type"], result["card_type"])
            return result

        try:
            def find_all_aids(b):
                result_list = []
                try:
                    parsed = parse_tlv(list(b))
                except Exception:
                    return result_list
                for tag, val in parsed.items():
                    if tag.upper() == '4F':
                        result_list.append(val)
                    else:
                        first_byte = int(tag[:2], 16)
                        if first_byte & 0x20:
                            result_list += find_all_aids(val)
                return result_list

            aid_list = find_all_aids(resp_bytes)
            for a in aid_list:
                candidate_aids.append(a)
        except Exception:
            pass
        if candidate_aids:
            break

    if not candidate_aids:
        candidate_aids = [
            bytes.fromhex('A0000000031010'),
            bytes.fromhex('A0000000032010'),
            bytes.fromhex('A0000000041010'),
            bytes.fromhex('A0000000043060'),
            bytes.fromhex('A00000002501'),
            bytes.fromhex('A0000001524040'),
            bytes.fromhex('A0000000651010'),
            bytes.fromhex('A000000333010101'),
            bytes.fromhex('A0000003241010'),
        ]

    pan = None
    expiry = None
    detected_issuer = None
    selected_aid = None

    for aid in candidate_aids:
        print(f'Trying AID {toHexString(list(aid))} ...')
        try:
            data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid))
        except Exception:
            continue
        print(f'  SELECT -> SW={sw1:02X}{sw2:02X} DATA={to_hex(data)}')
        if (sw1, sw2) == (0x67, 0x00):
            print('  Received 6700 (wrong params) — likely HCE token refusing standard SELECT. Skipping AID.')
            tokenized_hint = True
            continue
        if not (sw1 == 0x90 and sw2 == 0x00):
            continue
        selected_aid = aid
        for sfi in range(1, 16):
            for rec in range(1, 8):
                p2 = (sfi << 3) | 4
                apdu = [0x00, 0xB2, rec, p2, 0x00]
                try:
                    resp, rsw1, rsw2 = connection.transmit(apdu)
                except Exception:
                    continue
                if (rsw1, rsw2) != (0x90, 0x00):
                    continue
                resp_bytes = bytes(resp)
                v5a = find_tag_in_tlv_tree(resp_bytes, '5A')
                v57 = find_tag_in_tlv_tree(resp_bytes, '57')
                v5f24 = find_tag_in_tlv_tree(resp_bytes, '5F24')
                if v5a:
                    pan = ''.join(f'{b:02X}' for b in v5a).rstrip('F')
                    print(f'  Found 5A in SFI {sfi} rec {rec}: PAN={pan}')
                if v57 and not pan:
                    track2 = ''.join(f'{b:02X}' for b in v57)
                    if 'D' in track2:
                        pan = track2.split('D', 1)[0]
                        expiry = track2.split('D', 1)[1][:4]
                    elif 'F' in track2:
                        pan = track2.split('F', 1)[0]
                    print(f'  Found 57 in SFI {sfi} rec {rec}: track2={track2}')
                if v5f24 and not expiry:
                    expiry = ''.join(f'{b:02X}' for b in v5f24)
                    print(f'  Found 5F24 expiry: {expiry}')
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
    tag_type = None
    if pan:
        tag_type = 'EMV'
    else:
        tag_type, tokenized = detect_contactless_tag_type(connection, uid_hex, atr_hex_compact)
        if not tokenized:
            if tokenized_hint or (uid_hex is None and selected_aid is None and atr_card_type.upper().startswith('EMV')):
                tokenized = True
                if not tag_type or tag_type == 'Unknown':
                    tag_type = 'HCE/Tokenized (mobile wallet)'

    result["pan"] = pan
    result["expiry"] = expiry
    result["issuer"] = detected_issuer
    result["tag_type"] = tag_type or result["tag_type"] or 'Unknown'
    result["tokenized"] = tokenized or result["tokenized"]
    result["identifiers"] = derive_identifiers(result["pan"], uid_hex, result["tokenized"], result["tag_type"], result["card_type"])

    return result

# ---------- Helpers to attempt multiple connection modes ----------
def try_connect(connection):
    """
    Attempts connection in a few modes.
    Returns True if connected, False otherwise.
    """
    try:
        connection.connect()  # let pyscard select best protocol
        return True
    except Exception:
        pass
    try:
        connection.connect(protocol=SCARD_PROTOCOL_T0)
        return True
    except Exception:
        pass
    try:
        connection.connect(protocol=SCARD_PROTOCOL_T1)
        return True
    except Exception:
        pass
    return False

# ---------- Main ----------
def main():
    r = readers()
    if not r:
        print('No PC/SC readers found. Make sure reader is connected and PC/SC daemon/service is running.')
        sys.exit(1)

    # let user pick if multiple readers
    if len(r) > 1:
        print('Multiple readers found:')
        for i, reader in enumerate(r):
            print(f'  {i + 1}: {reader}')
        choice = input(f'Select reader (1-{len(r)}): ')
        try:
            reader = r[int(choice) - 1]
        except (ValueError, IndexError):
            print('Invalid choice, using first reader.')
            reader = r[0]
    else:
        reader = r[0]
    print('Using reader:', reader)
    connection = reader.createConnection()

    print('Waiting for card/tag (press Ctrl+C to cancel)...')
    try:
        connected = False
        # Try repeated connect attempts (handles insertion)
        while not connected:
            try:
                connected = try_connect(connection)
            except KeyboardInterrupt:
                raise
            except Exception:
                connected = False
            if not connected:
                time.sleep(0.5)

        # Print ATR if available
        try:
            atr = connection.getATR()
            print('Card ATR:', to_hex(atr))
        except Exception:
            print('Could not read ATR.')

        result = read_emv_pan_and_info(connection)

    except KeyboardInterrupt:
        print('\nCancelled by user.')
        sys.exit(1)
    except Exception as e:
        print('Failed to connect/read card:', e)
        sys.exit(1)

    print('\n--- Result ---')
    atr_display = result.get('atr_hex') or result.get('atr_hex_compact')
    if atr_display:
        print('ATR:', atr_display)
    print('Card type (ATR-derived):', result.get('card_type', 'Unknown'))
    tag_type = result.get('tag_type', 'Unknown')
    print('Tag type:', tag_type)

    tokenized = result.get('tokenized', False)
    if tokenized:
        print('Tokenized/HCE detected: True (identifiers suppressed)')

    uid = result.get('uid')
    if uid and not tokenized:
        print('UID:', uid)
    elif uid and tokenized:
        print('UID: Suppressed for tokenized cards')

    pan = result.get('pan')
    expiry = result.get('expiry')
    issuer = result.get('issuer')
    if pan:
        print('PAN:', pan)
        if expiry:
            print('Expiry (YYMM):', expiry)
        print('Issuer:', issuer or 'Unknown (try BIN lookup)')
    else:
        print('PAN not found (card may be tokenized/HCE, offline-only, locked, or non-EMV).')
        if issuer:
            print('Issuer hint:', issuer)

    identifiers = result.get('identifiers', {})
    if identifiers:
        print('Identifiers:')
        for key in ("primary", "secondary", "tertiary"):
            info = identifiers.get(key)
            if not info:
                continue
            print(f"  {info['type']}: {info['value']}")
    else:
        print('Identifiers: None (tokenized or unsupported)')

    atr_summary = result.get('atr_summary') or []
    if atr_summary:
        print('\nATR Analysis:')
        for line in atr_summary:
            print('  ' + line)
    print('--- End ---')

if __name__ == '__main__':
    main()
