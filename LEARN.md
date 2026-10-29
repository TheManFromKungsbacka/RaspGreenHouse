# LEARN.md - how this greenhouse project is built, and why

Written for: you, the owner of the project, who wants to understand the
structure and the programming basics without reading every line.

You can delete this file whenever you like. The extra explanations inside the
code are marked so they are easy to find and remove too (see the last section).

---

## 1. The big picture

The project has **three jobs**, and each job is its own program:

```
 ┌────────────────┐    reads/writes     ┌──────────────────┐
 │  Sensors and   │ <─────────────────> │  greenhouse.py   │   job 1: decide
 │  relays (GPIO) │   (hardware/*.py)   │  (the "brain")   │   what to do
 └────────────────┘                     └─────────┬────────┘
                                                  │ small JSON files
                                                  │ (statefiles.py)
                                        ┌─────────┴────────┐
 browser / phone  <───── HTTP ────────> │   web/app.py     │   job 2: show it
                                        │  (the web page)  │   and take orders
                                        └──────────────────┘

 systemd (*.service files)  =  job 3: start both programs at boot and
                               restart them if they crash
```

### The most important design decision

**Only ONE program ever touches the hardware: `greenhouse.py`.**

The web page never switches a relay. When you press "Water now", the web page
writes a small file (`pump_request.json`). `greenhouse.py` looks for that file
every second, checks it, and does the work.

Why?

1. **Safety lives in one place.** The rule "the pump runs 10-25 seconds, never
   more" is enforced in the program that owns the pump. A bug or a hacker on
   the web page cannot get around it.
2. **No fighting.** Two programs driving the same pin would give strange
   results. With one owner, that cannot happen.
3. **The web page can be less trusted.** It is the part that might one day be
   reachable from the internet, so it gets no hardware access at all.
4. **Either can crash alone.** If the web page crashes, the lamp and watering
   carry on. If you are editing the web page, the plants do not notice.

### The second most important decision: three layers

Every file belongs to one of three layers. A layer only talks to the one below.

| Layer | Question it answers | Files |
|-------|--------------------|-------|
| Decisions | "WHAT should happen, and WHEN?" | `greenhouse.py`, `web/app.py` |
| Hardware | "HOW do I talk to this device?" | `hardware/*.py` |
| Settings | "WHICH pin / time / limit?" | `config.py` |

Example: `greenhouse.py` decides "it is 06:00, the light should be on". It does
not know that the light is on GPIO20 or that the relay is active-low. It just
calls `relays.turn_on("light")`. `relays.py` knows the pin and the electrical
details. `config.py` stores the number 20.

The payoff: if you move the lamp wire to another pin, you change **one number**
in `config.py`. If you replace the relay board with a smart plug, you rewrite
only `relays.py`, and `greenhouse.py` is untouched.

---

## 2. The folder structure

```
Rasp/
├── config.py                  every setting, in one place
├── statefiles.py              helpers for the shared files + the event log
├── greenhouse.py              the brain (daily program)
├── greenhouse.service         tells Linux to run greenhouse.py
├── set_password.py            creates the web login (run once)
├── hardware/                  "how to talk to the devices"
│   ├── __init__.py            marks the folder as a Python package
│   ├── relays.py              light, pump, fan
│   ├── moisture.py            soil moisture via the MCP3008 chip
│   ├── temperature.py         DS18B20 temperature sensor
│   └── camera.py              Pi camera
├── web/                       the web page
│   ├── app.py                 the server (Flask)
│   ├── templates/             HTML that the server fills in
│   │   ├── index.html         the main page
│   │   └── login.html         the login page
│   └── static/                files sent unchanged to the browser
│       ├── app.js             live updates and button presses
│       └── style.css          looks
├── greenhouse-web.service     tells Linux to run web/app.py
├── test_all.py + test_*.py    check each device by hand
├── README.md                  short project overview
└── LEARN.md                   this file
```

Why this layout?

- **One file = one reason to change.** If the temperature sensor misbehaves you
  open `temperature.py`, and nothing else. You never scroll through 1000 lines.
- **`hardware/` is a folder** because the four modules belong together and
  have the same job. Python calls a folder with an `__init__.py` a *package*.
- **`web/` is separate** because it is a different program with different
  tools (Flask, HTML, JavaScript). Flask expects the names `templates/` and
  `static/` - those are not my choice, they are Flask's convention.
- **Test scripts sit at the top** so you can run `python3 test_relays.py`
  without typing a path.
