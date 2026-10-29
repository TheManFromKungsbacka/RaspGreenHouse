"""
statefiles.py - The small files greenhouse.py and the web page talk through.

The web page never switches a relay itself. Instead:

    greenhouse.py  --writes-->  status.json         <--reads--  web page
    greenhouse.py  <--reads--   overrides.json      <--writes-- web page
    greenhouse.py  <--reads--   pump_request.json   <--writes-- web page

Why files and not a direct connection? Only ONE program then ever drives the
GPIO pins, so the web page and the daily program can never fight over a relay,
and all safety rules (pump limits, override expiry) live in one place,
greenhouse.py. The web server also needs no GPIO access at all.

This module has no hardware imports, so both programs can use it safely.
"""

import json
import os
from datetime import datetime

import config


def log_event(message):
    """Write one timestamped line to the screen and to logs/events.log."""
    line = "{} {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    print(line, flush=True)
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        with open(os.path.join(config.LOG_DIR, "events.log"), "a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # a full or read-only SD card must not stop the greenhouse
    # ----- learn -----
    # try/except is Python's way of saying "attempt this, and if it fails in
    # THIS specific way, do that instead of crashing". OSError covers file
    # problems (disk full, no permission). `pass` means "do nothing".
    # Only name the errors you expect: a bare `except:` hides real bugs.
    # `with open(...) as f:` closes the file for you when the block ends,
    # even if an error happens inside it. "a" means append: add to the end.
    # ----- end learn -----


def read_json(path, default=None):
    """Read a JSON file, or return `default` if it is missing or damaged."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Write a JSON file so that a reader never sees a half-written file.

    We write to a temporary file first and then rename it over the real one.
    A rename is "atomic" on Linux: the reader gets either the old or the new
    file, never a mix, even if both programs touch it at the same moment.
    """
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    # ----- learn -----
    # Picture two programs and one file. If greenhouse.py is halfway through
    # writing status.json when the web page reads it, the page gets half a
    # file and crashes on invalid JSON. The fix is a pattern you will meet
    # everywhere: write the whole thing somewhere private (.tmp), then swap it
    # in with ONE step (os.replace). The reader sees the old file or the new
    # file, never something in between.
    # json.dump turns Python dicts/lists into text; json.load does the reverse.
    # ----- end learn -----


def recent_events(count=20):
    """Return the last `count` lines of logs/events.log, newest first."""
    try:
        with open(os.path.join(config.LOG_DIR, "events.log")) as f:
            lines = f.readlines()
    except OSError:
        return []
    return [line.rstrip("\n") for line in reversed(lines[-count:])]
