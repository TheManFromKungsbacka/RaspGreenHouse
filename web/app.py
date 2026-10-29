"""
web/app.py - The greenhouse web page.

Shows the latest sensor values, the state of every output, the schedule, the
latest photo and recent events. After logging in, the light and fan can be
switched by hand and the pump started or stopped.

Run on the Pi (normally started by systemd, see greenhouse-web.service):
    python3 web/app.py
then open http://<pi-ip>:8080 in a browser on the home network.

Set the login first, once:   python3 set_password.py

Security, built in from the start because the page may later be reachable
from the internet:
  - This program never touches the GPIO pins. It only writes requests to
    files, and greenhouse.py carries them out with its own safety limits
    (pump 10-25 s, manual overrides expire). See statefiles.py.
  - Passwords are stored only as a salted hash (web_auth.json), never as text.
  - After WEB_MAX_LOGIN_FAILURES wrong passwords an address is locked out.
  - Every request that changes something needs a CSRF token: a secret value
    only our own page knows, so another website cannot make your browser
    press our buttons.
  - The login cookie cannot be read by JavaScript (HttpOnly), is never sent
    along from other sites (SameSite=Strict), and expires after inactivity.
  - Security headers stop the page being shown inside other sites and only
    allow scripts and styles from this server.
  - It runs on Waitress, a server built for real use, not Flask's test server.
"""

import hmac
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash

# Make config.py and statefiles.py in the folder above importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from statefiles import log_event, read_json, recent_events, write_json  # noqa: E402

# A status.json older than this means greenhouse.py is not running.
STATUS_MAX_AGE_SECONDS = 90


# ---------------------------------------------------------------------------
# Login data from web_auth.json (created by set_password.py)
# ---------------------------------------------------------------------------

auth = read_json(config.WEB_AUTH_FILE)
if not auth or not auth.get("password_hash") or not auth.get("secret_key"):
    sys.exit("No login set up yet. Run first:  python3 set_password.py")

# ----- learn -----
# Flask in two sentences. `app = Flask(__name__)` creates the web application.
# Then `@app.route("/address")` above a function says "when a browser asks for
# this address, run this function and send back what it returns".
# The line above (sys.exit) stops the server from starting at all without a
# login: failing loudly at startup beats running unprotected.
# `sys.path.insert(...)` earlier adds the folder above `web/` to the places
# Python searches when you `import`, which is how this file finds config.py.
# ----- end learn -----
app = Flask(__name__)
app.config.update(
    # Signs the session cookie so it cannot be forged. Random, made by set_password.py.
    SECRET_KEY=auth["secret_key"],
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=config.WEB_COOKIE_SECURE,
    SESSION_COOKIE_NAME="greenhouse_session",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=config.WEB_SESSION_MINUTES),
    SESSION_REFRESH_EACH_REQUEST=True,  # inactivity timeout, not a fixed one
    MAX_CONTENT_LENGTH=4096,  # our requests are tiny; refuse anything big
)


# ---------------------------------------------------------------------------
# Login protection: count wrong passwords per address
# ---------------------------------------------------------------------------

_failures = {}  # address -> list of times of recent wrong passwords
_failures_lock = threading.Lock()  # Waitress serves several requests at once


def _client_address():
    return request.remote_addr or "?"


def _locked_out(addr):
    window = config.WEB_LOCKOUT_MINUTES * 60
    with _failures_lock:
        recent = [t for t in _failures.get(addr, []) if time.time() - t < window]
        _failures[addr] = recent
        return len(recent) >= config.WEB_MAX_LOGIN_FAILURES


def _record_failure(addr):
    with _failures_lock:
        _failures.setdefault(addr, []).append(time.time())


# ---------------------------------------------------------------------------
# Sessions and CSRF
# ---------------------------------------------------------------------------

def logged_in_user():
    return session.get("user")