- **Files that change while the program runs** (`status.json`, `state.json`,
  logs, photos) are listed in `.gitignore` so they stay out of GitHub. So is
  `web_auth.json`, because it holds your password hash.

---

## 3. Basics you need to read this code

### Python in 10 lines

```python
name = "pump"                       # a variable
RELAY_PINS = {"light": 20}          # a dict: look things up by name
RELAY_PINS["light"]                 # -> 20
def turn_on(name):                  # a function; the indented lines are its body
    print("on", name)
if temp > 28: ...                   # a decision
for name in RELAY_PINS: ...         # a loop
try: ... except OSError: ...        # "try this, and if it fails, do that instead"
import config                       # use another file
config.WATER_TIME                   # -> "07:30"
```

### Words that come back again and again

| Word | Meaning in this project |
|------|------------------------|
| **GPIO** | The Pi's pins. Each can be set HIGH (3.3 V) or LOW (0 V). |
| **Relay** | An electric switch. A tiny signal from the Pi switches the mains/12 V device. |
| **ADC / MCP3008** | A chip that turns a voltage into a number, because the Pi cannot read voltages. |
| **JSON** | Text format for data: `{"temperature": 23.1}`. Both Python and JavaScript read it. |
| **systemd / service** | Linux's manager for programs that must always run. |
| **Flask** | A Python library that turns functions into web pages. |
| **API route** | A web address that returns data instead of a page, e.g. `/api/status`. |
| **CSRF token** | A secret value that proves a button press came from *our* page, not another website. |
| **Hash** | One-way scrambled password. It can check a password but not reveal it. |
| **Dry run** | Run the program but switch nothing; it only prints what it would do. |

### How a program "runs all the time"

`greenhouse.py` is an endless loop:

```
while True:
    look at the clock and sensors
    decide what every device should do
    do it (only if it changed)
    sleep 1 second
```

It does **not** say "turn the light on at 06:00 and then wait". Every second it
asks "what *should* the state be right now?" and makes it so. That is why a
power cut does no harm: after the restart, the first loop round works out the
right state by itself. This idea - *describe the wanted state, not the steps* -
is the most useful thing in this project to take with you.

---

## 4. File by file

### config.py - the settings

**What it is:** nothing but names and values (`LIGHT_ON_TIME = "06:00"`). No
logic.

**Why it exists:** every other file imports from it. One place to look, one
place to change. Comments next to each number say what the number means and
why it has that value.

**Things to notice:**
- `BASE_DIR` is found automatically from the file's own location, and other
  paths are built from it. Move the folder and nothing breaks.
- Dictionaries like `MOISTURE_SENSORS` hold one entry per sensor. Adding a
  third sensor means adding one line there; the code loops over the dict.
- Names in CAPITAL LETTERS are a Python habit for "constant, do not change
  while running".

**Change it when:** you move a wire, calibrate a sensor, or want different
times/temperatures.

### statefiles.py - shared files and the event log

**What it is:** four small helpers: `log_event` (print + append to the log),
`read_json`, `write_json`, `recent_events`.

**Why it exists:** both `greenhouse.py` and `web/app.py` need to read and write
the shared files and the log. Putting the helpers in a file with **no hardware
imports** lets the web page use them without needing GPIO.

**The clever part is `write_json`.** It writes to `status.json.tmp` and then
*renames* it over `status.json`. A rename is all-or-nothing on Linux, so the
other program never reads a half-written file. Without this, you would
sometimes get a broken page for no visible reason.

**`read_json` returns a default if the file is missing or damaged**, instead of
crashing. Programs that run for months must expect that files can be missing.

### hardware/__init__.py

An almost empty file. Its existence tells Python "this folder is a package", so
you can write `from hardware import relays`. The text inside is documentation.

### hardware/relays.py - light, pump, fan

**What it is:** `setup()`, `turn_on(name)`, `turn_off(name)`, `is_on(name)`,
`run_for(name, seconds)`, `cleanup()`.

**Why it exists:** to hide two annoying facts from the rest of the code:
(1) the relay board is "active low" (LOW = on) and (2) pin numbers.
Callers say `turn_on("pump")` and never think about LOW/HIGH.

**Safety features:**
- Pins start in the OFF level (`initial=OFF_LEVEL`) so relays do not click on
  for a moment while starting up.
- A background **timer** switches the pump off after `PUMP_MAX_SECONDS`, no
  matter what the rest of the program does. It is the last line of defence
  against a flood.
- `run_for` uses `try/finally` so the device is switched off even if you press
  Ctrl+C in the middle.

