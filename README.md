# Raspberry Pi Greenhouse

Monitors and controls a small greenhouse with a Raspberry Pi 3.

| Type   | Device                | Connection                              |
|--------|-----------------------|-----------------------------------------|
| Sensor | Temperature (DS18B20) | 1-Wire, GPIO4                           |
| Sensor | Soil moisture 1       | MCP3008 ADC channel 0, SPI bus 0        |
| Sensor | Soil moisture 2       | MCP3008 ADC channel 1, SPI bus 0        |
| Sensor | Camera module         | CSI ribbon cable                        |
| Output | UV grow light         | Relay on GPIO20 (active low)            |
| Output | Water pump            | Relay on GPIO23 (active low)            |
| Output | Fan                   | Relay on GPIO25 (active low)            |

All pin numbers and calibration values live in [config.py](config.py).

## Project layout

```
config.py            all settings (pins, calibration, limits)
hardware/            one module per device - "how to talk to it"
  temperature.py
  moisture.py
  camera.py
  relays.py
greenhouse.py        the daily program (light, fan, watering, photo)
greenhouse.service   systemd file that keeps greenhouse.py running
statefiles.py        the shared files greenhouse.py and the web page talk through
web/                 the web page (app.py, templates/, static/)
greenhouse-web.service  systemd file for the web page
set_password.py      create or change the web page login
test_all.py          tests every sensor and output in one run, with a summary
test_temperature.py  test scripts - one device at a time, in more detail
test_moisture.py
test_camera.py
test_relays.py
```

## Phase 1: test each component

Run from this folder on the Pi (`cd /home/pi/Greenhouse/Rasp`):

```bash
python3 test_all.py              # everything in one run (asks before each relay)
python3 test_all.py --sensors-only
python3 test_temperature.py      # 5 readings, should be near room temperature
python3 test_moisture.py         # 10 readings; also used for calibration
python3 test_camera.py           # takes one photo into photos/
python3 test_relays.py light     # light on for 3 s
python3 test_relays.py fan       # fan on for 3 s
python3 test_relays.py pump      # pump on (minimum 10 s, maximum 25 s)
python3 test_relays.py           # interactive on/off menu
```

## Phase 2: the daily program

`greenhouse.py` runs all the time as a systemd service and, every 30 seconds:

| Device | Rule (settings in the "DAILY PROGRAM" section of config.py) |
|--------|--------------------------------------------------------------|
| Light  | on 06:00-20:00 (14 h, suits herbs)                           |
| Fan    | on above 28 C until 25 C, plus 10 min every hour for air     |
| Pump   | 20 s at 07:30 every day (moisture logged, not used)          |
| Camera | one photo a day at 12:00                                     |

Readings are written every 10 minutes to `logs/readings.csv`, events
(light on, watering, warnings) to `logs/events.log`.

```bash
python3 greenhouse.py --dry-run --once     # show the decisions, switch nothing
sudo cp greenhouse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greenhouse     # start now and at every boot
systemctl status greenhouse
sudo systemctl stop greenhouse             # stop BEFORE running the test_*.py scripts
```

## Next

- Temperature history chart on the web page (from logs/readings.csv)
- External access (Tailscale or Cloudflare Tunnel), or a phone app
- Better moisture sensors, then watering based on moisture
- Camera-based growth tracking and anomaly detection

## Phase 3: the web page

`web/app.py` shows all sensor values, the state of every output, the schedule,
the latest photo and recent events. After logging in you can switch the light
and fan (they return to automatic after 2 hours) and run or stop the pump
(10-25 s). The page never touches the GPIO pins: it leaves requests in small
files and `greenhouse.py` carries them out with its own safety limits, so
greenhouse.py must be running for the buttons to work.

```bash
python3 set_password.py                    # once: choose username + password
sudo cp greenhouse-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greenhouse-web
```

Open http://<pi-ip>:8080 on the home network.

Security settings are in the "WEB PAGE" section of config.py. Before the page
is reachable from the internet: set `WEB_PUBLIC_VIEW = False` (login needed
to look too) and, once it runs over HTTPS, `WEB_COOKIE_SECURE = True`.
