"""
camera.py - Take photos with the Raspberry Pi camera module.

Uses the `picamera` library, which works with the camera stack on your
Raspbian Buster. The camera must be enabled (start_x=1 in /boot/config.txt,
already set) and its ribbon cable firmly seated at both ends, with the blue
side of the cable facing the network/USB ports on a Pi 3.

Quick hardware check without Python:  vcgencmd get_camera
    supported=1 detected=1   -> camera found
    supported=1 detected=0   -> camera enabled but not seen: check the cable
"""

import os
import time
from datetime import datetime

from config import CAMERA_RESOLUTION, PHOTO_DIR


def take_photo(filename=None):
    """Take one photo and return the full path of the saved .jpg file.

    If no filename is given, the photo is named after the current date and
    time, e.g. photos/2026-10-18_14-05-00.jpg, so photos never overwrite each
    other and sort in time order. That will be handy later for following
    plant growth over days and weeks.
    """
    # Imported here rather than at the top so that the other hardware modules
    # still work even if the camera library has a problem.
    from picamera import PiCamera

    os.makedirs(PHOTO_DIR, exist_ok=True)
    if filename is None:
        filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".jpg"
    path = os.path.join(PHOTO_DIR, filename)

    # `with` makes sure the camera is closed again afterwards, even on errors.
    # An unclosed camera stays "busy" and blocks the next photo.
    # ----- learn -----
    # `with X as name:` is a "context manager": Python opens X at the start of
    # the block and always closes it at the end, even after an error. It
    # replaces try/finally for resources that must be released (files,
    # cameras, network connections).
    # `filename=None` in the function header is a default argument: callers
    # may leave it out, and `if filename is None` then picks a date-based name.
    # strftime("%Y-%m-%d_%H-%M-%S") turns a date into text like 2026-10-25_14-53-42.
    # ----- end learn -----
    with PiCamera() as cam:
        cam.resolution = CAMERA_RESOLUTION
        # Give the sensor 2 seconds to adjust exposure and white balance,
        # otherwise the first photo is often too dark or has a colour cast.
        time.sleep(2)
        cam.capture(path)

    return path