**Imports `RPi.GPIO`**, which only exists on a Pi. That is why `greenhouse.py`
has a dry-run stand-in: you can test the logic on any computer.

### hardware/moisture.py - soil moisture

**What it is:** reads a number 0-1023 from the MCP3008 chip over the SPI bus,
and converts it to a percentage.

**Why it is built like this:**
- `read_raw` follows the chip's datasheet: send three bytes, get the answer
  back in the last two. The odd-looking `(8 + channel) << 4` builds the byte
  that says "single measurement on channel N".
- `raw_to_percent` is a straight line between "dry air" and "in water", from
  the calibration numbers in `config.py`. Each sensor has its own pair.
- `read_moisture` takes five readings and uses the **median**. A cheap sensor
  jumps around; the median ignores a single wild reading better than an average.
- The SPI connection is opened lazily (`_get_spi`) the first time it is needed,
  not when the file is imported. Importing should never crash.

### hardware/temperature.py - DS18B20

**What it is:** reads a text "file" that Linux creates for the sensor and picks
the temperature out of it.

**Why it is simple:** Linux does the hard work (the 1-Wire protocol). To the
program, the sensor looks like a file in `/sys/bus/w1/devices/`.

**Defensive details:** it retries up to 10 times if the checksum fails, and
treats exactly 85.0 as "sensor just powered on, not a real reading". It raises
an error after the retries instead of looping forever - the old code could hang
the whole program on a loose wire.

### hardware/camera.py - photos

Takes a photo and names it by date and time so nothing is overwritten. The
`with PiCamera() as cam:` block guarantees the camera is closed afterwards;
otherwise the next photo fails because the camera is "busy". The library is
imported inside the function so a camera problem cannot break the other modules.

### greenhouse.py - the brain

The biggest file. Read it from the bottom up:

1. **`main()`** (bottom) - set up, then the endless loop described above.
2. **`control_light`, `control_fan`, `control_watering`, `control_photo`** -
   one function per device. Each takes the clock/temperature and decides.
3. **`set_device`** - the only function that actually switches a relay. It
   skips the call if the device is already in the wanted state, and logs the
   change with a reason. That is why the log says "fan ON (too hot: 28.4 C)"
   once rather than every second.
4. **`write_status` / `write_readings`** - output for the web page and for a
   spreadsheet (`logs/readings.csv`).
5. **Helpers** (`at_time`, `in_daily_window`, `job_is_due`) - small pure
   functions that answer yes/no questions about time. Easy to test.

**Design choices worth understanding:**

- **Light and fan are computed, not remembered.** Watering and the photo
  *are* remembered (`state.json`) because "did I water today?" cannot be
  worked out from the clock.
- **Remember before you pump.** `control_watering` saves "watered today"
  *before* starting the pump. If the program crashes mid-watering, it will not
  water again after the restart. A missed watering is better than a double one.
- **Hysteresis on the fan.** On at 28 C, off at 25 C. Between the two it keeps
  what it was doing. Otherwise a temperature hovering around 28 would click the
  fan on and off all day. The `cooling` variable remembers which side we are on.
- **The pump never blocks.** It sets `pump_until` and the loop checks every
  second. A `time.sleep(20)` would freeze the light, the fan and the web
  buttons for 20 seconds.
- **Everything is in `try/except`.** A loose sensor logs a WARNING and returns
  `None`; the rest keeps working.
- **`--dry-run`** swaps the real relays for `DryRunRelays`, a class with the
  same method names that only remembers state. The rest of the code cannot tell
  the difference. This is called *duck typing*: "if it quacks like a duck".
- **`finally:` at the end** switches every relay off when the program stops, so
  a stopped program can never leave the pump running.

### greenhouse.service and greenhouse-web.service - systemd

Plain text files that tell Linux: run this command as user `pi`, start it at
boot, restart it after a crash. Without them you would have to log in and start
the programs by hand after every power cut.

The web service has extra lines (`NoNewPrivileges`, `ProtectSystem=strict`,
`ReadWritePaths`) that fence the web server in. If the web page were ever
broken into, the attacker still could not change system files.

### set_password.py - create the login

Run once by you. Asks for a username and password, stores only the **hash** of
the password and a random **secret key** (used to sign the login cookie) in
`web_auth.json`. I did not create your password because only you should know
it. The file gets permission `600`, readable by the `pi` user only.

### web/app.py - the web server

Built with **Flask**: you write a normal Python function and attach a web
address to it with `@app.route("/something")`.

