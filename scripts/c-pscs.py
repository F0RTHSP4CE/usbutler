#!/usr/bin/env python3
"""
read_emv_pan_full_with_contact.py

Requires: pyscard
Run with Python 3.

Features added compared to previous:
 - Expanded AID -> issuer mappings (many common AIDs included).
 - Attempts explicit contact connection protocols (T=0, T=1) if needed.
 - All previous EMV, tag-type, UID, HCE-detection functionality retained.
"""

import sys
import time
from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.scard import SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1

# ---------- TLV parsing helpers ----------
def parse_tlv(data):
    """Simple BER-TLV parser returning dict of tag(hex)->value(bytes).
    Input: iterable/list of ints or bytes -> returns dict of 'TAG'->bytes.
    """
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
    # Common card payment AIDs (prefix matching)
    # Visa family
    'A000000003': 'Visa',
    'A0000000031010': 'Visa Credit/Debit',
    'A0000000032010': 'Visa Electron',
    'A0000000033010': 'VPay',
    # Mastercard family
    'A000000004': 'Mastercard',
    'A0000000041010': 'Mastercard Credit/Debit',
    'A0000000043060': 'Maestro (Mastercard network)',
    # American Express
    'A000000025': 'American Express',
    'A00000002501': 'American Express',
    # Discover / Diners / JCB / UnionPay / MIR
    'A000000152': 'Discover',
    'A000000042': 'Diners Club / Discover',
    'A000000065': 'JCB',
    'A000000333': 'UnionPay',
    'A000000324': 'MIR',
    # Additional / regional or known AIDs (examples)
    'A000000632': 'Test / example (not real)',
    'A000000524': 'Some region-specific AID',
    # add other specific known AIDs if you want...
}

def issuer_from_aid(aid_bytes):
    """Infer issuer from AID bytes using prefix matching against AID_ISSUER_MAP."""
    aid_hex = toHexString(list(aid_bytes)).replace(' ', '')
    # try longest-prefix match
    best = None
    for prefix, name in AID_ISSUER_MAP.items():
        if aid_hex.upper().startswith(prefix.upper()):
            # prefer longest matching prefix
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, name)
    return best[1] if best else None

def issuer_from_pan(pan):
    """Heuristic BIN/IIN -> issuer inference from PAN digits."""
    if not pan or len(pan) < 2:
        return None
    # Visa
    if pan.startswith('4'):
        return 'Visa'
    # Amex
    if pan.startswith('34') or pan.startswith('37'):
        return 'American Express'
    # Mastercard 51-55
    try:
        if 51 <= int(pan[:2]) <= 55:
            return 'Mastercard'
    except Exception:
        pass
    # Mastercard 2221-2720
    try:
        if len(pan) >= 6:
            prefix6 = int(pan[:6])
            if 222100 <= prefix6 <= 272099:
                return 'Mastercard'
    except Exception:
        pass
    # MIR (2200-2204)
    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 2200 <= prefix4 <= 2204:
                return 'MIR'
    except Exception:
        pass
    # UnionPay (62)
    if pan.startswith('62'):
        return 'UnionPay'
    # Discover (6011, 65, 64x, 622126-622925)
    if pan.startswith('6011') or pan.startswith('65') or pan.startswith('64') or pan.startswith('622'):
        return 'Discover/UnionPay (check BIN)'
    # JCB (3528-3589)
    try:
        if len(pan) >= 4:
            prefix4 = int(pan[:4])
            if 3528 <= prefix4 <= 3589:
                return 'JCB'
    except Exception:
        pass
    return None

