import sys
from smartcard.System import readers
from smartcard.util import toHexString

# --- APDU Commands ---
# Standard command to get UID (for non-EMV cards like MIFARE)
GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
# Command to SELECT the Proximity Payment System Environment (PPSE)
# This is the standard way to start communication with an EMV card.
SELECT_PPSE = [0x00, 0xA4, 0x04, 0x00, 0x0E, 0x32, 0x50, 0x41, 0x59, 0x2E, 0x53, 0x59, 0x53, 0x2E, 0x44, 0x44, 0x46, 0x30, 0x31, 0x00]

# --- Known Application Identifiers (AIDs) ---
# We only need the Registered Application Provider Identifier (RID), which are the first 5 bytes.
AID_ISSUER_MAP = {
    # Issuer: RID (Hex)
    "Visa":         "A000000003",
    "Mastercard":   "A000000004",
    "Amex":         "A000000025",
    "UnionPay":     "A000000333",
    "JCB":          "A000000065",
    "Discover":     "A000000152",
    "Mir":          "A000000658",
}

def identify_card(connection):
    """
    Identifies the card by first attempting an EMV transaction.
    If it fails, it treats the card as a non-EMV (NFC) tag.
    """
    print("\n--- Card Detected ---")
    
    # 1. Try to select the payment application (PPSE) to check if it's an EMV card.
    data, sw1, sw2 = connection.transmit(SELECT_PPSE)
    
    # Check if the command was successful (status word 90 00)
    if sw1 == 0x90 and sw2 == 0x00:
        print("✅ Type: EMV Payment Card")
        response_hex = toHexString(data).replace(" ", "")
        
        # Look for a known issuer RID in the card's response
        for issuer, rid in AID_ISSUER_MAP.items():
            if rid in response_hex:
                print(f"💳 Issuer: {issuer}")
                return # Exit after finding the first match

        print("🔍 Issuer: Unknown EMV Card")
        return

    # 2. If selecting PPSE fails (e.g., status 6A 82: "File not found"),
    # it's not a payment card. Treat it as a standard NFC tag.
    elif sw1 == 0x6A and sw2 == 0x82:
        print("❌ Type: Non-EMV Card (e.g., MIFARE, NTAG)")
        # Try the original command to get the UID
        try:
            data, sw1, sw2 = connection.transmit(GET_UID)
            if sw1 == 0x90 and sw2 == 0x00:
                uid = toHexString(data)
                print(f"🆔 UID: {uid}")
            else:
                print(f"Could not retrieve UID. Status: {sw1:02X} {sw2:02X}")
        except Exception as e:
            print(f"Error getting UID: {e}")
        return
    
    # Handle other unexpected responses
    else:
        print(f"⚠️ Unknown card type or communication error.")
        print(f"Response Status: {sw1:02X} {sw2:02X}")

### Main Execution Logic
def main():
    try:
        reader_list = readers()
        if not reader_list:
            print("Error: No card readers found!")
            sys.exit()

        reader = reader_list[0]
        print(f"Using reader: {reader}")

        while True:
            try:
                connection = reader.createConnection()
                connection.connect()
                
                # This call blocks until a card is presented
                print("\nWaiting for a card...")
                connection.wait_for_card()
                identify_card(connection)
                
                # This call blocks until the card is removed
                connection.wait_for_card_remove()
                print("--- Card Removed ---")

            except Exception:
                # This exception often occurs if a card is removed unexpectedly.
                # The loop will simply restart and wait for the next card.
                pass

    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    finally:
        sys.exit()

if __name__ == "__main__":
    main()