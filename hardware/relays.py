"""
relays.py - Switch the UV light, water pump and fan on and off.

How it works
------------
Each device is powered through a relay: an electrically controlled switch.
The Pi's GPIO pin controls the relay's coil, and the relay's contacts switch
the device's own power supply. The Pi never powers the pump or fan directly.

Your relay board is "active low" (see config.py): pin LOW = relay ON.
To keep the rest of the code free of that confusing detail, this module
offers plain functions like turn_on("pump") and works out LOW/HIGH itself.

Typical use:
    from hardware import relays
    relays.setup()
    relays.turn_on("fan")
    ...
    relays.cleanup()   # always at the end: everything off
"""

import threading
import time

import RPi.GPIO as GPIO

from config import PUMP_MAX_SECONDS, PUMP_MIN_SECONDS, RELAY_ACTIVE_LOW, RELAY_PINS

# Translate "on" / "off" into the pin level the relay board needs.
ON_LEVEL = GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH
OFF_LEVEL = GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW
# ----- learn -----
# `A if condition else B` is a one-line choice. These two lines are the whole
# reason the rest of the code can ignore "active low": we decide ONCE here
# what "on" means electrically, and everything else says turn_on / turn_off.
# This is called an abstraction: hiding an ugly detail behind a clear name.
# ----- end learn -----


def setup():
    """Prepare all relay pins as outputs, starting in the OFF state.

    `initial=OFF_LEVEL` matters: without it the pin may briefly go LOW while
    being set up, which on an active-low board would click every relay ON for
    a moment. (The old green.py had exactly this problem: its relaystatus()
    called GPIO.setup() each time the web page loaded, which could switch the
    relays on just by viewing the page.)
    """
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in RELAY_PINS.values():
        GPIO.setup(pin, GPIO.OUT, initial=OFF_LEVEL)


def _pin(name):
    """Look up the GPIO pin for a device name, with a helpful error if misspelt."""
    if name not in RELAY_PINS:
        raise ValueError(
            "Unknown device '" + name + "'. Choose one of: " + ", ".join(RELAY_PINS)
        )
    return RELAY_PINS[name]


# Safety timer for the pump. Whenever the pump is switched on, a background
# timer is started that switches it off again after PUMP_MAX_SECONDS. Because
# it lives here in turn_on() and not only in run_for(), the limit holds for
# EVERY way of starting the pump: run_for(), the interactive menu, or any
# future script that calls turn_on("pump") directly and forgets to turn it off.
_pump_timer = None


def _pump_timeout():
    """Called by the timer thread when the pump has run for too long."""
    print("Pump switched off automatically after", PUMP_MAX_SECONDS, "s (PUMP_MAX_SECONDS in config.py)")
    GPIO.output(RELAY_PINS["pump"], OFF_LEVEL)


def _cancel_pump_timer():
    global _pump_timer
    if _pump_timer is not None:
        _pump_timer.cancel()
        _pump_timer = None


def turn_on(name):
    global _pump_timer
    if name == "pump":
        # Restart the timer rather than stacking a second one.
        _cancel_pump_timer()
        # daemon=True so a waiting timer never keeps the program from exiting.
        _pump_timer = threading.Timer(PUMP_MAX_SECONDS, _pump_timeout)
        _pump_timer.daemon = True
        _pump_timer.start()
    GPIO.output(_pin(name), ON_LEVEL)
    # ----- learn -----
    # threading.Timer runs a function later, on its own "thread": a second
    # track of execution that runs in parallel with the main program. Here it
    # is a safety net: even if the main program freezes, 25 s later the timer
    # still switches the pump off.
    # `global _pump_timer` (first line of this function) is needed because we
    # ASSIGN to a variable that lives outside the function. Without it Python
    # would create a new local variable with the same name.
    # The leading underscore (_pump_timer, _pin) is a naming habit meaning
    # "internal, other files should not use this".
    # ----- end learn -----


def turn_off(name):
    if name == "pump":
        _cancel_pump_timer()
    GPIO.output(_pin(name), OFF_LEVEL)


def is_on(name):
    """True if the device is currently switched on.

    Reading an output pin returns the level we last set it to, so this tells
    us what the Pi is commanding, not whether the pump physically spins.
    """
    return GPIO.input(_pin(name)) == ON_LEVEL


def status():
    """Return a dict like {"light": False, "pump": False, "fan": True}."""
    return {name: is_on(name) for name in RELAY_PINS}


def all_off():
    for name in RELAY_PINS:
        turn_off(name)


def run_for(name, seconds):
    """Switch a device on for a number of seconds, then off again.

    The `try/finally` guarantees the device is switched off even if the
    program is interrupted (Ctrl+C) or crashes during the wait.
    The pump run time is kept between PUMP_MIN_SECONDS and PUMP_MAX_SECONDS
    from config.py: too short and the weak pump delivers no water, too long
    and it risks flooding.
    """
    if name == "pump":
        if seconds > PUMP_MAX_SECONDS:
            print("Pump time capped at", PUMP_MAX_SECONDS, "s (PUMP_MAX_SECONDS in config.py)")
            seconds = PUMP_MAX_SECONDS
        elif seconds < PUMP_MIN_SECONDS:
            print("Pump time raised to", PUMP_MIN_SECONDS, "s (PUMP_MIN_SECONDS in config.py)")
            seconds = PUMP_MIN_SECONDS

    turn_on(name)
    try:
        time.sleep(seconds)
    finally:
        turn_off(name)
    # ----- learn -----
    # `finally:` runs NO MATTER HOW the try block ends: normally, by an error,
    # or by Ctrl+C. Use it for "must always happen" cleanup. Here, no matter
    # what goes wrong during the wait, the device is switched off afterwards.
    # ----- end learn -----


def cleanup():
    """Switch everything off and release the GPIO pins. Call this on exit."""
    all_off()
    GPIO.cleanup()
