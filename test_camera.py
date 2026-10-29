"""
test_camera.py - Check the Pi camera by taking one photo.

Run on the Pi:   python3 test_camera.py

The photo is saved in the photos/ folder. In VS Code (connected to the Pi)
you can simply click it in the file explorer to look at it.
"""

import os
import subprocess
import sys

from hardware.camera import take_photo

# First ask the Pi's firmware whether it can see a camera at all. This gives a
# much clearer message than the Python error you get otherwise.
result = subprocess.run(["vcgencmd", "get_camera"], stdout=subprocess.PIPE, universal_newlines=True)
print("Firmware says:", result.stdout.strip())

if "detected=0" in result.stdout:
    print(
        "PROBLEM: the camera is enabled but not detected.\n"
        "  - Power off the Pi (sudo poweroff) and unplug it before touching the cable.\n"
        "  - Reseat the ribbon cable at BOTH ends; on the Pi side the blue strip\n"
        "    faces the USB/network ports, on the camera side it faces away from the lens board.\n"
        "  - Make sure the cable is pushed fully in before closing the little latch."
    )
    sys.exit(1)

print("Taking a photo (takes about 3 seconds)...")
try:
    path = take_photo()
except Exception as err:  # picamera raises several error types; show any of them
    print("PROBLEM:", err)
    sys.exit(1)

print("OK - photo saved: {} ({} KB)".format(path, os.path.getsize(path) // 1024))
