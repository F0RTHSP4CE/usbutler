import sys
import argparse
from smartcard.System import readers
from smartcard.util import toHexString

# APDU commands for ACR122U
# This command sets the PICC operating parameters.
# Setting the P2 byte to 0x00 disables the buzzer for card detection.
# Setting the P2 byte to 0xFF enables it.
DISABLE_BUZZER_APDU = [0xFF, 0x00, 0x52, 0x00, 0x00]
ENABLE_BUZZER_APDU = [0xFF, 0x00, 0x52, 0xFF, 0x00]

# This command controls the LED state.
# The 5-byte pseudo-APDU for this is known to be unreliable on some
# firmwares, causing the program to hang. We use the more robust 9-byte
# command that explicitly sets the final LED state.
# P2 byte: Controls which LEDs to update and their final state.
# 0x0D = Update Red, Final state: ON; Update Green, Final state: OFF
# 0x0C = Update Red, Final state: OFF; Update Green, Final state: OFF
# Lc = 0x04, followed by 4 data bytes for blinking patterns (set to 0 for solid state).
LED_OFF_APDU = [0xFF, 0x00, 0x40, 0x0C, 0x04, 0x00, 0x00, 0x00, 0x00]
LED_ON_APDU = [0xFF, 0x00, 0x40, 0x0D, 0x04, 0x00, 0x00, 0x00, 0x00]


def main():
    """
    Main function to connect to the ACR122U reader and enable/disable the
    LED and buzzer based on command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Control the LED and buzzer on an ACR122U reader."
    )
    parser.add_argument(
        "action",
        choices=["enable", "disable"],
        help="Action to perform: 'enable' or 'disable' the LED and buzzer."
    )
    args = parser.parse_args()

    if args.action == "enable":
        buzzer_apdu = ENABLE_BUZZER_APDU
        led_apdu = LED_ON_APDU
        buzzer_action_str = "enable"
        led_action_str = "turn on"
    else:  # disable
        buzzer_apdu = DISABLE_BUZZER_APDU
        led_apdu = LED_OFF_APDU
        buzzer_action_str = "disable"
        led_action_str = "turn off"

    connection = None
    try:
        # Get a list of available readers
        r = readers()
        if not r:
            print("Error: No readers found!")
            sys.exit()

        # Connect to the first reader
        reader = r[0]
        print(f"Found reader: {reader}")

        connection = reader.createConnection()
        connection.connect()

        # 1. Enable/Disable the buzzer for card detection events
        print(f"Sending command to {buzzer_action_str} buzzer: {toHexString(buzzer_apdu)}")
        data, sw1, sw2 = connection.transmit(buzzer_apdu)
        print(f"Response: SW1={sw1:02X}, SW2={sw2:02X}")

        if sw1 == 0x90 and sw2 == 0x00:
            print(f"Buzzer {buzzer_action_str}d successfully.")
        else:
            print(f"Failed to {buzzer_action_str} buzzer.")

        # 2. Turn on/off the LED
        print(f"\nSending command to {led_action_str} LED: {toHexString(led_apdu)}")
        data, sw1, sw2 = connection.transmit(led_apdu)
        print(f"Response: SW1={sw1:02X}, SW2={sw2:02X}")

        if sw1 == 0x90 and sw2 == 0x00:
            # A bit of string manipulation to make the output grammatically correct
            # e.g., "turned on" -> "turnedon" is not ideal. "turned off" -> "turnedoff" is ok.
            # A simple replace works for "turn on" -> "turnedon", but let's be more robust
            if ' ' in led_action_str:
                verb, preposition = led_action_str.split(' ')
                action_past_tense = f"{verb}ed {preposition}"
            else:
                action_past_tense = f"{led_action_str}ed"
            print(f"LED {action_past_tense} successfully.")
        else:
            print(f"Failed to {led_action_str} LED.")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please ensure your reader is connected and the PC/SC service is running.")

    finally:
        # Clean up the connection
        if connection:
            connection.disconnect()
            print("\nConnection closed.")


if __name__ == "__main__":
    main()