def csrf_token():
    """The secret value our forms and scripts send back with every change."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


# ----- learn -----
# CSRF in plain words. Your browser attaches your login cookie to EVERY
# request to this site, even one triggered by a hidden form on a malicious
# website. So "has a valid cookie" is not proof that YOU pressed the button.
# Fix: the page we send contains a random secret (the token) that only our own
# pages can read. Every change must send it back in a header; a foreign site
# cannot read it, so it cannot forge the request.
# `abort(403, "...")` stops handling the request at once and returns an error.
# `hmac.compare_digest` compares two texts in constant time, so an attacker
# cannot measure tiny timing differences to guess the token one letter at a time.
# ----- end learn -----
def check_csrf(sent):
    # compare_digest takes the same time whether the first or last character
    # differs, so an attacker cannot guess the token piece by piece.
    expected = session.get("csrf", "")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(403, "Invalid or missing CSRF token - reload the page and try again.")


def require_login_for_changes():
    if not logged_in_user():
        abort(401, "Log in first.")
    check_csrf(request.headers.get("X-CSRF-Token"))


@app.before_request
def require_login_to_view():
    """With WEB_PUBLIC_VIEW = False, every page except the login needs a login."""
    if config.WEB_PUBLIC_VIEW or logged_in_user():
        return None
    if request.endpoint in ("login", "static"):
        return None
    if request.path.startswith("/api/"):
        abort(401)
    return redirect(url_for("login"))


@app.after_request
def security_headers(response):
    # Only our own scripts, styles and images; nothing from other sites.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"          # not inside other sites
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/") or request.endpoint in ("index", "login"):
        response.headers["Cache-Control"] = "no-store"     # never cache live data
    return response


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", user=logged_in_user(), csrf=csrf_token())


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        check_csrf(request.form.get("csrf"))
        addr = _client_address()
        if _locked_out(addr):
            error = "Too many wrong attempts. Try again in {} minutes.".format(config.WEB_LOCKOUT_MINUTES)
            log_event("web: login blocked for {} (locked out)".format(addr))
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            # Check both even if the username is wrong, so the response time
            # does not reveal whether a username exists.
            name_ok = hmac.compare_digest(username.encode(), auth["username"].encode())
            password_ok = check_password_hash(auth["password_hash"], password)
            if name_ok and password_ok:
                session.clear()  # new session on login: an old cookie cannot be reused
                session.permanent = True
                session["user"] = auth["username"]
                csrf_token()
                log_event("web: {} logged in from {}".format(auth["username"], addr))
                return redirect(url_for("index"))
            _record_failure(addr)
            log_event("web: failed login from {}".format(addr))
            error = "Wrong username or password."
    return render_template("login.html", error=error, csrf=csrf_token()), (401 if error else 200)


@app.route("/logout", methods=["POST"])
def logout():
    check_csrf(request.form.get("csrf"))
    user = logged_in_user()
    session.clear()
    if user:
        log_event("web: {} logged out".format(user))
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Data for the page (polled by static/app.js every few seconds)
# ---------------------------------------------------------------------------

def program_running(status):
    if not status or "updated" not in status:
        return False
    age = (datetime.now() - datetime.fromisoformat(status["updated"])).total_seconds()
    return age < STATUS_MAX_AGE_SECONDS


def latest_photo_name():
    try:
        photos = sorted(f for f in os.listdir(config.PHOTO_DIR) if f.lower().endswith(".jpg"))
    except OSError:
        return None
    return photos[-1] if photos else None


# ----- learn -----
# This is an "API route": it returns data (JSON) instead of a page. The
# browser's JavaScript (app.js) calls it every few seconds and draws the
# result. The web server does no thinking here; it only reads the file that
# greenhouse.py wrote and hands it over. `jsonify` turns a Python dict into a
# JSON reply. Note that `running` is worked out from the AGE of status.json:
# if greenhouse.py stopped, the file stops being updated and the page can tell.
# ----- end learn -----
@app.route("/api/status")
def api_status():
    status = read_json(config.STATUS_FILE)
    return jsonify({
        "running": program_running(status),
        "status": status,
        "now": datetime.now().isoformat(timespec="seconds"),
        "photo": latest_photo_name(),
        "events": recent_events(15),
        "user": logged_in_user(),
    })


@app.route("/photo/<name>")
def photo(name):
    # send_from_directory refuses names like "../config.py", so only files
    # inside the photos folder can ever be sent.
    if not name.lower().endswith(".jpg"):
        abort(404)
    return send_from_directory(config.PHOTO_DIR, name, max_age=3600)


# ---------------------------------------------------------------------------
# Manual control (login + CSRF token required)
# ---------------------------------------------------------------------------

_override_lock = threading.Lock()


def refuse_if_not_running():
    if not program_running(read_json(config.STATUS_FILE)):
        abort(503, "greenhouse.py is not running, so nothing can be switched.")


@app.route("/api/relay/<name>", methods=["POST"])
def api_relay(name):
    """Light or fan: {"mode": "on" | "off" | "auto"}."""
    require_login_for_changes()
    refuse_if_not_running()
    if name not in ("light", "fan"):
        abort(400, "Only light and fan can be switched; use the pump buttons for the pump.")
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in ("on", "off", "auto"):
        abort(400, "mode must be on, off or auto")

    # Read-change-write under a lock, so two clicks at the same moment cannot
    # overwrite each other's change.
    with _override_lock:
        overrides = read_json(config.OVERRIDE_FILE, {}) or {}
        if mode == "auto":
            overrides.pop(name, None)
            message = "{} back to automatic".format(name)
        else:
            until = datetime.now() + timedelta(minutes=config.MANUAL_OVERRIDE_MINUTES)
            overrides[name] = {"on": mode == "on", "until": until.strftime("%Y-%m-%dT%H:%M:%S"),
                               "user": logged_in_user()}
            message = "{} manually {} until {}".format(name, mode.upper(), until.strftime("%H:%M"))
        write_json(config.OVERRIDE_FILE, overrides)
    log_event("web: {} set {} (from {})".format(logged_in_user(), message, _client_address()))
    return jsonify({"ok": True, "message": message})


# ----- learn -----
# The pump button, step by step: (1) check the user is logged in and the CSRF
# token is right, (2) check greenhouse.py is running, (3) check the number is
# a whole number in range, (4) write the request to pump_request.json, (5)
# answer "ok". This function NEVER starts the pump itself. greenhouse.py picks
# the file up within a second and applies its own limits again.
# Checking the same thing twice (here for a helpful message, there for
# safety) is deliberate: never trust input just because it came from "our"
# page. Anyone can send a request that does not come from your buttons.
# `methods=["POST"]` means this address only accepts POST (a request that
# changes something), never a plain page visit (GET).
# ----- end learn -----
@app.route("/api/pump", methods=["POST"])
def api_pump():
    """{"seconds": 10-25} to water now, or {"stop": true}."""
    require_login_for_changes()
    refuse_if_not_running()
    body = request.get_json(silent=True) or {}
    req = {"time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "user": logged_in_user()}
    if body.get("stop"):
        req["stop"] = True
        message = "pump stop requested"
    else:
        try:
            seconds = int(body.get("seconds"))
        except (TypeError, ValueError):
            abort(400, "seconds must be a whole number")
        # Checked here for a clear message; greenhouse.py enforces it again.
        if not config.PUMP_MIN_SECONDS <= seconds <= config.PUMP_MAX_SECONDS:
            abort(400, "seconds must be between {} and {}".format(
                config.PUMP_MIN_SECONDS, config.PUMP_MAX_SECONDS))
        req["seconds"] = seconds
        message = "watering for {} s requested".format(seconds)
    write_json(config.PUMP_REQUEST_FILE, req)
    log_event("web: {} {} (from {})".format(logged_in_user(), message, _client_address()))
    return jsonify({"ok": True, "message": message})


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(503)
def json_errors(err):
    """Short, plain error replies - never a stack trace that reveals internals."""
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": err.description}), err.code
    return "{} {}".format(err.code, err.description), err.code


# ----- learn -----
# `@app.after_request` (above) and `@app.before_request` are "hooks": Flask
# runs those functions around EVERY request. That is where the login check for
# the whole site and the security headers live, so no route can forget them.
# A line starting with @ above a function is a "decorator": it hands the
# function to Flask, which registers it. You do not call these functions
# yourself; Flask calls them when a matching request arrives.
# ----- end learn -----
if __name__ == "__main__":
    from waitress import serve
    print("Greenhouse web page on http://{}:{}".format(config.WEB_HOST, config.WEB_PORT), flush=True)
    serve(app, host=config.WEB_HOST, port=config.WEB_PORT, threads=4)
