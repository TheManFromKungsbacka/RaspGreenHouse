"""
greenhouse.py - The daily program that runs the greenhouse on its own.

Every second it looks at the clock, the latest temperature and any manual
commands from the web page, and decides:

    grow light   on between LIGHT_ON_TIME and LIGHT_OFF_TIME
    fan          on when too hot (FAN_ON_TEMP), off when cooled (FAN_OFF_TEMP),
                 plus FAN_CIRCULATE_MINUTES at the start of every hour for fresh air
    pump         WATER_SECONDS at WATER_TIME, every WATER_EVERY_DAYS days
    camera       one photo a day at PHOTO_TIME

Sensors are read every SENSOR_EVERY_SECONDS, readings are written to
logs/readings.csv every LOG_INTERVAL_MINUTES, and the current state is written
to status.json for the web page. All numbers live in config.py.

Manual control from the web page (see statefiles.py):
    overrides.json      light/fan forced on or off until a set time
    pump_request.json   "water now for N seconds" or "stop the pump"
This program is the ONLY one that switches relays, so its safety rules (pump
10-25 s, overrides expire) apply to manual commands too.

Run on the Pi:
    python3 greenhouse.py              run for real (normally started by systemd)
    python3 greenhouse.py --dry-run    only PRINT what it would do, no relays switched
    python3 greenhouse.py --dry-run --once   one round of decisions, then stop

Important design choices:
  - The light and fan are worked out from the clock and temperature every
    round, not remembered. So after a power cut or restart, the right devices
    simply come back on by themselves.
  - Watering and the photo are remembered in state.json, so a restart in the
    middle of the morning never waters twice on the same day.
  - Every error (a loose sensor, a camera problem) is logged and the program
    carries on: one broken device must not stop the light or the watering.
"""

import csv
import os
import signal
import sys
import time
from datetime import datetime, timedelta

import config
from statefiles import log_event as log
from statefiles import read_json, write_json

TICK_SECONDS = 1           # how often decisions are made (fast reaction to the web page)
SENSOR_EVERY_SECONDS = 30  # how often the sensors are read

# A scheduled job (watering, photo) is still done if the program starts up to
# this long after its time, e.g. after a reboot at 07:50. Later than that it is
# skipped for the day rather than watering at an odd hour.
LATE_START_WINDOW = timedelta(minutes=60)

DRY_RUN = "--dry-run" in sys.argv
ONCE = "--once" in sys.argv


# ---------------------------------------------------------------------------
# Outputs: the real relays, or a stand-in that only prints (--dry-run)
# ---------------------------------------------------------------------------

class DryRunRelays:
    """Pretends to be hardware/relays.py: remembers the state, switches nothing."""

    def __init__(self):
        self.state = {name: False for name in config.RELAY_PINS}

    def setup(self):
        pass

    def is_on(self, name):
        return self.state[name]

    def turn_on(self, name):
        self.state[name] = True

    def turn_off(self, name):
        self.state[name] = False

    def cleanup(self):
        pass


if DRY_RUN:
    relays = DryRunRelays()
else:
    from hardware import relays
# ----- learn -----
# After these lines the name `relays` means EITHER the fake or the real thing,
# and the rest of the file just calls relays.turn_on("fan") without caring.
# Both offer the same methods (setup, is_on, turn_on, turn_off, cleanup), so
# they are interchangeable. This is "duck typing": if it has the right
# methods, it can be used.
# Why bother? The real relays import RPi.GPIO, which only exists on a Pi, and
# a dry run must not switch real hardware. Now you can test the program's
# decisions on your PC or on the Pi without touching anything.
# `DRY_RUN = "--dry-run" in sys.argv` works because sys.argv is the list of
# words typed on the command line; `in` asks "is it in the list?" (True/False).
# ----- end learn -----


# What each output is doing and why, shown on the web page. Filled in by the
# control functions every round, e.g.
#   {"light": {"mode": "auto", "reason": "schedule 06:00-20:00", "until": None}}
output_info = {}

# Set to True whenever something changes, so status.json is rewritten at once
# instead of waiting for the next sensor read.
status_dirty = True


