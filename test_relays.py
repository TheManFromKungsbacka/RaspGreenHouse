"""
test_relays.py - Check the UV light, pump and fan relays one at a time.

Two ways to use it:

  1. Quick test of one device, switched on for a few seconds:
         python3 test_relays.py light        (on for 3 s)
         python3 test_relays.py fan 10       (on for 10 s)
         python3 test_relays.py pump         (on for at least 10 s - have a cup ready!)

  2. Interactive menu where you switch things on and off yourself:
         python3 test_relays.py

Whatever happens - normal exit, Ctrl+C or an error - everything is switched
OFF at the end (the `finally:` blocks below take care of that).

What to check: you should hear the relay click and see its LED change, and
the device itself should start. If the WRONG device starts, swap the pin
numbers in RELAY_PINS in config.py. If a device runs when it should be off,
set RELAY_ACTIVE_LOW = False in config.py.
"""

import sys

from config import RELAY_PINS
from hardware import relays


def quick_test(name, seconds):
    """Mode 1: switch one device on for a fixed time."""
    print("Switching {} (GPIO{}) ON for {} s...".format(name, RELAY_PINS[name], seconds))
    relays.run_for(name, seconds)
    print("{} is OFF again.".format(name))


def show_status():
    for name, on in relays.status().items():
        print("  {:<6} (GPIO{:>2}): {}".format(name, RELAY_PINS[name], "ON" if on else "off"))


def interactive_menu():
    """Mode 2: a small text menu. Type a device name to toggle it on/off."""
    names = list(RELAY_PINS)
    print("Type a device name to toggle it, 'off' for all off, 'q' to quit.")
    print("Devices:", ", ".join(names))
    while True:
        print()
        show_status()
        choice = input("> ").strip().lower()

        if choice in ("q", "quit", "exit"):
            break
        elif choice == "off":
            relays.all_off()
        elif choice in names:
            # Toggle: on becomes off, off becomes on.
            if relays.is_on(choice):
                relays.turn_off(choice)
            else:
                relays.turn_on(choice)
        else:
            print("Unknown command:", choice)


if __name__ == "__main__":
    relays.setup()
    try:
        if len(sys.argv) > 1:
            name = sys.argv[1].lower()
            if name not in RELAY_PINS:
                print("Unknown device '{}'. Choose one of: {}".format(name, ", ".join(RELAY_PINS)))
                sys.exit(1)
            seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 3
            quick_test(name, seconds)
        else:
            interactive_menu()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        relays.cleanup()
        print("All relays OFF.")
