# read_emv_pan.py
# Requires: pyscard
# Tested conceptually with ACR122U (uses PC/SC). Run with Python 3.

from smartcard.System import readers
from smartcard.util import toHexString, toBytes
import sys
import time

# ---------- TLV parsing helpers ----------
def parse_tlv(data):
    """Simple TLV parser returning dict of tag(hex)->value(bytes).
       Supports multi-byte tags and lengths per BER-TLV (basic)."""
    i = 0
    tlv = {}
    n = len(data)
    while i < n:
        # tag
        tag_start = i
        tag = data[i]
        i += 1
        # multi-byte tag
        if (tag & 0x1F) == 0x1F:
            tag_bytes = [tag]
            while True:
                b = data[i]
                tag_bytes.append(b)
                i += 1
                if not (b & 0x80):
                    break
            tag_hex = ''.join(f'{b:02X}' for b in tag_bytes)
        else:
            tag_hex = f'{tag:02X}'

        # length
        length = data[i]
        i += 1
        if length & 0x80:
            num_len_bytes = length & 0x7F
            length = 0
            for _ in range(num_len_bytes):
                length = (length << 8) + data[i]
                i += 1

        # value
        value = bytes(data[i:i+length])
        i += length

        tlv[tag_hex] = value
    return tlv

def find_tag_in_tlv_tree(tlv_bytes, tag_hex):
    """Recursively search TLV bytes for a tag (tag_hex like '5A' or '57')."""
    try:
        tlv = parse_tlv(list(tlv_bytes))
    except Exception:
        return None
    if tag_hex in tlv:
        return tlv[tag_hex]
    # search inside constructed tags
    for k, v in tlv.items():
        # if constructed (first byte indicates constructed bit), try recursively
        first_tag_byte = int(k[:2], 16)
        if first_tag_byte & 0x20:  # constructed
            found = find_tag_in_tlv_tree(v, tag_hex)
            if found:
                return found
    return None

# ---------- APDU helpers ----------
def send_apdu(connection, apdu, desc=None):
    data, sw1, sw2 = connection.transmit(apdu)
    sw = (sw1 << 8) | sw2
    if desc:
        print(f'--> {desc}: {toHexString(apdu)}')
        print(f'<-- SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}')
    return bytes(data), sw1, sw2

def select_by_name(connection, name_bytes):
    # SELECT by name (P2 = 0x04 for select by name), CLA=0x00, INS=0xA4
    lc = len(name_bytes)
    apdu = [0x00, 0xA4, 0x04, 0x00, lc] + list(name_bytes)
    data, sw1, sw2 = connection.transmit(apdu)
    return bytes(data), sw1, sw2

def select_aid(connection, aid_bytes):
    lc = len(aid_bytes)
    apdu = [0x00, 0xA4, 0x04, 0x00, lc] + list(aid_bytes)
    return connection.transmit(apdu)