def set_device(name, want_on, reason):
    """Switch a device only if it is not already in the wanted state, and log why.

    Only logging real changes keeps events.log short and readable: you see
    "fan ON (too hot: 28.4 C)" once, not every second.
    """
    global status_dirty
    if relays.is_on(name) == want_on:
        return
    if want_on:
        relays.turn_on(name)
    else:
        relays.turn_off(name)
    log("{} {} ({})".format(name, "ON" if want_on else "off", reason))
    status_dirty = True
    # ----- learn -----
    # This is the most important small function in the program. Every device
    # change goes through it, so there is exactly ONE place that switches
    # things and writes to the log.
    # The first `if ... return` is a "guard": leave early when there is nothing
    # to do. Because decisions are made every second, this keeps the log free
    # of "light ON" repeated 3600 times an hour.
    # "{} {} ({})".format(a, b, c) fills the {} holes in order with a, b, c.
    # `global status_dirty` lets the function change a variable defined outside
    # it; the main loop looks at the flag to know it must rewrite status.json.
    # ----- end learn -----


# ---------------------------------------------------------------------------
# Helpers for times and remembered state
# ---------------------------------------------------------------------------

def at_time(hhmm, day):
    """Turn "07:00" into a full datetime on the given day."""
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes)


def in_daily_window(now, start_hhmm, end_hhmm):
    """True if the clock time of `now` is between start and end.

    Also handles windows that cross midnight, e.g. 20:00-06:00.
    """
    start = at_time(start_hhmm, now).time()
    end = at_time(end_hhmm, now).time()
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end
    # ----- learn -----
    # A window like 06:00-20:00 is easy: start <= now < end. A window that
    # crosses midnight (20:00-06:00) is not, because "now" can be after the
    # start OR before the end, but never both. Handling both shapes here means
    # nobody has to remember the special case later.
    # `a <= t < b` is Python's chained comparison: both must be true.
    # The end is "<" and not "<=" so that at exactly 20:00 the light is off.
    # ----- end learn -----


def job_is_due(now, hhmm, last_done):
    """True if a once-a-day job at `hhmm` should run now and has not run today."""
    scheduled = at_time(hhmm, now)
    already_done = last_done == now.date().isoformat()
    return not already_done and scheduled <= now < scheduled + LATE_START_WINDOW
    # ----- learn -----
    # A function that returns True/False is called a predicate. The name reads
    # like a question: job_is_due(...). Good names make the calling code read
    # like English: `if not job_is_due(now, config.PHOTO_TIME, ...): return`.
    # Why not just "now == scheduled"? The loop runs once a second and a
    # restart can happen at any moment, so we ask "are we inside the window
    # that starts at the scheduled time?" instead of "is it exactly 07:30:00?".
    # Dates are stored as text like "2026-10-25" (isoformat) so they can be
    # saved in the JSON file and compared with ==.
    # ----- end learn -----


def is_water_day(day):
    # Counting days since a fixed date (rather than "N days after the last
    # watering") keeps the rhythm steady even if a watering was missed.
    return day.toordinal() % config.WATER_EVERY_DAYS == 0


def next_watering(now, state):
    """When the next scheduled watering will happen, for the web page."""
    for days_ahead in range(config.WATER_EVERY_DAYS + 1):
        day = now + timedelta(days=days_ahead)
        if not is_water_day(day):
            continue
        scheduled = at_time(config.WATER_TIME, day)
        if days_ahead == 0 and (state.get("last_watered") == now.date().isoformat()
                                or now >= scheduled + LATE_START_WINDOW):
            continue  # today's watering is already done or missed
        return scheduled
    return None


def load_state():
    return read_json(config.STATE_FILE, {})  # {} on first run or a damaged file


def save_state(state):
    if DRY_RUN:
        return  # a dry run must not stop the real program from watering today
    write_json(config.STATE_FILE, state)


# ---------------------------------------------------------------------------
# Sensors - each read is protected so a failing sensor is logged, not fatal
# ---------------------------------------------------------------------------

def read_temperature():
    try:
        from hardware.temperature import read_temperature as read
        return read()
    except Exception as err:
        log("WARNING temperature sensor: {}".format(err))
        return None


def read_moisture():
    try:
        from hardware.moisture import read_all
        return read_all()
    except Exception as err:
        log("WARNING moisture sensors: {}".format(err))
        return {}


# ---------------------------------------------------------------------------
# Manual commands from the web page
# ---------------------------------------------------------------------------

def read_overrides(now):
    """Return the manual overrides that are still valid, e.g.
    {"fan": {"on": True, "until": datetime, "user": "admin"}}.

    Expired overrides are simply ignored: the device goes back to automatic.
    """
    active = {}
    for name, o in (read_json(config.OVERRIDE_FILE, {}) or {}).items():
        try:
            until = datetime.strptime(o["until"], "%Y-%m-%dT%H:%M:%S")
        except (KeyError, TypeError, ValueError):
            continue
        if name in ("light", "fan") and until > now:
            active[name] = {"on": bool(o.get("on")), "until": until, "user": o.get("user", "?")}
    return active


