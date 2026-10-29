"""
moisture.py - Read the soil moisture sensors through the MCP3008 ADC.

The signal chain
----------------
    moisture sensor  --(analog voltage)-->  MCP3008  --(SPI, digital)-->  Pi

Each sensor outputs a voltage that changes with how wet the soil is. The Pi has
no analog inputs, so the MCP3008 measures the voltage and turns it into a
number from 0 (0 V) to 1023 (3.3 V). The Pi asks for that number over SPI.

Several sensors can share one MCP3008: each one is wired to its own input
channel. Which sensor is on which channel, and each sensor's dry/wet
calibration, is listed in MOISTURE_SENSORS in config.py.

Typical use:
    from hardware import moisture
    raw, percent = moisture.read_moisture("sensor1")   # one sensor
    readings = moisture.read_all()                     # every sensor
"""

import time

import spidev  # Python library for talking to SPI devices

from config import MOISTURE_SENSORS, MOISTURE_SPI_BUS, MOISTURE_SPI_DEVICE

# The SPI connection is opened the first time it is needed and then reused.
# Opening it once at import time (like the old code did) would crash any
# script that merely imports this file on a machine without SPI.
_spi = None


def _get_spi():
    global _spi
    if _spi is None:
        _spi = spidev.SpiDev()
        _spi.open(MOISTURE_SPI_BUS, MOISTURE_SPI_DEVICE)
        _spi.max_speed_hz = 1350000  # 1.35 MHz, well within the MCP3008's limit
    return _spi


def _sensor(name):
    """Look up a sensor's settings in config.py, with a helpful error if misspelt."""
    if name not in MOISTURE_SENSORS:
        raise ValueError(
            "Unknown moisture sensor '" + name + "'. Choose one of: "
            + ", ".join(MOISTURE_SENSORS)
        )
    return MOISTURE_SENSORS[name]


def read_raw(channel):
    """Ask the MCP3008 for one measurement on a channel (0-7), returned as 0-1023.

    SPI sends and receives at the same time: for every byte we send, we get one
    byte back. The MCP3008 datasheet says to send 3 bytes:

        byte 1: 00000001         -> "start bit": wake up, a request follows
        byte 2: 1ccc0000         -> 1 = single-ended mode, ccc = channel 0-7
        byte 3: 00000000         -> dummy byte, just to clock the answer out

    The 10-bit answer comes back spread over the last two received bytes:
    the lowest 2 bits of reply[1] are the top bits, reply[2] is the rest.
    """
    spi = _get_spi()
    reply = spi.xfer2([1, (8 + channel) << 4, 0])
    return ((reply[1] & 3) << 8) + reply[2]
    # ----- learn -----
    # Bit tricks, step by step. The chip answers with 10 bits split over two
    # bytes (a byte is 8 bits). Say reply[1] = 0b00000010 and reply[2] = 0b01100100.
    #   reply[1] & 3     keeps only the lowest 2 bits of reply[1]  -> 0b10
    #   ... << 8         slides them 8 places left (the "high" part) -> 0b1000000000
    #   ... + reply[2]   adds the other 8 bits                       -> 612
    # So two small pieces become one number from 0 to 1023.
    # Likewise `(8 + channel) << 4` builds the request byte "1ccc0000":
    # 8 is binary 1000, and shifting left 4 places puts it at the top.
    # ----- end learn -----


def raw_to_percent(raw, raw_dry, raw_wet):
    """Convert a raw 0-1023 reading to a 0-100 % moisture value.

    A straight-line conversion between the sensor's two calibration points:
    raw_dry -> 0 %, raw_wet -> 100 %. Values outside that range are clamped so
    we never report -5 % or 112 %.
    """
    percent = (raw - raw_dry) * 100.0 / (raw_wet - raw_dry)
    return int(max(0, min(100, round(percent))))


def read_moisture(name, samples=5):
    """Return (raw, percent) for one sensor, based on several quick readings.

    Analog readings jitter a little. We take a few readings and use the median
    (the middle value after sorting), which ignores an occasional odd spike
    better than an average would.
    """
    sensor = _sensor(name)
    readings = []
    for _ in range(samples):
        readings.append(read_raw(sensor["channel"]))
        time.sleep(0.05)
    readings.sort()
    raw = readings[len(readings) // 2]
    return raw, raw_to_percent(raw, sensor["raw_dry"], sensor["raw_wet"])


def read_all(samples=5):
    """Read every sensor in config.py.

    Returns a dict in the same order as MOISTURE_SENSORS, for example:
        {"sensor1": (612, 40), "sensor2": (580, 43)}
    """
    return {name: read_moisture(name, samples) for name in MOISTURE_SENSORS}
    # ----- learn -----
    # This one line is a "dict comprehension": build a dict by looping.
    # It means exactly the same as:
    #     result = {}
    #     for name in MOISTURE_SENSORS:
    #         result[name] = read_moisture(name, samples)
    #     return result
    # Comprehensions are a short form for "make a new list/dict from an old one".
    # ----- end learn -----