# ---------- The main combined function ----------
def read_emv_pan_and_info(connection):
    """
    Attempts to read PAN and expiry, detect issuer, tag type and UID.
    Returns: (pan_or_None, expiry_or_None, issuer_or_None, tag_type_or_None, uid_or_None)
    tag_type: 'EMV' | 'MIFARE Classic (likely)' | 'NTAG/Type2 (likely)' | 'Type4/NDEF (likely)' | 'Unknown'
    """
    uid_hex = None
    tag_type = None

    # 0) Try to get UID via reader-specific GET UID (FF CA 00 00 00) — supported by many readers (ACR122U)
    try:
        resp, sw1, sw2 = connection.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if (sw1, sw2) == (0x90, 0x00) or sw1 == 0x91:
            uid_bytes = bytes(resp)
            uid_hex = ''.join(f'{b:02X}' for b in uid_bytes)
        else:
            uid_hex = None
    except Exception:
        uid_hex = None

    # If UID present, attempt a conservative classification
    if uid_hex:
        try:
            # SELECT NDEF Tag Application AID (Type 4)
            ndef_aid = bytes.fromhex('D2760000850101')
            data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(ndef_aid)] + list(ndef_aid))
            if (sw1, sw2) == (0x90, 0x00):
                tag_type = 'Type4/NDEF (likely)'
            else:
                # conservative probe: try to read a raw block (FF B0 ...). If success, inspect content
                try:
                    resp2, sw1b, sw2b = connection.transmit([0xFF, 0xB0, 0x00, 0x00, 0x10])
                    if (sw1b, sw2b) == (0x90, 0x00):
                        raw0 = bytes(resp2)
                        raw0_hex = ''.join(f'{b:02X}' for b in raw0)
                        if raw0_hex.startswith('E1') or b'\xE1' in raw0:
                            tag_type = 'NTAG/Type2 (likely)'
                        else:
                            tag_type = 'MIFARE Classic (likely)'
                    else:
                        tag_type = 'Contactless (UID present, exact type unknown)'
                except Exception:
                    tag_type = 'Contactless (UID present, exact type unknown)'
        except Exception:
            tag_type = 'Contactless (UID present, exact type unknown)'
    else:
        tag_type = None

    # 1) ATR-based quick check for mobile-wallet HCE (avoid trying to extract DPAN)
    try:
        atr = connection.getATR()
        atr_hex = ''.join(f'{b:02X}' for b in atr)
    except Exception:
        atr_hex = ''

    hce_atr_prefixes = ['3B8F80018031', '3B8F80018066', '3B80800101', '3B8F8001804F0C']
    if any(atr_hex.startswith(p) for p in hce_atr_prefixes):
        print(f'Card ATR: {atr_hex} (HCE/mobile-wallet pattern detected)')
        return None, None, None, tag_type or 'Unknown', uid_hex

    # 2) EMV discovery (PPSE / PSE)
    ppse = b'2PAY.SYS.DDF01'
    pse = b'1PAY.SYS.DDF01'
    candidate_aids = []

    for name in (ppse, pse):
        try:
            data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(name)] + list(name))
        except Exception:
            data, sw1, sw2 = b'', 0x6A, 0x82
        print(f'SELECT {name.decode("ascii", errors="ignore")} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}')
        if (sw1, sw2) == (0x6A, 0x82):
            continue
        resp_bytes = bytes(data)
        # Detect tokenized wallet inside PPSE
        if b'A0000000041010' in resp_bytes or b'A0000000031010' in resp_bytes:
            print('PPSE indicates tokenized wallet (e.g., Google Pay). Will not attempt to extract PAN.')
            return None, None, None, tag_type or 'Unknown', uid_hex
        # parse FCI for AIDs
        try:
            def find_all_aids(b):
                result = []
                try:
                    parsed = parse_tlv(list(b))
                except Exception:
                    return result
                for tag, val in parsed.items():
                    if tag.upper() == '4F':
                        result.append(val)
                    else:
                        first_byte = int(tag[:2], 16)
                        if first_byte & 0x20:
                            result += find_all_aids(val)
                return result
            aid_list = find_all_aids(resp_bytes)
            for a in aid_list:
                candidate_aids.append(a)
        except Exception:
            pass
        if candidate_aids:
            break

    # 3) Fallback common AIDs (expanded list)
    if not candidate_aids:
        candidate_aids = [
            bytes.fromhex('A0000000031010'),  # Visa
            bytes.fromhex('A0000000032010'),  # Visa Electron / VPay
            bytes.fromhex('A0000000041010'),  # Mastercard
            bytes.fromhex('A0000000043060'),  # Maestro (Mastercard)
            bytes.fromhex('A00000002501'),    # Amex
            bytes.fromhex('A0000001524040'),  # Discover (example)
            bytes.fromhex('A0000000651010'),  # JCB example
            bytes.fromhex('A000000333010101'),# UnionPay example
            bytes.fromhex('A0000003241010'),  # MIR example
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
        print(f'  SELECT -> SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}')
        if (sw1, sw2) == (0x67, 0x00):
            print('  Received 6700 (wrong params) — likely HCE token refusing standard SELECT. Skipping AID.')
            continue
        if not (sw1 == 0x90 and sw2 == 0x00):
            continue
        selected_aid = aid
        # read records for PAN & expiry
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
                        pan = track2.split('D',1)[0]
                        expiry = track2.split('D',1)[1][:4]
                    elif 'F' in track2:
                        pan = track2.split('F',1)[0]
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

    # Determine issuer preference: AID -> PAN
    if selected_aid:
        detected_issuer = issuer_from_aid(selected_aid)
    if not detected_issuer and pan:
        detected_issuer = issuer_from_pan(pan)

    if pan:
        tag_type = 'EMV'

    return pan, expiry, detected_issuer, tag_type or 'Unknown', uid_hex

# ---------- Helpers to attempt multiple connection modes ----------
def try_connect(connection):
    """
    Attempts connection in a few modes.
    Returns True if connected, False otherwise.
    """
    # Try default connect
    try:
        connection.connect()  # let pyscard select best protocol
        return True
    except Exception:
        pass
    # Try explicit T=0 then T=1 if supported
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
            print('Card ATR:', toHexString(atr))
        except Exception:
            print('Could not read ATR.')

        pan, expiry, issuer, tag_type, uid = read_emv_pan_and_info(connection)

    except KeyboardInterrupt:
        print('\nCancelled by user.')
        sys.exit(1)
    except Exception as e:
        print('Failed to connect/read card:', e)
        sys.exit(1)

    print('\n--- Result ---')
    if uid:
        print('UID:', uid)
    print('Tag type:', tag_type)
    if pan:
        print('PAN:', pan)
        if expiry:
            print('Expiry (YYMM):', expiry)
        print('Issuer:', issuer or 'Unknown (try BIN lookup)')
    else:
        print('PAN not found (card may be tokenized/HCE, offline-only, locked, or non-EMV).')
        if issuer:
            print('Issuer hint:', issuer)
    print('--- End ---')

if __name__ == '__main__':
    main()