# ---------- Main EMV reading flow ----------
def read_emv_pan(connection):
    """
    Attempts to read PAN and expiry from an EMV card via PC/SC connection.
    Handles both contact and contactless cards.
    Detects and skips Google Pay / tokenized wallets (HCE emulation)
    using both ATR and APDU response patterns.
    """

    from smartcard.util import toHexString

    # --- Detect mobile wallet by ATR before sending any APDUs ---
    atr = connection.getATR()
    atr_hex = ''.join(f'{b:02X}' for b in atr)
    print(f"Card ATR: {atr_hex}")

    # Common ATR patterns for Android HCE / Google Pay virtual cards
    hce_atr_patterns = [
        "3B8F80018031",     # generic HCE prefix
        "3B8F8001804F0CA000000306030001",  # seen on some Samsung/Pixel devices
        "3B8F8001806680",   # common ACR122U + Android combo
        "3B80800101",       # generic minimal ATR from phone emulation
    ]
    if any(atr_hex.startswith(p) for p in hce_atr_patterns):
        print("⚠️  Detected mobile wallet (HCE emulation / Google Pay).")
        print("   These do not expose real EMV PAN data outside payment transactions.")
        return None, None

    # --- Begin normal EMV discovery flow ---
    ppse = b'2PAY.SYS.DDF01'  # contactless directory
    pse  = b'1PAY.SYS.DDF01'  # contact directory
    candidate_dirs = []

    for name, label in [(ppse, 'PPSE (2PAY.SYS.DDF01)'), (pse, 'PSE (1PAY.SYS.DDF01)')]:
        print(f'\nSelecting directory {label} ...')
        data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(name)] + list(name))
        print(f'<-- SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}')

        if (sw1, sw2) == (0x6A, 0x82):
            print(f'{label} not found (SW={sw1:02X}{sw2:02X})')
            continue

        resp_bytes = bytes(data)

        # --- Detect Google Pay / tokenized wallet from FCI content ---
        if b'A0000000041010' in resp_bytes or b'A0000000031010' in resp_bytes:
            print("⚠️  Detected possible mobile wallet (Google Pay / tokenized card).")
            print("   Mobile wallets never expose real PAN via APDU — skipping read.")
            return None, None
        # -------------------------------------------------------------

        # Parse FCI and extract AIDs recursively
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
        except Exception:
            aid_list = []

        if aid_list:
            print('Found AIDs in directory:')
            for aid in aid_list:
                print(' -', toHexString(list(aid)))
                candidate_dirs.append(aid)
            break

    # --- If no AIDs found, try common ones ---
    if not candidate_dirs:
        print('No AIDs found; trying common Visa/Mastercard/Amex...')
        candidate_dirs = [
            bytes.fromhex('A0000000031010'),  # Visa
            bytes.fromhex('A0000000041010'),  # Mastercard
            bytes.fromhex('A00000002501'),    # Amex
        ]

    # --- Iterate through AIDs ---
    for aid in candidate_dirs:
        print(f'\nSelecting AID {toHexString(list(aid))} ...')
        data, sw1, sw2 = connection.transmit([0x00, 0xA4, 0x04, 0x00, len(aid)] + list(aid))
        print(f'<-- SW={sw1:02X}{sw2:02X} DATA={toHexString(data)}')

        if (sw1, sw2) == (0x67, 0x00):
            print("⚠️  Wrong parameters (6700) — likely mobile wallet / HCE token. Skipping.")
            continue
        if not (sw1 == 0x90 and sw2 == 0x00):
            print('Select AID failed or returned non-success; trying next AID.')
            continue

        # --- Try reading records ---
        pan = None
        expiry = None
        for sfi in range(1, 16):
            for rec in range(1, 8):
                p2 = (sfi << 3) | 4
                apdu = [0x00, 0xB2, rec, p2, 0x00]
                try:
                    resp, sw1, sw2 = connection.transmit(apdu)
                except Exception:
                    continue

                if (sw1, sw2) == (0x90, 0x00):
                    resp_bytes = bytes(resp)
                    v5a = find_tag_in_tlv_tree(resp_bytes, '5A')
                    v57 = find_tag_in_tlv_tree(resp_bytes, '57')
                    v5f24 = find_tag_in_tlv_tree(resp_bytes, '5F24')

                    if v5a:
                        pan = ''.join(f'{b:02X}' for b in v5a).rstrip('F')
                        print(f'Found tag 5A in SFI {sfi}, record {rec}: {pan}')

                    if v57 and not pan:
                        track2 = ''.join(f'{b:02X}' for b in v57)
                        if 'D' in track2:
                            pan = track2.split('D', 1)[0]
                            expiry = track2.split('D', 1)[1][:4]
                        elif 'F' in track2:
                            pan = track2.split('F', 1)[0]
                        print(f'Found tag 57 in SFI {sfi}, record {rec}: track2={track2}')

                    if v5f24 and not expiry:
                        expiry = ''.join(f'{b:02X}' for b in v5f24)
                        print(f'Found expiry (5F24): {expiry}')

                    if pan:
                        return pan, expiry

    print("No PAN found — card may be locked, offline, or tokenized.")
    return None, None

def main():
    r = readers()
    if not r:
        print('No PC/SC readers found. Make sure ACR122U is connected and PCSC daemon/service is running.')
        sys.exit(1)
    # pick first reader (you might want to list & choose)
    reader = r[0]
    print('Using reader:', reader)
    connection = reader.createConnection()
    # Wait until a card is present. connection.connect() raises if no card is inserted,
    # so retry with a short sleep. Allow user to cancel with Ctrl+C.
    print('Waiting for card insertion (press Ctrl+C to cancel)...')
    try:
        while True:
            try:
                connection.connect()  # may require protocol T=0/T=1 - pyscard handles it
                break
            except Exception:
                # No card yet or temporary error — wait and retry
                time.sleep(0.5)

        # show ATR
        atr = connection.getATR()
        print('Card ATR:', toHexString(atr))

        pan, expiry = read_emv_pan(connection)
    except KeyboardInterrupt:
        print('\nCancelled by user.')
        sys.exit(1)
    except Exception as e:
        print('Failed to connect/read card:', e)
        sys.exit(1)
    if pan:
        print('\n=== PAN FOUND ===')
        print('PAN:', pan)
        if expiry:
            print('Expiry (YYMM):', expiry)
    else:
        print('\nPAN not found. Card may be locked, offline-only, or not an EMV payment app.')

if __name__ == '__main__':
    main()
