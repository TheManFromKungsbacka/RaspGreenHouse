"""
config.py - All hardware settings for the greenhouse, in ONE place.

Why a separate config file?
    Every other file (the test scripts now, the automation and the web page
    later) imports its settings from here. If you ever move a wire to another
    GPIO pin, or re-calibrate the moisture sensor, you change ONE number in
    this file instead of hunting through many scripts.

Pin numbers use the "BCM" numbering (the GPIO numbers, e.g. GPIO20), NOT the
physical pin position on the header. Run `pinout` in a terminal on the Pi to
see a map of both.
"""

import os

# The folder this file lives in (/home/pi/Greenhouse/Rasp). Other paths are
# built from it so the project still works if the folder is moved or renamed.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ----- learn -----
# `__file__` is a built-in variable holding the path of THIS file. abspath makes
# it a full path, and dirname cuts off the file name, leaving the folder.
# Reading it from right to left: "the folder of the full path of this file".
# Other files do `import config` and then write config.BASE_DIR: an import
# runs the file once and gives you its names under the prefix `config.`.
# ----- end learn -----


# ---------------------------------------------------------------------------
# OUTPUTS: the relay board
# ---------------------------------------------------------------------------
# Each output device (UV light, pump, fan) is powered through a relay. The Pi
# switches the relay by setting a GPIO pin HIGH or LOW.
#
# The names on the left are what the rest of the code uses, e.g.
# relays.turn_on("pump"). The numbers are the GPIO pins taken from your
# earlier scripts.
RELAY_PINS = {
    "light": 20,  # UV grow light
    "pump": 23,   # water pump (mtm.py once used GPIO21 - test_relays.py will tell)
    "fan": 25,    # fan
}
# ----- learn -----
# This is a dictionary (dict): pairs of "key": value inside { }. You look a
# value up by its key: RELAY_PINS["pump"] gives 23. Why a dict and not three
# separate variables? Because code can then LOOP over all devices:
#     for name, pin in RELAY_PINS.items(): ...
# Adding a fourth device means adding one line here, and the loops in
# relays.py, greenhouse.py and the web page pick it up without any changes.
# ----- end learn -----

# Most cheap relay boards are "active low": the relay switches ON when the pin
# is pulled LOW (0 V) and OFF when it is HIGH (3.3 V). Your old code did
# GPIO.output(pin, GPIO.LOW) to turn things on, so that is the case here.
# If a device turns on when it should turn off, flip this to False.
RELAY_ACTIVE_LOW = True

# Safety limit: the pump is never allowed to run longer than this in one go,
# no matter what a script asks for. Protects against flooding if a bug or a
# crash leaves the pump on. The new pump has a much lower capacity than the
# old one, so 25 s is still a modest amount of water.
PUMP_MAX_SECONDS = 25

# The pump is never run for less than this. The new pump is weak and needs
# several seconds to prime and push water through the hose, so a shorter run
# would deliver almost nothing.
PUMP_MIN_SECONDS = 10


# ---------------------------------------------------------------------------
# SENSORS: soil moisture (analog sensors -> MCP3008 ADC -> SPI)
# ---------------------------------------------------------------------------
# The Pi cannot read analog voltages itself, so the moisture sensors are wired
# to an MCP3008 chip (an analog-to-digital converter). The Pi talks to the
# MCP3008 over the SPI bus. SPI bus 0, chip-select 0 = the device /dev/spidev0.0.
MOISTURE_SPI_BUS = 0
MOISTURE_SPI_DEVICE = 0

# One entry per moisture sensor. The MCP3008 has 8 inputs (CH0-CH7), so up to
# 8 sensors can share the one chip; each sensor just needs its own channel.
#
#   "channel"  which MCP3008 input the sensor's AO wire goes to
#              (CH0 = chip pin 1, CH1 = chip pin 2, ... CH7 = chip pin 8)
#   "raw_dry"  raw reading (0-1023) with the sensor in dry air   -> 0 %
#   "raw_wet"  raw reading with the sensor in a glass of water   -> 100 %
#
# Each sensor gets its OWN calibration, because two cheap sensors of the same
# model rarely read the same. Run test_moisture.py with the sensors in air and
# then in water, and replace the numbers below with what you see.
#
# Tip: rename "sensor1"/"sensor2" to where they sit, e.g. "near_outlet" and
# "far_corner". The new names then show up in the test output automatically.
MOISTURE_SENSORS = {
    # Calibrated 2026-10-25: dry air and a glass of tap water (typical value of 10 readings).
    "sensor1": {"channel": 0, "raw_dry": 1023, "raw_wet": 815},
    "sensor2": {"channel": 1, "raw_dry": 1023, "raw_wet": 720},
}
# ----- learn -----
# A dict inside a dict. The outer key is the sensor's name, and each value is
# a small dict of that sensor's own settings:
#     MOISTURE_SENSORS["sensor2"]["raw_wet"]   ->  720
# Data like this (a table of things, each with the same fields) is better kept
# as data than as code: the sensor code in moisture.py does not mention
# "sensor1" anywhere, it just loops over whatever is listed here.
# ----- end learn -----


