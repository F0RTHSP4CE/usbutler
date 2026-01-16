#!/usr/bin/env python3
"""Simple GPIO toggle test script"""

import os
import sys
import time

try:
    import gpiod
    from gpiod.line import Direction, Value
except ImportError:
    print("❌ gpiod module not available")
    sys.exit(1)


def main():
    gpio_pin = int(os.getenv("USBUTLER_DOOR_GPIO", "17"))
    active_high = os.getenv("USBUTLER_DOOR_ACTIVE_HIGH", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }
    gpio_chip = os.getenv("USBUTLER_GPIO_CHIP", "/dev/gpiochip0")

    print(f"🔌 GPIO Test Script")
    print(f"   Chip: {gpio_chip}")
    print(f"   Pin: {gpio_pin}")
    print(f"   Mode: {'active-high' if active_high else 'active-low'}")
    print(f"\nPress Ctrl+C to stop\n")

    try:
        chip = gpiod.Chip(gpio_chip)
        line_settings = gpiod.LineSettings(direction=Direction.OUTPUT)
        line = chip.request_lines(
            config={gpio_pin: line_settings}, consumer="gpio-test"
        )

        print("✅ GPIO initialized successfully\n")

        state = False
        while True:
            # Toggle state
            state = not state

            if state:
                value = Value.ACTIVE if active_high else Value.INACTIVE
                print("🟢 GPIO ON")
            else:
                value = Value.INACTIVE if active_high else Value.ACTIVE
                print("🔴 GPIO OFF")

            line.set_value(gpio_pin, value)
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n\n👋 Stopping GPIO test")
        # Turn off before exit
        line.set_value(gpio_pin, Value.INACTIVE if active_high else Value.ACTIVE)
        line.release()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
