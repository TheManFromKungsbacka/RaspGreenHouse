"""
test_all.py - Test every sensor and every output in one run.

Run on the Pi:   python3 test_all.py                  (sensors, then asks per relay)
                 python3 test_all.py --sensors-only   (no relays switched at all)
                 python3 test_all.py --yes            (switch all relays without asking)

Order of the tests:
  1. Temperature  - one reading from the DS18B20
  2. Moisture     - one reading from every sensor in config.py
  3. Camera       - takes one photo into photos/
  4. Relays       - light, fan, pump switched on for a few seconds each.
                    Before each one you are asked "y/N", so you can make sure
                    the pump hose points into a cup first. Just pressing Enter
                    skips that device.

Each test reports OK, PROBLEM or SKIPPED, and a summary is printed at the end.
One broken device does not stop the rest: every test catches its own errors.
For deeper testing of one device, use the separate test_*.py scripts.

The exit code is 0 if nothing failed and 1 otherwise, so later scripts (e.g.
a daily health check) can tell whether everything is fine.
"""

import os
import subprocess
import sys

from config import MOISTURE_SENSORS, PUMP_MIN_SECONDS, RELAY_PINS

# How long each output is switched on during the test, in seconds. The pump is
# kept short because it is powerful; the light and fan just need long enough
# to see and hear that they start.
RELAY_TEST_SECONDS = {"light": 3, "fan": 3, "pump": PUMP_MIN_SECONDS}

# Each test adds one entry here: (device, result, details). Printed at the end.
results = []


def report(device, result, details=""):
    """Print one test result straight away and remember it for the summary."""
    print("  -> {}: {} {}".format(device, result, details).rstrip())
    results.append((device, result, details))


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
# The hardware modules are imported inside each test, not at the top of the
# file. If one library is missing or broken (e.g. picamera), only that test
# fails instead of the whole script refusing to start.

def test_temperature():
    print("\n[1] Temperature (DS18B20)")
    try:
        from hardware.temperature import read_temperature
        celsius = read_temperature()
        # A working sensor indoors or in a greenhouse should be well inside
        # this range. Anything outside it suggests a fault, not real weather.
        if -20 <= celsius <= 60:
            report("temperature", "OK", "{:.2f} C".format(celsius))
        else:
            report("temperature", "PROBLEM", "{:.2f} C looks unrealistic".format(celsius))
    except Exception as err:
        report("temperature", "PROBLEM", str(err))


def test_moisture():
    print("\n[2] Soil moisture (MCP3008)")
    try:
        from hardware.moisture import read_moisture
    except Exception as err:
        report("moisture", "PROBLEM", str(err))
        return

    # Test each sensor separately, so one bad sensor is reported by name.
    for name, settings in MOISTURE_SENSORS.items():
        device = "moisture " + name
        try:
            raw, percent = read_moisture(name)
            details = "CH{} raw {} = {} %".format(settings["channel"], raw, percent)
            # Exactly 0 or 1023 almost always means a loose or missing wire:
            # the ADC input is then stuck at 0 V or 3.3 V.
            if raw in (0, 1023):
                report(device, "PROBLEM", details + " (stuck at the limit - check wiring)")
            else:
                report(device, "OK", details)
        except Exception as err:
            report(device, "PROBLEM", str(err))


def test_camera():
    print("\n[3] Camera")
    try:
        # Ask the firmware first: it gives a clear answer if the cable is loose.
        out = subprocess.run(["vcgencmd", "get_camera"], stdout=subprocess.PIPE,
                             universal_newlines=True).stdout.strip()
        if "detected=0" in out:
            report("camera", "PROBLEM", "not detected (" + out + ") - check the ribbon cable")
            return

        from hardware.camera import take_photo
        print("  taking a photo (about 3 s)...")
        path = take_photo()
        size_kb = os.path.getsize(path) // 1024
        report("camera", "OK", "{} ({} KB)".format(path, size_kb))
    except Exception as err:
        report("camera", "PROBLEM", str(err))


# ---------------------------------------------------------------------------
# Outputs (relays)
# ---------------------------------------------------------------------------

def ask(question):
    """Ask a yes/no question. Only 'y' or 'yes' counts as yes."""
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        # No keyboard attached (e.g. started from a script): treat as "no".
        return False


def test_relays(ask_first):
    print("\n[4] Relays (outputs)")
    try:
        from hardware import relays
        relays.setup()
    except Exception as err:
        report("relays", "PROBLEM", str(err))
        return

    # try/finally: whatever happens below - an error, Ctrl+C - every relay is
    # switched off and the GPIO pins are released before the script ends.
    try:
        for name, pin in RELAY_PINS.items():
            seconds = RELAY_TEST_SECONDS.get(name, 3)
            question = "  Switch {} (GPIO{}) ON for {} s?".format(name, pin, seconds)
            if name == "pump":
                question += " Have a cup ready!"

            if ask_first and not ask(question):
                report(name, "SKIPPED")
                continue

            print("  {} ON...".format(name))
            relays.run_for(name, seconds)

            # The Pi can only check that it commanded the relay; whether the
            # device really started is for you to see and hear, so we ask.
            if ask_first:
                if ask("  Did the {} start (relay click + device running)?".format(name)):
                    report(name, "OK")
                else:
                    report(name, "PROBLEM", "did not start - check wiring, pin and RELAY_ACTIVE_LOW")
            else:
                report(name, "OK", "switched (not confirmed by you)")
    finally:
        relays.cleanup()
        print("  All relays OFF.")


# ---------------------------------------------------------------------------
# Main: run everything, then print the summary
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sensors_only = "--sensors-only" in sys.argv
    ask_first = "--yes" not in sys.argv

    try:
        test_temperature()
        test_moisture()
        test_camera()
        if sensors_only:
            print("\n[4] Relays: skipped (--sensors-only)")
        else:
            test_relays(ask_first)
    except KeyboardInterrupt:
        print("\nStopped.")

    # Summary table: one line per device, problems easy to spot.
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for device, result, details in results:
        print("  {:<20} {:<8} {}".format(device, result, details))

    # ----- learn -----
    # `if __name__ == "__main__":` (above) means "only run this part when the
    # file is started directly (python3 test_all.py), not when another file
    # imports it". It lets a file be both a program and a collection of
    # functions. Every runnable file in this project ends this way.
    # `results` is a list of tuples (device, result, details). A tuple is a
    # fixed group of values; `for device, result, details in results` unpacks
    # each one into three names.
    # `sum(1 for r in results if r[1] == "PROBLEM")` counts matches: add 1 for
    # every result whose second item is "PROBLEM".
    # `sys.exit(1 if problems else 0)` gives the program an exit code: 0 means
    # success, anything else means failure. Other programs (and systemd) use
    # that number to know if it worked. A number that is 0 counts as False.
    # ----- end learn -----
    problems = sum(1 for r in results if r[1] == "PROBLEM")
    print("\n{} problem(s) found.".format(problems) if problems else "\nEverything tested works.")
    sys.exit(1 if problems else 0)
