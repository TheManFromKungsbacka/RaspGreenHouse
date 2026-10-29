"""
The `hardware` package: one small module per physical device.

    temperature.py  - read the DS18B20 temperature sensor
    moisture.py     - read the soil moisture sensor via the MCP3008
    camera.py       - take a photo with the Pi camera
    relays.py       - switch the UV light, pump and fan on/off

These modules only know HOW to talk to the hardware. They contain no
decisions like "water when dry" - that belongs to the automation part we
build later, which will simply import these modules.
"""
