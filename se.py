#!/usr/bin/env python3
"""
read_emv_pan_gpo.py

Reads PAN/expiry from EMV cards by:
 - selecting PPSE/PSE or common AIDs
 - selecting an AID
 - sending GET PROCESSING OPTIONS (GPO)
 - parsing AFL and READ RECORD for PAN/57/5F24
"""

import sys
import time
from smartcard.System import readers
from smartcard.util import toHexString

# ---------- TLV helpers ----------
def parse_tlv(data):
    """Simple BER-TLV parser returning dict tag->value (bytes)."""
    i = 0
    n = len(data)
    tlv = {}
    while i < n:
        tag = data[i]
        i += 1
        # multi-byte tag
        if (tag & 0x1F) == 0x1F:
            tag_bytes = [tag]
            while True:
                if i >= n:
                    raise ValueError("truncated tag")
                b = data[i]; tag_bytes.append(b); i += 1
                if not (b & 0x80):
                    break
            tag_hex = ''.join(f'{b:02X}' for b in tag_bytes)
        else:
            tag_hex = f'{tag:02X}'
        if i >= n:
            raise ValueError("truncated length")
        length = data[i]; i += 1
        if length & 0x80:
            num = length & 0x7F
            length = 0
            if i + num > n:
                raise ValueError("truncated length bytes")
            for _ in range(num):
                length = (length << 8) + data[i]; i += 1
        if i + length > n:
            raise ValueError("truncated value")
        value = bytes(data[i:i+length]); i += length
        tlv[tag_hex.upper()] = value
    return tlv

def find_tag_in_tlv_tree(tlv_bytes, tag_hex):
    """Recursively find a tag (like '5A' or '57') inside TLV bytes."""
    try:
        parsed = parse_tlv(list(tlv_bytes))
    except Exception:
        return None
    tag_hex = tag_hex.upper()
    if tag_hex in parsed:
        return parsed[tag_hex]
    for k, v in parsed.items():
        try:
            first = int(k[:2], 16)
        except Exception:
            continue
        if first & 0x20:  # constructed
            found = find_tag_in_tlv_tree(v, tag_hex)
            if found:
                return found
    return None

# ---------- Issuer helpers ----------
AID_ISSUER_MAP = {
    'A000000003': 'Visa',
    'A0000000031010': 'Visa',
    'A000000004': 'Mastercard',
    'A0000000041010': 'Mastercard',
    'A0000000043060': 'Maestro/Mastercard',
    'A000000025': 'American Express',
    'A000000152': 'Discover',
    'A000000065': 'JCB',
    'A000000333': 'UnionPay',
    'A000000324': 'MIR',
}

def issuer_from_aid(aid_bytes):
    aid_hex = toHexString(list(aid_bytes)).replace(' ', '').upper()
    best = None
    for prefix, name in AID_ISSUER_MAP.items():
        if aid_hex.startswith(prefix):
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
        two = int(pan[:2])
        if 51 <= two <= 55:
            return 'Mastercard'
    except Exception:
        pass
    try:
        if len(pan) >= 6:
            six = int(pan[:6])
            if 222100 <= six <= 272099:
                return 'Mastercard'
    except Exception:
        pass
    if pan.startswith('62'):
        return 'UnionPay'
    try:
        four = int(pan[:4])
        if 3528 <= four <= 3589:
            return 'JCB'
    except Exception:
        pass
    try:
        if len(pan) >= 4:
            if 2200 <= int(pan[:4]) <= 2204:
                return 'MIR'
    except Exception:
        pass
    return None

