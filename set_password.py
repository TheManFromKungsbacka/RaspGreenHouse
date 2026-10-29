"""
set_password.py - Create or change the login for the greenhouse web page.

Run on the Pi:   python3 set_password.py

It asks for a username and a password (typed invisibly) and stores them in
web_auth.json. The password itself is never stored: only a salted hash, a
one-way scrambled version that can check a password but not reveal it.

Each run also makes a new random secret key for the login cookies, so
everyone who is logged in is logged out. Restart the web page afterwards:
    sudo systemctl restart greenhouse-web
"""

import getpass
import os
import secrets
import sys

from werkzeug.security import generate_password_hash

import config
from statefiles import read_json, write_json

MIN_LENGTH = 10  # the page may be on the internet later: no short passwords

old = read_json(config.WEB_AUTH_FILE, {}) or {}
default_user = old.get("username", "admin")
username = input("Username [{}]: ".format(default_user)).strip() or default_user

password = getpass.getpass("New password (min {} characters): ".format(MIN_LENGTH))
if len(password) < MIN_LENGTH:
    sys.exit("Too short - nothing changed.")
if getpass.getpass("Same password again: ") != password:
    sys.exit("The passwords did not match - nothing changed.")

# New files from here on are readable by the pi user only - also the
# temporary file write_json() creates before renaming it into place.
os.umask(0o077)
write_json(config.WEB_AUTH_FILE, {
    "username": username,
    # pbkdf2 with many rounds: slow to guess even if someone copies the file.
    "password_hash": generate_password_hash(password, method="pbkdf2:sha256:260000"),
    "secret_key": secrets.token_hex(32),
})
# ----- learn -----
# Why not just save the password? If someone ever copies web_auth.json, they
# would own your password (and probably every other site where you reuse it).
# A hash is a one-way scramble: the same password always gives the same
# result, but you cannot go backwards. At login the page hashes what you typed
# and compares. "pbkdf2 ... 260000" repeats the scrambling 260 000 times, so
# an attacker trying a million guesses has to do 260 billion rounds of work.
# The hash also contains a random "salt", so two identical passwords give
# different hashes.
# `getpass` types invisibly. `secrets` (not `random`) is used for the key,
# because `random` is predictable and `secrets` is built for security.
# `os.umask(0o077)` / `chmod 0o600` are Linux file permissions in octal:
# 6 = read+write for the owner, 0 = nothing for everyone else.
# ----- end learn -----
os.chmod(config.WEB_AUTH_FILE, 0o600)  # also fixes an older file with looser rights
print("Saved login for '{}' in {}".format(username, config.WEB_AUTH_FILE))
print("Restart the web page to use it:  sudo systemctl restart greenhouse-web")
