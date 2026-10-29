"""
test_moisture.py - Check the soil moisture sensors and help calibrate them.

Run on the Pi:   python3 test_moisture.py        (10 readings)
                 python3 test_moisture.py 60     (60 readings, 1 per second)

Every second it reads ALL sensors listed in MOISTURE_SENSORS in config.py and
prints them side by side, plus the difference between the first two. Use that
to compare the sensors in the same soil, or to watch water spread: put one
sensor near where the water goes in and one further away, water, and see how
long the far one takes to follow.

Calibration (do this once per sensor):
  1. Hold the sensors in the AIR and note each raw value   -> "raw_dry"
  2. Put them in a glass of WATER (only up to the line on the sensor!)
     and note each raw value                                -> "raw_wet"
  3. Put the numbers in MOISTURE_SENSORS in config.py.

A reading stuck at 0 or 1023 whatever you do usually means a wiring problem.
"""

import sys
import time

from config import MOISTURE_SENSORS
from hardware.moisture import read_all

count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
names = list(MOISTURE_SENSORS)

# Print which channel and calibration each sensor uses, so a mix-up between
# sensors is easy to spot.
for name, s in MOISTURE_SENSORS.items():
    print("{:<12} CH{}   dry = {:>4}   wet = {:>4}".format(name, s["channel"], s["raw_dry"], s["raw_wet"]))
print()

# Column headings: one "raw / %" column per sensor, then the difference.
header = "  #   " + "".join("{:>18}".format(n) for n in names)
if len(names) >= 2:
    header += "   diff (1st - 2nd)"
print(header)

try:
    for i in range(1, count + 1):
        readings = read_all()
        line = "{:>3}   ".format(i)
        for name in names:
            raw, percent = readings[name]
            line += "{:>9} raw {:>3} %".format(raw, percent)
        # The difference in % between the first two sensors. Positive means the
        # first sensor reads wetter. Only meaningful once both are calibrated.
        if len(names) >= 2:
            diff = readings[names[0]][1] - readings[names[1]][1]
            line += "   {:>+5} %".format(diff)
        print(line)
        if i < count:
            time.sleep(1)
except KeyboardInterrupt:
    print("\nStopped.")