| Route | What it does |
|-------|--------------|
| `/` | The main page (`index.html`) |
| `/login`, `/logout` | Sign in/out |
| `/api/status` | All current data as JSON (the page polls this) |
| `/photo/<name>` | Sends the latest photo |
| `/api/relay/<name>` | Light/fan: on, off or auto (login needed) |
| `/api/pump` | Start or stop the pump (login needed) |

The file is long because of **security**, which is built in from the start:
password hashing, lock-out after 5 wrong tries, CSRF tokens, secure cookies,
and security headers. Each has a comment explaining what attack it stops. The
control routes do not switch anything; they write `overrides.json` or
`pump_request.json` for `greenhouse.py`.

**Waitress** (at the bottom) is the actual server. Flask's own server is only
for testing, and not safe to leave running.

### web/templates/ - HTML with holes in it

`index.html` and `login.html` are HTML with placeholders like `{{ user }}` and
`{% if user %}`. Flask (via Jinja2) fills those in before sending the page.
They are in `templates/` because that is the folder Flask looks in.

The page is mostly an empty skeleton. The numbers are filled in by JavaScript.

### web/static/app.js - the live part

Runs in the browser, not on the Pi. It:
1. asks `/api/status` every 5 seconds (every 1 second while the pump runs),
2. draws the answer into the page (`render*` functions),
3. sends button presses as small JSON messages (`send`).

**Why polling and not push?** Simplest thing that works. The cost is one tiny
request per 5 seconds.

**Two habits to notice:** text is inserted with `textContent`, never as HTML,
so a strange log line can never run as code. And output cards are built once
and then only *updated*; rebuilding them every 5 seconds would reset your
slider while you drag it.

### web/static/style.css - looks

Colours are defined once as variables (`--accent`, `--card`) at the top, and
redefined inside `@media (prefers-color-scheme: dark)`, so the page follows
the phone's dark mode with no extra code. The grid uses
`repeat(auto-fill, minmax(240px, 1fr))`: "as many 240px-or-wider columns as fit",
which gives one column on a phone and several on a PC.

### test_all.py and test_*.py - checks by hand

`test_all.py` tests every sensor and relay and prints a summary table. The
single-device scripts (`test_relays.py`, `test_moisture.py`,
`test_temperature.py`, `test_camera.py`) go deeper on one thing, and
`test_moisture.py` is also used for calibration.

They were built first (phase 1) so every part was proven working **before** the
decision logic was added on top. When something breaks later, you know whether
it is the hardware or the logic. Stop the greenhouse service before running
them, because both would try to drive the same pins.

---

## 5. Why was it built in this order?

1. **Phase 1 - test each component alone.** Cheap to debug: one device, one file.
2. **Phase 2 - the daily program.** Logic on top of parts that are known to work.
3. **Phase 3 - the web page.** A view and a remote control on top of the program.
4. **Then remote access** (ZeroTier) last, because it exposes everything else.

Build the small, checkable pieces first and stack on top. If something fails,
the broken piece is the newest one.

## 6. If you want to learn programming from this

Good order, easiest first:
1. `config.py` - just values.
2. `hardware/temperature.py` - one job, about 80 lines.
3. `statefiles.py` - small functions with clear purposes.
4. `greenhouse.py`, bottom-up: `main()`, then `control_light`, then the rest.
5. `web/static/app.js` and `index.html` - you will see how a page is made.
6. `web/app.py` last. It is mostly security detail.

**Experiments to try (dry run, no hardware needed):**
- Change `LIGHT_ON_TIME` and run `python3 greenhouse.py --dry-run --once`.
- Add a new sensor entry in `MOISTURE_SENSORS` and run `test_moisture.py`.
- Add a line to the schedule table in `renderSchedule` in `app.js`.

## 7. The `learn` blocks inside the code

Extra explanations of the programming were added to the code in blocks like:

```python
# ----- learn -----
# explanation...
# ----- end learn -----
```

They start with `----- learn` and end with `----- end learn -----`, in each
file's own comment style (`#`, `//`, `/* */`, `{# #}`), so they are easy to find.
Search for `----- learn` to see them all.

**To remove them all at once** in VS Code: open Search (`Ctrl+Shift+H`), enable
the regex button (`.*`), and replace this pattern with nothing:

```
(?s)[ \t]*(?:#|//|/\*|\{#) ----- learn.*?----- end learn -----(?: \*/| #\})?[ \t]*\r?\n
```

Use "Replace All" and check that Source Control shows only removed lines.
Remember: if the code was already copied to the Pi, copy the cleaned files too.