def apply_override(name, override):
    """Switch a device as the web page asked. Returns True if an override applied."""
    if override is None:
        return False
    until = override["until"].strftime("%H:%M")
    reason = "manual by {} until {}".format(override["user"], until)
    set_device(name, override["on"], reason)
    output_info[name] = {"mode": "manual", "reason": reason, "until": override["until"].isoformat()}
    return True


# ---------------------------------------------------------------------------
# The decisions, one function per device
# ---------------------------------------------------------------------------

def control_light(now, overrides):
    if apply_override("light", overrides.get("light")):
        return
    on = in_daily_window(now, config.LIGHT_ON_TIME, config.LIGHT_OFF_TIME)
    reason = "schedule {}-{}".format(config.LIGHT_ON_TIME, config.LIGHT_OFF_TIME)
    set_device("light", on, reason)
    output_info["light"] = {"mode": "auto", "reason": reason, "until": None}


def control_fan(now, temp, cooling, overrides):
    """Decide the fan. Returns the new `cooling` flag (True = cooling because hot).

    `cooling` is what makes the gap between FAN_ON_TEMP and FAN_OFF_TEMP work:
    at 26 C the fan stays on if we were already cooling, and stays off if not.
    """
    if temp is not None:
        if temp >= config.FAN_ON_TEMP:
            cooling = True
        elif temp <= config.FAN_OFF_TEMP:
            cooling = False
    # If the sensor fails, `cooling` keeps its last value: the safest guess.
    # ----- learn -----
    # This is hysteresis, the thing a thermostat does. Two thresholds
    # (28 on, 25 off) and a remembered flag. Trace it with the temperature
    # rising and falling: 24 off, 27 off (below 28), 28.1 ON, 26 ON (above 25,
    # so no change), 24.9 off. Without the gap the fan would flick on and off
    # around 28 and wear out the relay.
    # The function receives `cooling` and RETURNS the new value, and the
    # caller stores it (`cooling = control_fan(...)`). That is how state is
    # passed along without a global variable.
    # `if / elif / else` checks conditions top to bottom; only the first true
    # branch runs, and when none match nothing changes.
    # ----- end learn -----

    if apply_override("fan", overrides.get("fan")):
        return cooling

    if cooling:
        on, reason = True, "too hot: {} C".format(temp)
    elif now.minute < config.FAN_CIRCULATE_MINUTES:
        on, reason = True, "air circulation, {} min every hour".format(config.FAN_CIRCULATE_MINUTES)
    else:
        on, reason = False, "temperature {} C, circulation done".format(temp)
    set_device("fan", on, reason)
    output_info["fan"] = {"mode": "auto", "reason": reason, "until": None}
    return cooling


# The pump does not block the program while it runs: we switch it on, remember
# when it must stop, and check every second. The light, fan and web page keep
# working during watering. (relays.py has its own PUMP_MAX_SECONDS timer as a
# second line of defence.)
pump_until = None


def start_pump(now, seconds, reason, mode):
    global pump_until
    seconds = max(config.PUMP_MIN_SECONDS, min(config.PUMP_MAX_SECONDS, seconds))
    # ----- learn -----
    # "Clamping": force a number into a range. min(25, x) caps it at 25, then
    # max(10, ...) lifts it to at least 10. Whatever is asked for (5, 20 or
    # 9999), the result is between 10 and 25. This line is why a mistaken or
    # malicious request cannot run the pump too long.
    # Notice that the pump is started here by setting `pump_until` (a time)
    # and returning at once. The program does NOT wait for the pump. Each
    # second check_pump() compares now with pump_until and stops the pump when
    # the time has passed. Compare with time.sleep(20), which would freeze
    # everything else for 20 seconds.
    # ----- end learn -----
    pump_until = now.replace(microsecond=0) + timedelta(seconds=seconds)
    set_device("pump", True, "{}, {} s".format(reason, seconds))
    output_info["pump"] = {"mode": mode, "reason": reason, "until": pump_until.isoformat()}


def stop_pump(reason):
    global pump_until
    pump_until = None
    set_device("pump", False, reason)
    output_info["pump"] = {"mode": "auto", "reason": "idle", "until": None}


def check_pump(now):
    if pump_until is not None and now >= pump_until:
        stop_pump("watering done")
    elif pump_until is None and relays.is_on("pump"):
        stop_pump("not expected to be on")  # e.g. switched on by something else
    elif pump_until is None:
        output_info["pump"] = {"mode": "auto", "reason": "idle", "until": None}


