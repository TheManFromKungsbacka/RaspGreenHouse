"""
temperature.py - Read the DS18B20 temperature sensor.

How the DS18B20 works on a Raspberry Pi
---------------------------------------
The sensor uses the "1-Wire" bus (one data wire, on GPIO4 by default). The
line `dtoverlay=w1-gpio` in /boot/config.txt makes Linux load a driver that
does all the hard work. The driver shows each sensor as a folder:

    /sys/bus/w1/devices/28-000009a23983/w1_slave

Reading that "file" makes the driver ask the sensor for a measurement and
gives back two lines of text, for example:

    72 01 4b 46 7f ff 0e 10 57 : crc=57 YES
    72 01 4b 46 7f ff 0e 10 57 t=23125

Line 1 ends in YES if the data arrived without transmission errors (the CRC
checksum matched). Line 2 contains the temperature after "t=", in thousandths
of a degree Celsius: 23125 means 23.125 C.
"""

import glob
import time

from config import TEMP_SENSOR_ID

W1_DEVICES_DIR = "/sys/bus/w1/devices/"


def find_sensor_file():
    """Return the path to the sensor's w1_slave file.

    DS18B20 sensors always have IDs starting with "28-". If config.py names a
    specific sensor we use that one, otherwise the first one we find.
    """
    if TEMP_SENSOR_ID:
        folders = glob.glob(W1_DEVICES_DIR + TEMP_SENSOR_ID)
    else:
        folders = sorted(glob.glob(W1_DEVICES_DIR + "28-*"))

    if not folders:
        raise RuntimeError(
            "No DS18B20 temperature sensor found in " + W1_DEVICES_DIR + ". "
            "Check the wiring (data wire on GPIO4 with a 4.7k pull-up resistor "
            "to 3.3V) and that /boot/config.txt contains 'dtoverlay=w1-gpio'."
        )
    return folders[0] + "/w1_slave"


def read_temperature(retries=10):
    """Read the temperature in degrees Celsius, rounded to 2 decimals.

    A single read can occasionally fail (bad checksum, electrical noise), so we
    try up to `retries` times, waiting 0.2 s between attempts, before giving up
    with an error. The old code looped forever in that case, which would make
    the whole program hang if the sensor came loose.
    """
    sensor_file = find_sensor_file()

    for _ in range(retries):
        with open(sensor_file) as f:
            lines = f.readlines()

        # Line 1 must end with "YES" (checksum OK) and line 2 must contain "t=".
        if len(lines) >= 2 and lines[0].strip().endswith("YES"):
            pos = lines[1].find("t=")
            if pos != -1:
                celsius = int(lines[1][pos + 2:]) / 1000.0

                # 85.0 C is the value the DS18B20 reports right after power-up,
                # before it has made a real measurement. Treat it as "not ready
                # yet" and try again rather than reporting a heat wave.
                if celsius != 85.0:
                    return round(celsius, 2)

        time.sleep(0.2)
    # ----- learn -----
    # The shape of this function is a very common pattern: "retry, then give
    # up loudly". Loop a limited number of times; return as soon as one try is
    # good; if the loop ends without a return, raise an error (below).
    # `for _ in range(retries)` uses `_` as a name for "I need to repeat this,
    # but I do not need the counter".
    # `lines[1][pos + 2:]` is slicing: everything from position pos+2 to the
    # end of the text. For "... t=23125" it gives "23125", and int() makes it a
    # number. Dividing by 1000.0 gives 23.125.
    # Early `return` inside the loop is how a function says "found it, done".
    # ----- end learn -----

    raise RuntimeError(
        "The temperature sensor did not give a valid reading after "
        + str(retries) + " attempts. Check the wiring."
    )
