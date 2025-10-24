"""
This script uses an ACR122U NFC reader to identify the type of a contactless card.

It uses an advanced ATR (Answer to Reset) parser, inspired by the logic from
tools like Proxmark, to provide detailed information about the card and a more
accurate identification.

Requirements:
- An ACR122U (or compatible PC/SC) reader.
- The appropriate drivers for your reader installed.
- The `pyscard` library: pip install pyscard
"""

import sys
from smartcard.System import readers
from smartcard.util import toHexString

# A dictionary mapping known ATR prefixes to card types. This is a first-pass check.
ATR_MAP = {
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 01": "Mifare Classic 1K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 02": "Mifare Classic 4K",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 03": "Mifare Ultralight or Ultralight C",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 31": "NTAG213",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 32": "NTAG215",
    "3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 33": "NTAG216",
}

def parse_atr(atr_bytes):
    """
    Parses a raw ATR byte array into a structured dictionary, following ISO/IEC 7816-3.
    This provides a detailed breakdown of the card's reported capabilities.
    
    Args:
        atr_bytes (list): A list of integers representing the ATR bytes.
        
    Returns:
        dict: A dictionary containing the parsed ATR information.
    """
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
        "protocol": "T=0", # Default protocol
        "summary": []
    }

    # TS (Initial Character)
    parsed_data["ts"] = f"{atr_bytes[0]:02X}"
    if atr_bytes[0] == 0x3B:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Direct Convention)")
    elif atr_bytes[0] == 0x3F:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Inverse Convention)")
    else:
        parsed_data["summary"].append(f"TS: {parsed_data['ts']} (Unknown Convention)")

    if len(atr_bytes) < 2:
        return parsed_data

    # T0 (Format Character)
    t0 = atr_bytes[1]
    parsed_data["t0"] = f"{t0:02X}"
    num_historical_bytes = t0 & 0x0F
    parsed_data["summary"].append(f"T0: {parsed_data['t0']}, K = {num_historical_bytes} (historical bytes)")

    # Pointers and state
    i = 2
    y_indicator = t0 >> 4
    protocol_t = 0
    interface_char_index = 1

    # Parse Interface Characters (TA, TB, TC, TD)
    while True:
        if y_indicator & 0x01: # TA(i) present
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TA{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else: break
        if y_indicator & 0x02: # TB(i) present
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TB{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else: break
        if y_indicator & 0x04: # TC(i) present
            if i < len(atr_bytes):
                parsed_data["interface_chars"][f"TC{interface_char_index}"] = f"{atr_bytes[i]:02X}"
                i += 1
            else: break
        if y_indicator & 0x08: # TD(i) present
            if i < len(atr_bytes):
                td = atr_bytes[i]
                parsed_data["interface_chars"][f"TD{interface_char_index}"] = f"{td:02X}"
                y_indicator = td >> 4
                protocol_t = td & 0x0F
                interface_char_index += 1
                i += 1
            else: break
        else:
            break # No more TD bytes, loop ends

    parsed_data['protocol'] = f"T={protocol_t}"
    parsed_data["summary"].append(f"Protocol: T={protocol_t}")

    # Extract Historical Bytes
    historical_start_index = i
    historical_end_index = historical_start_index + num_historical_bytes
    if historical_end_index <= len(atr_bytes):
        historical = atr_bytes[historical_start_index:historical_end_index]
        parsed_data["historical_bytes_hex"] = toHexString(historical)
        parsed_data["summary"].append(f"Historical Bytes: {parsed_data['historical_bytes_hex']}")
        i = historical_end_index
    
    # Checksum (TCK) - only present if T > 0
    if protocol_t > 0 and i < len(atr_bytes):
        tck = atr_bytes[i]
        parsed_data["tck"] = f"{tck:02X}"
        
        # XOR all bytes from T0 up to and including TCK
        checksum = 0
        for byte_val in atr_bytes[1:i+1]:
            checksum ^= byte_val
        
        if checksum == 0:
            parsed_data["tck_valid"] = True
            parsed_data["summary"].append(f"TCK: {parsed_data['tck']} (Valid)")
        else:
            parsed_data["tck_valid"] = False
            parsed_data["summary"].append(f"TCK: {parsed_data['tck']} (Invalid!)")

    return parsed_data

def identify_card_type(parsed_atr):
    """
    Identifies the card type from the parsed ATR data.
    
    Args:
        parsed_atr (dict): The structured data from the parse_atr function.
        
    Returns:
        str: The identified card type or "Unknown".
    """
    atr_hex = parsed_atr.get("raw_atr_hex", "")
    historical_hex = parsed_atr.get("historical_bytes_hex", "")

    # 1. Check direct matches from our simple map for common cards.
    for known_atr, card_type in ATR_MAP.items():
        if atr_hex.startswith(known_atr):
            return card_type

    # 2. Analyze historical bytes and protocol for more complex cards.
    # ISO/IEC 7816-4 defines the structure of historical bytes.
    # For contactless cards (PICCs), the Category Indicator '80' is common.
    if historical_hex.startswith("80"):
        # A strong indicator of a PICC that supports ISO 14443-4 (T=CL)
        return "EMV or ISO 14443-4 Compliant Card (e.g., DESFire)"

    # 3. Fallback checks based on protocol and other patterns
    if parsed_atr.get('protocol') in ['T=1', 'T=15']:
        return "EMV Card (Visa, Mastercard, etc.)"
    
    if "71 D5" in atr_hex or "77 D5" in atr_hex:
        return "EMV Card (Likely)"

    return "Unknown Card Type"

def main():
    """
    Main function to connect to the reader and poll for cards.
    """
    try:
        r = readers()
        if not r:
            print("Error: No readers found! Is the PC/SC service running?")
            sys.exit()

        reader = r[0]
        print(f"Using reader: {reader}")

        while True:
            try:
                connection = reader.createConnection()
                print("\n---> Waiting for card...")
                connection.connect()
                
                atr_bytes = connection.getATR()
                atr_hex = toHexString(atr_bytes)
                
                print(f"\n[+] Raw ATR: {atr_hex}")
                print("="*40)
                
                parsed_atr = parse_atr(atr_bytes)
                
                print("[+] ATR Analysis:")
                for line in parsed_atr.get("summary", []):
                    print(f"    {line}")
                if parsed_atr.get("interface_chars"):
                    print("    Interface Chars:", " ".join([f"{k}:{v}" for k,v in parsed_atr["interface_chars"].items()]))
                
                card_type = identify_card_type(parsed_atr)
                print("="*40)
                print(f"[+] Identified Card Type: {card_type}")

                print("\n<--- Please remove the card.")
                while connection.getATR():
                    pass

            except Exception as e:
                # This exception often signals card removal.
                if 'Card is not connected' in str(e) or 'Card removal' in str(e):
                    continue
                else:
                    print(f"An error occurred: {e}")
                    import time
                    time.sleep(2)

    except KeyboardInterrupt:
        print("\nExiting program.")
        sys.exit()
    except Exception as e:
        print(f"A critical error occurred: {e}")
        print("Please ensure the PC/SC service is running and the reader is connected.")
        sys.exit()

if __name__ == "__main__":
    main()