def handle_pump_request(now):
    """Carry out a "water now" or "stop" request from the web page, once."""
    request = read_json(config.PUMP_REQUEST_FILE)
    if request is None:
        return
    try:
        os.remove(config.PUMP_REQUEST_FILE)  # each request is carried out only once
    except OSError:
        pass

    user = request.get("user", "?")
    try:
        made_at = datetime.strptime(request["time"], "%Y-%m-%dT%H:%M:%S")
    except (KeyError, TypeError, ValueError):
        log("WARNING ignored a damaged pump request")
        return
    if (now - made_at).total_seconds() > config.PUMP_REQUEST_MAX_AGE_SECONDS:
        log("ignored an old pump request from {} (made {})".format(user, request["time"]))
        return

    if request.get("stop"):
        stop_pump("stopped by {}".format(user))
    else:
        seconds = int(request.get("seconds", config.PUMP_MIN_SECONDS))
        start_pump(now, seconds, "manual by {}".format(user), "manual")


def control_watering(now, state, moisture):
    if not is_water_day(now) or not job_is_due(now, config.WATER_TIME, state.get("last_watered")):
        return
    readings = ", ".join("{} {} %".format(n, p) for n, (raw, p) in moisture.items())
    log("scheduled watering (moisture before: {})".format(readings or "unknown"))
    # Remember it BEFORE pumping: if the program crashes during the pump run,
    # it will not pump again after the restart.
    state["last_watered"] = now.date().isoformat()
    save_state(state)
    start_pump(now, config.WATER_SECONDS, "scheduled watering", "auto")
    # ----- learn -----
    # Read the first line of this function as a list of reasons to do nothing:
    # not a watering day, OR not yet/no longer due. Starting a function with
    # "if not X: return" keeps the real work at the left edge instead of
    # buried in nested ifs.
    # `", ".join("{} {} %".format(n, p) for n, (raw, p) in moisture.items())`
    # builds a text like "sensor1 40 %, sensor2 43 %". `for n, (raw, p) in
    # ...items()` unpacks each pair: the key goes into n, and the value, which
    # is itself a pair (raw, percent), is split into raw and p.
    # The order matters: save to disk FIRST, then start the pump. If the order
    # were reversed, a crash during pumping would lead to a second watering.
    # ----- end learn -----


def control_photo(now, state):
    if not job_is_due(now, config.PHOTO_TIME, state.get("last_photo")):
        return
    state["last_photo"] = now.date().isoformat()
    save_state(state)
    if DRY_RUN:
        log("  (dry run: would take the daily photo)")
        return
    try:
        from hardware.camera import take_photo
        log("photo saved: {}".format(take_photo()))
    except Exception as err:
        log("WARNING camera: {}".format(err))


# ---------------------------------------------------------------------------
# Writing the readings and the status for the web page
# ---------------------------------------------------------------------------

def write_readings(now, temp, moisture):
    """Append one row to logs/readings.csv - can be opened in Excel later."""
    if DRY_RUN:
        # Show the readings but keep test runs out of the real data file.
        log("  (dry run: readings temp {} C, moisture {})".format(temp, moisture))
        return
    path = os.path.join(config.LOG_DIR, "readings.csv")
    new_file = not os.path.exists(path)
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            names = list(config.MOISTURE_SENSORS)
            if new_file:
                writer.writerow(["time", "temperature_c"]
                                + ["{}_percent".format(n) for n in names]
                                + ["{}_raw".format(n) for n in names]
                                + ["light", "fan"])
            writer.writerow(
                [now.strftime("%Y-%m-%d %H:%M"), temp]
                + [moisture.get(n, (None, None))[1] for n in names]
                + [moisture.get(n, (None, None))[0] for n in names]
                + [int(relays.is_on("light")), int(relays.is_on("fan"))]
            )
    except OSError as err:
        log("WARNING could not write readings: {}".format(err))