# ---------- APDU helpers ----------
def transmit(connection, apdu, desc=None):
    try:
        resp, sw1, sw2 = connection.transmit(apdu)
    except Exception as e:
        print(f"APDU {apdu} -> ERROR: {e}")
        return None, None, None
    if desc:
        print(f"{desc:<40} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
    else:
        print(f"APDU {toHexString(apdu)} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
    return bytes(resp), sw1, sw2

# ---------- EMV flow ----------
COMMON_AIDS = [
    bytes.fromhex('A0000000031010'),  # Visa
    bytes.fromhex('A0000000041010'),  # Mastercard
    bytes.fromhex('A00000002501'),    # Amex
    bytes.fromhex('A000000333010101'),# UnionPay example
    bytes.fromhex('A0000003241010'),  # MIR example
]

def get_processing_options(connection):
    """Send GPO with empty PDOL (83 00) and return response bytes and SW."""
    # GPO template: 80 A8 00 00 Lc 83 00  (Le omitted)
    apdu = [0x80, 0xA8, 0x00, 0x00, 0x02, 0x83, 0x00]
    data, sw1, sw2 = connection.transmit(apdu)
    print(f"GPO -> SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}")
    return bytes(data), sw1, sw2

def parse_gpo_for_afl(gpo_resp_bytes):
    """Accepts raw GPO response bytes and returns AFL bytes (or None)."""
    # gpo_resp_bytes may be:
    # - tag '80' primitive: [AIP(2) | AFL(n)]
    # - tag '77' constructed containing '82'(AIP) and '94'(AFL)
    if not gpo_resp_bytes:
        return None
    # Try TLV parse
    try:
        parsed = parse_tlv(list(gpo_resp_bytes))
        if '94' in parsed:
            return parsed['94']
        # maybe response is 80 primitive: first two bytes AIP, rest AFL
    except Exception:
        pass
    # fallback: if length >= 4, treat bytes[2:] as AFL (after AIP(2))
    if len(gpo_resp_bytes) >= 4:
        # if first byte is 0x80 it's primitive form
        # treat as AIP(2) + AFL
        return gpo_resp_bytes[2:]
    return None

def parse_afl_and_read_records(connection, afl_bytes):
    """Parse AFL (sequence of 4-byte entries) and READ RECORD for each record.
       Returns list of raw record bytes found.
    """
    if not afl_bytes:
        return []
    records = []
    # AFL is multiple of 4
    n = len(afl_bytes)
    if n % 4 != 0:
        print("Warning: AFL length not multiple of 4; trying to parse anyway.")
    for i in range(0, n, 4):
        if i + 4 > n:
            break
        entry = afl_bytes[i:i+4]
        # entry[0] contains SFI in upper 5 bits (SFI = entry[0] >> 3)
        sfi = entry[0] >> 3
        first_rec = entry[1]
        last_rec = entry[2]
        # entry[3] is number of records for offline auth (ignore)
        for rec in range(first_rec, last_rec + 1):
            p2 = (sfi << 3) | 4
            apdu = [0x00, 0xB2, rec, p2, 0x00]
            resp, sw1, sw2 = connection.transmit(apdu)
            print(f"READ RECORD SFI={sfi} REC={rec} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
            if (sw1, sw2) == (0x90, 0x00) and resp:
                records.append(bytes(resp))
    return records

def extract_pan_expiry_from_records(records):
    """Look for tags 5A, 57, 5F24 in records and return (pan, expiry)."""
    pan = None
    expiry = None
    for rec in records:
        v5a = find_tag_in_tlv_tree(rec, '5A')
        v57 = find_tag_in_tlv_tree(rec, '57')
        v5f24 = find_tag_in_tlv_tree(rec, '5F24')
        if v5a and not pan:
            pan = ''.join(f'{b:02X}' for b in v5a).rstrip('F')
        if v57 and not pan:
            track2 = ''.join(f'{b:02X}' for b in v57)
            if 'D' in track2:
                pan = track2.split('D',1)[0]
                if len(track2) >= len(pan) + 5:
                    expiry = track2[len(pan) + 1: len(pan) + 5]
            elif 'F' in track2:
                pan = track2.split('F',1)[0]
        if v5f24 and not expiry:
            expiry = ''.join(f'{b:02X}' for b in v5f24)
        if pan:
            # keep scanning in case expiry not set yet
            continue
    return pan, expiry

def select_aid_and_read_pan(connection, aid):
    """Select AID, do GPO, parse AFL, read records and extract PAN/expiry."""
    # SELECT by name
    apdu = [0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid)
    resp, sw1, sw2 = connection.transmit(apdu)
    print(f"SELECT AID {toHexString(list(aid))} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
    if (sw1, sw2) == (0x6D, 0x00):
        print("SELECT returned 6D00 (INS not supported) - AID not selectable on this card/reader.")
        return None, None, None
    if not (sw1 == 0x90 and sw2 == 0x00) and sw1 != 0x61 and sw1 != 0x6C:
        # some cards return 61xx; we will not handle extended-get-response here.
        print("SELECT AID non-success; continuing.")
    # If SW=61xx we could GET RESPONSE, but many cards return 9000 w/data directly on SELECT
    # Now GPO
    gpo_resp, gpo_sw1, gpo_sw2 = get_processing_options(connection)
    if (gpo_sw1, gpo_sw2) not in ((0x90,0x00), (0x61,0x00), (0x6F,0x00)):
        # some cards may ask for PDOL; but many accept empty PDOL
        print("GPO not successful or returned unusual SW; trying alternate GPO with zero PDOL done above.")
    afl = parse_gpo_for_afl(gpo_resp)
    if afl is None or len(afl) == 0:
        print("No AFL found in GPO response; trying READ RECORD brute-force (SFI 1..10, rec 1..16).")
        records = []
        for sfi in range(1, 11):
            for rec in range(1, 17):
                p2 = (sfi << 3) | 4
                apdu = [0x00, 0xB2, rec, p2, 0x00]
                resp, sw1, sw2 = connection.transmit(apdu)
                print(f"READ RECORD SFI={sfi} REC={rec} -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
                if (sw1, sw2) == (0x90, 0x00) and resp:
                    records.append(bytes(resp))
    else:
        print(f"AFL bytes: {toHexString(list(afl))}")
        records = parse_afl_and_read_records(connection, afl)
    pan, expiry = extract_pan_expiry_from_records(records)
    return pan, expiry, records

# ---------- High-level reading function ----------
def read_emv_pan(connection):
    """
    Top-level: find AID via PPSE/PSE or common list, select, GPO, READ RECORD, return pan, expiry, aid
    """
    ppse = bytes("2PAY.SYS.DDF01", "ascii")
    pse  = bytes("1PAY.SYS.DDF01", "ascii")
    candidate_aids = []

    # Try PPSE
    apdu_ppse = [0x00, 0xA4, 0x04, 0x00, len(ppse)] + list(ppse)
    resp, sw1, sw2 = connection.transmit(apdu_ppse)
    print(f"SELECT PPSE -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
    if (sw1, sw2) == (0x90, 0x00) and resp:
        # parse for AIDs (tag 4F occurrences)
        try:
            parsed = parse_tlv(list(resp))
            # recursively find 4F
            def find_all_aids(b):
                res = []
                try:
                    p = parse_tlv(list(b))
                except Exception:
                    return res
                for tag, val in p.items():
                    if tag.upper() == '4F':
                        res.append(val)
                    else:
                        first = int(tag[:2], 16)
                        if first & 0x20:
                            res += find_all_aids(val)
                return res
            candidate_aids = find_all_aids(resp)
            if candidate_aids:
                print("AIDs found in PPSE:")
                for a in candidate_aids:
                    print(" -", toHexString(list(a)))
        except Exception:
            candidate_aids = []
    else:
        print("PPSE not present or not returning AIDs.")

    # If no AIDs from PPSE, try PSE (contact)
    if not candidate_aids:
        apdu_pse = [0x00, 0xA4, 0x04, 0x00, len(pse)] + list(pse)
        resp, sw1, sw2 = connection.transmit(apdu_pse)
        print(f"SELECT PSE -> SW={sw1:02X}{sw2:02X} DATA={toHexString(resp)}")
        if (sw1, sw2) == (0x90, 0x00) and resp:
            try:
                parsed = parse_tlv(list(resp))
                def find_all_aids(b):
                    res = []
                    try:
                        p = parse_tlv(list(b))
                    except Exception:
                        return res
                    for tag, val in p.items():
                        if tag.upper() == '4F':
                            res.append(val)
                        else:
                            first = int(tag[:2], 16)
                            if first & 0x20:
                                res += find_all_aids(val)
                    return res
                candidate_aids = find_all_aids(resp)
            except Exception:
                candidate_aids = []

    # fallback to common aids
    if not candidate_aids:
        candidate_aids = COMMON_AIDS
        print("Using fallback common AIDs")

    # try each aid
    for aid in candidate_aids:
        pan, expiry = None, None
        pan, expiry, records = (None, None, None)
        try:
            pan, expiry, records = select_aid_and_read_pan(connection, aid)
        except Exception as e:
            print("Error selecting/reading AID:", e)
        if pan:
            issuer = issuer_from_aid(aid) or issuer_from_pan(pan)
            return pan, expiry, issuer, toHexString(list(aid))
    return None, None, None, None

# ---------- Main ----------
def main():
    r = readers()
    if not r:
        print("No PC/SC readers found.")
        sys.exit(1)
    print("Readers:")
    for i, rd in enumerate(r):
        print(f"  [{i}] {rd}")
    try:
        idx = 0 if len(r) == 1 else int(input("Select reader index: "))
    except Exception:
        idx = 0
    reader = r[idx]
    print("Using reader:", reader)
    conn = reader.createConnection()
    # try connect with both protocols
    from smartcard.scard import SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1
    try:
        conn.connect(protocol=SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1)
    except Exception:
        try:
            conn.connect()
        except Exception as e:
            print("Connection failed:", e)
            sys.exit(1)
    print("Protocol:", conn.getProtocol(), "ATR:", toHexString(conn.getATR()))

    pan, expiry, issuer, aid_hex = read_emv_pan(conn)

    print("\n=== Result ===")
    if pan:
        print("PAN:", pan)
        if expiry:
            print("Expiry (YYMM):", expiry)
        print("Issuer:", issuer or "Unknown")
        print("AID:", aid_hex)
    else:
        print("PAN not found. Card may be tokenized/HCE, offline-only, locked, or not an EMV payment card.")
    print("=== End ===")

if __name__ == '__main__':
    main()