# ---------------------------------------------------------------------------
# SENSOR: temperature (DS18B20 on the 1-Wire bus)
# ---------------------------------------------------------------------------
# The DS18B20 shows up as a folder in /sys/bus/w1/devices/ named "28-xxxxxxx".
# None = use the first one found. If you add more sensors later, put the exact
# ID here, e.g. "28-000009a23983".
TEMP_SENSOR_ID = None


# ---------------------------------------------------------------------------
# SENSOR: camera (Raspberry Pi camera module, ribbon cable)
# ---------------------------------------------------------------------------
PHOTO_DIR = os.path.join(BASE_DIR, "photos")
CAMERA_RESOLUTION = (1920, 1080)


# ---------------------------------------------------------------------------
# DAILY PROGRAM (greenhouse.py) - settings for herbs
# ---------------------------------------------------------------------------
# All times are "HH:MM" in 24-hour format, Pi local time (Europe/Oslo).
# Values are a middle ground for common herbs (basil, parsley, thyme, oregano,
# chives, mint). Basil wants the most light and warmth; thyme, oregano and
# rosemary want the least water.

# Grow light: herbs need roughly 12-16 hours of light a day. In autumn and
# winter the daylight here is much shorter, so the lamp supplies the rest.
# 14 hours (06:00-20:00) suits both basil and the hardier herbs.
LIGHT_ON_TIME = "06:00"
LIGHT_OFF_TIME = "20:00"

# Fan for cooling: herbs do best at about 18-27 C during the day. Above
# FAN_ON_TEMP the fan runs until the temperature falls to FAN_OFF_TEMP. The gap
# between the two stops the fan flicking on and off at the limit.
FAN_ON_TEMP = 28.0
FAN_OFF_TEMP = 25.0

# Fan for air circulation: moving air keeps leaves dry and prevents mildew,
# which basil is especially prone to. The fan runs for this many minutes at the
# start of every hour, even when it is not hot. 0 = no circulation runs.
FAN_CIRCULATE_MINUTES = 2.0

# Warning only (there is no heater): below this, basil gets cold damage.
TEMP_LOW_WARNING = 10.0

# Watering on a schedule, because the moisture sensors are too unreliable to
# decide on their own. Most herbs want the soil to dry a little between
# waterings; with the weak new pump, 20 s every morning was chosen instead.
# Adjust WATER_SECONDS after measuring how much water the pump gives
# (must be between PUMP_MIN_SECONDS and PUMP_MAX_SECONDS).
WATER_TIME = "07:30"
WATER_EVERY_DAYS = 1
WATER_SECONDS = 12

# One photo a day at this time, for following plant growth over weeks.
PHOTO_TIME = "12:00"

# How often a row with all readings is written to the log file, in minutes.
LOG_INTERVAL_MINUTES = 10
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Remembers what was done today (watering, photo), so a restart of the
# program or the Pi never waters twice on the same day.
STATE_FILE = os.path.join(BASE_DIR, "state.json")

# Files greenhouse.py and the web page use to talk to each other
# (see statefiles.py for why they talk through files).
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
OVERRIDE_FILE = os.path.join(BASE_DIR, "overrides.json")
PUMP_REQUEST_FILE = os.path.join(BASE_DIR, "pump_request.json")


# ---------------------------------------------------------------------------
# WEB PAGE (web/app.py)
# ---------------------------------------------------------------------------
# 0.0.0.0 = reachable from every device on the home network.
WEB_HOST = "0.0.0.0"
WEB_PORT = 8080

# Username, password hash and session key, created by set_password.py.
# Never put this file in Git.
WEB_AUTH_FILE = os.path.join(BASE_DIR, "web_auth.json")

# True: anyone who can reach the page may LOOK at the values; only switching
# relays needs a login. Set to False before the page is reachable from the
# internet, so that everything needs a login.
WEB_PUBLIC_VIEW = True

# A logged-in user is logged out after this many minutes without activity.
WEB_SESSION_MINUTES = 30

# True once the page is served over HTTPS (e.g. through a Cloudflare tunnel):
# the login cookie is then never sent over plain, readable HTTP.
WEB_COOKIE_SECURE = False

# Login protection: after this many wrong passwords from one address, that
# address is locked out for WEB_LOCKOUT_MINUTES.
WEB_MAX_LOGIN_FAILURES = 5
WEB_LOCKOUT_MINUTES = 15

# A light/fan switched by hand on the web page returns to the automatic
# schedule after this many minutes, so a forgotten manual "off" can never
# leave the plants without light or cooling for days.
MANUAL_OVERRIDE_MINUTES = 120

# A manual pump request older than this is ignored (e.g. one made while
# greenhouse.py was stopped), so the pump never starts unexpectedly later.
PUMP_REQUEST_MAX_AGE_SECONDS = 60