def write_status(now, started, temp, moisture, sensor_time, state):
    """Write everything the web page shows to status.json."""
    nxt = next_watering(now, state)
    status = {
        "updated": now.isoformat(timespec="seconds"),
        "started": started.isoformat(timespec="seconds"),
        "dry_run": DRY_RUN,
        "sensors_read": sensor_time.isoformat(timespec="seconds") if sensor_time else None,
        "temperature": temp,
        "moisture": {n: {"raw": raw, "percent": p} for n, (raw, p) in moisture.items()},
        "outputs": {
            name: dict(output_info.get(name, {}), on=relays.is_on(name))
            for name in config.RELAY_PINS
        },
        "schedule": {
            "light": "{}-{}".format(config.LIGHT_ON_TIME, config.LIGHT_OFF_TIME),
            "fan_on_temp": config.FAN_ON_TEMP,
            "fan_off_temp": config.FAN_OFF_TEMP,
            "fan_circulate_minutes": config.FAN_CIRCULATE_MINUTES,
            "water_time": config.WATER_TIME,
            "water_every_days": config.WATER_EVERY_DAYS,
            "water_seconds": config.WATER_SECONDS,
            "next_watering": nxt.isoformat(timespec="minutes") if nxt else None,
            "last_watered": state.get("last_watered"),
            "photo_time": config.PHOTO_TIME,
            "pump_min_seconds": config.PUMP_MIN_SECONDS,
            "pump_max_seconds": config.PUMP_MAX_SECONDS,
            "temp_low_warning": config.TEMP_LOW_WARNING,
        },
    }
    try:
        write_json(config.STATUS_FILE, status)
    except OSError as err:
        log("WARNING could not write status: {}".format(err))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global status_dirty
    # systemd stops a service with SIGTERM. Turning it into a normal exit makes
    # the `finally:` below run, so every relay is switched off on shutdown.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    # ----- learn -----
    # Linux stops a program by sending it a "signal". SIGTERM means "please
    # stop". By default Python would die instantly and skip the `finally:`
    # block at the bottom of this function, leaving relays in whatever state
    # they were in. This line says: when SIGTERM arrives, call sys.exit(0)
    # instead, which ends the program NORMALLY, so `finally:` runs.
    # `lambda a, b: expression` is a tiny unnamed function written inline.
    # It is the same as:  def handler(signum, frame): sys.exit(0)
    # ----- end learn -----

    started = datetime.now()
    log("greenhouse started{}".format(" (DRY RUN - no relays switched)" if DRY_RUN else ""))
    relays.setup()  # all relays OFF to begin with
    state = load_state()
    cooling = False
    temp, moisture, sensor_time = None, {}, None
    last_log_slot = None
    temp_warned = False

    try:
        while True:
            now = datetime.now()

            # Sensors: every SENSOR_EVERY_SECONDS, not every tick - reading
            # the DS18B20 takes almost a second.
            sensors_due = sensor_time is None or (now - sensor_time).total_seconds() >= SENSOR_EVERY_SECONDS
            if sensors_due:
                temp = read_temperature()
                moisture = read_moisture()
                sensor_time = now
                # Warn once when it gets too cold, and again only after it has
                # warmed up in between - not every 30 seconds all night.
                if temp is not None and temp < config.TEMP_LOW_WARNING and not temp_warned:
                    log("WARNING cold: {} C - basil is damaged below about {} C".format(
                        temp, config.TEMP_LOW_WARNING))
                    temp_warned = True
                elif temp is not None and temp >= config.TEMP_LOW_WARNING + 2:
                    temp_warned = False

            # ----- learn -----
            # This is the heart of the whole program: the same few steps, every
            # second, forever. Each round it (1) reads the world: clock,
            # sensors, requests from the web page, then (2) calls one control_*
            # function per device, each deciding what its device SHOULD be doing
            # now. None of them depends on what happened in earlier seconds
            # (except the fan's `cooling` flag and the saved watering date), so
            # the program recovers on its own after any restart.
            # `while True:` loops forever. The only ways out are `break` (the
            # --once option), Ctrl+C (KeyboardInterrupt) or the SIGTERM above.
            # ----- end learn -----
            overrides = read_overrides(now)
            handle_pump_request(now)
            control_light(now, overrides)
            cooling = control_fan(now, temp, cooling, overrides)
            control_watering(now, state, moisture)
            check_pump(now)
            control_photo(now, state)

            # Write a row of readings once per LOG_INTERVAL_MINUTES slot.
            slot = (now.hour * 60 + now.minute) // config.LOG_INTERVAL_MINUTES
            if slot != last_log_slot:
                write_readings(now, temp, moisture)
                last_log_slot = slot

            # status.json: after every sensor read, and at once after a change
            # (so a button press shows up on the web page within a second).
            if sensors_due or status_dirty:
                write_status(now, started, temp, moisture, sensor_time, state)
                status_dirty = False

            if ONCE:
                break
            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        relays.cleanup()
        log("greenhouse stopped, all relays off")
        # Tell the web page straight away that nothing is running any more.
        try:
            os.remove(config.STATUS_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
