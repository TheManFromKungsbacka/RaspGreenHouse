"""
test_temperature.py - Check that the DS18B20 temperature sensor works.

Run on the Pi:   python3 test_temperature.py        (5 readings)
                 python3 test_temperature.py 20     (20 readings)

What to check: the value should be close to room temperature, and it should
rise within a few seconds if you hold the sensor between your fingers.
"""

import sys
import time

from hardware.temperature import find_sensor_file, read_temperature

# How many readings to take: the first command-line argument, default 5.
count = int(sys.argv[1]) if len(sys.argv) > 1 else 5

try:
    print("Sensor file:", find_sensor_file())
    for i in range(1, count + 1):
        print("Reading {}/{}: {:.2f} C".format(i, count, read_temperature()))
        if i < count:
            time.sleep(1)
    print("OK - temperature sensor works.")
except RuntimeError as err:
    print("PROBLEM:", err)
    sys.exit(1)
except KeyboardInterrupt:
    print("\nStopped.")
