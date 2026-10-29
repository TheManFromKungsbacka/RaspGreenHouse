/* app.js - keeps the greenhouse page up to date and sends button presses.

   Every few seconds it asks the server for /api/status and fills in the page.
   Buttons send small JSON requests with the CSRF token from the page's
   <meta> tag; the server refuses any change without it.

   All text from the server is inserted with textContent, never as HTML, so a
   strange value in a log line can never run as code on the page. */

"use strict";

const LOGGED_IN = document.body.dataset.loggedIn === "yes";
const CSRF = document.querySelector('meta[name="csrf-token"]').content;
const POLL_MS = 5000;       // normal refresh
const POLL_FAST_MS = 1000;  // while the pump runs, to show the countdown

const LABELS = { light: "Grow light", fan: "Fan", pump: "Water pump" };

let latest = null;          // last answer from /api/status
let pollTimer = null;

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function $(id) { return document.getElementById(id); }

// ----- learn -----
// The page is changed by JavaScript through the DOM: the browser's live tree of
// everything on the page. `document.createElement("p")` makes a new element in
// memory, `.textContent = "..."` sets its text, `.append(child)` hangs it in
// the page. This tiny helper el() does the three steps in one call, so the
// rest of the file can build a whole card in a few readable lines.
// `$(id)` is only a short name for document.getElementById(id).
// textContent (not innerHTML) is a security habit: it shows text as text, so a
// log line containing <script> can never run.
// ----- end learn -----
function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}

function hhmm(iso) {
  return iso ? iso.slice(11, 16) : "–";
}

// Seconds between two ISO times from the server. Using the server's own
// "now" avoids errors if the phone's clock is a little off.
function secondsBetween(fromIso, toIso) {
  return Math.round((new Date(toIso) - new Date(fromIso)) / 1000);
}

function toast(message, isError) {
  const t = $("toast");
  t.textContent = message;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4000);
}

// ---------------------------------------------------------------------------
// Talking to the server
// ---------------------------------------------------------------------------

// ----- learn -----
// `fetch` asks the server for something over the network. That takes time, so
// it returns a "promise" instead of an answer. `await` means "pause THIS
// function here until the answer arrives, but let the rest of the page keep
// working". A function that uses await must be marked `async`.
// Why try/catch? If the Pi is unreachable, fetch throws an error. We catch it
// and show "No connection" instead of the page silently stopping.
// poll() then schedules itself again with setTimeout: a simple loop that runs
// every 5 s (or every 1 s while the pump runs, to show the countdown).
// `const` is a variable that is never reassigned; `let` one that is.
// ----- end learn -----
async function poll() {
  clearTimeout(pollTimer);
  try {
    const res = await fetch("/api/status", { credentials: "same-origin", cache: "no-store" });
    if (res.status === 401) { window.location = "/login"; return; }
    latest = await res.json();
    render(latest);
  } catch (err) {
    setRunStatus("No connection to the Pi", "pill-bad");
  }
  const pumpOn = latest && latest.status && latest.status.outputs.pump.on;
  pollTimer = setTimeout(poll, pumpOn ? POLL_FAST_MS : POLL_MS);
}

async function send(url, body, okText) {
  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      toast("Your login has expired - please log in again.", true);
      setTimeout(() => { window.location = "/login"; }, 1500);
      return;
    }
    if (!res.ok) { toast(data.message || "Error " + res.status, true); return; }
    toast(okText || data.message);
  } catch (err) {
    toast("No connection to the Pi", true);
  }
  // greenhouse.py acts within about a second; refresh shortly after.
  setTimeout(poll, 1200);
}

// ---------------------------------------------------------------------------
// Drawing the page
// ---------------------------------------------------------------------------

function setRunStatus(text, cls) {
  const p = $("run-status");
  p.textContent = text;
  p.className = "pill " + cls;
}

function render(data) {
  const s = data.status;
  if (!data.running || !s) {
    setRunStatus("Program not running", "pill-bad");
    $("updated").textContent = s ? "last data " + hhmm(s.updated) : "";
  } else {
    setRunStatus(s.dry_run ? "Running (dry run)" : "Running", s.dry_run ? "pill-manual" : "pill-on");
    const age = s.sensors_read ? secondsBetween(s.sensors_read, data.now) : null;
    $("updated").textContent = age === null ? "" : "sensors read " + age + " s ago";
  }
  if (s) {
    renderSensors(s);
    renderOutputs(s, data.running);
    renderSchedule(s.schedule);
  }
  renderPhoto(data.photo);
  renderEvents(data.events);
}

function renderSensors(s) {
  const card = $("temp-card");
  const t = s.temperature;
  $("temp-value").textContent = t === null ? "–" : t.toFixed(1);
  card.classList.toggle("is-hot", t !== null && t >= s.schedule.fan_on_temp);
  card.classList.toggle("is-cold", t !== null && t < s.schedule.temp_low_warning);
  let note = "Herbs like about 18–27 °C";
  if (t === null) note = "Sensor not responding";
  else if (t >= s.schedule.fan_on_temp) note = "Hot – fan cooling";
  else if (t < s.schedule.temp_low_warning) note = "Too cold for basil";
  $("temp-note").textContent = note;

  // One card per moisture sensor, created the first time we see it.
  for (const [name, m] of Object.entries(s.moisture)) {
    let c = document.getElementById("moist-" + name);
    if (!c) {
      c = el("article", "card");
      c.id = "moist-" + name;
      c.append(el("h3", "", "Soil moisture – " + name));
      const big = el("p", "big");
      big.append(el("span", "value"), el("span", "unit", "%"));
      const bar = el("div", "bar");
      bar.append(el("span"));
      c.append(big, bar, el("p", "muted small raw"));
      $("sensors").append(c);
    }
    c.querySelector(".value").textContent = m.percent;
    c.querySelector(".bar > span").style.width = Math.max(0, Math.min(100, m.percent)) + "%";
    c.querySelector(".raw").textContent = "raw " + m.raw + " · rough value, for info only";
  }
}

// The output cards are built once, then only updated. Rebuilding them every
// few seconds would reset the pump slider while you are moving it.
function buildOutputCard(name, s) {
  const c = el("article", "card output");
  c.id = "out-" + name;
  const head = el("div", "output-head");
  head.append(el("h3", "", LABELS[name] || name), el("span", "pill mode"));
  c.append(head, el("p", "state"), el("p", "muted small reason"));

  const controls = el("div", "controls");
  controls.hidden = !LOGGED_IN;
  if (name === "pump") {
    const min = s.schedule.pump_min_seconds, max = s.schedule.pump_max_seconds;
    const row = el("label", "pump-seconds");
    const slider = document.createElement("input");
    slider.type = "range"; slider.min = min; slider.max = max; slider.value = min;
    slider.setAttribute("aria-label", "Pump seconds");
    const shown = el("span", "", min + " s");
    slider.addEventListener("input", () => { shown.textContent = slider.value + " s"; });
    row.append(slider, shown);
    const go = el("button", "btn btn-primary water", "Water now");
    go.addEventListener("click", () => {
      const secs = Number(slider.value);
      if (confirm("Run the pump for " + secs + " seconds?")) {
        send("/api/pump", { seconds: secs }, "Watering for " + secs + " s requested");
      }
    });
    const stop = el("button", "btn btn-danger stop", "Stop");
    stop.addEventListener("click", () => send("/api/pump", { stop: true }, "Stopping the pump"));
    controls.append(row, go, stop);
  } else {
    const seg = el("div", "segmented");
    for (const mode of ["on", "off", "auto"]) {
      const b = el("button", "btn", mode === "auto" ? "Auto" : mode.toUpperCase());
      b.dataset.mode = mode;
      b.addEventListener("click", () => send("/api/relay/" + name, { mode: mode }));
      seg.append(b);
    }
    controls.append(seg);
  }
  c.append(controls);
  $("outputs").append(c);
  return c;
}

// ----- learn -----
// "Build once, then update" (see buildOutputCard above). On the first call
// there is no element with id "out-pump", so `||` runs the right-hand side and
// builds it. On later calls getElementById finds it and the builder is skipped.
// `a || b` means "a if it exists, otherwise b".
// `for (const [name, o] of Object.entries(s.outputs))` loops over a dict from
// the server, giving each key and value. It is the JavaScript twin of Python's
// `for name, o in outputs.items()`.
// `classList.toggle("is-on", o.on)` adds the CSS class when o.on is true and
// removes it when false. The page's look is changed by flipping classes; the
// colours themselves live in style.css, not here.
// ----- end learn -----
function renderOutputs(s, running) {
  for (const [name, o] of Object.entries(s.outputs)) {
    const c = document.getElementById("out-" + name) || buildOutputCard(name, s);
    c.classList.toggle("is-on", o.on);
    c.querySelector(".state").textContent = o.on ? "ON" : "Off";

    const manual = o.mode === "manual";
    const mode = c.querySelector(".mode");
    mode.textContent = manual ? "Manual" : "Auto";
    mode.className = "pill mode " + (manual ? "pill-manual" : "pill-off");

    let reason = o.reason || "";
    if (name === "pump" && o.on && o.until && latest) {
      const left = Math.max(0, secondsBetween(latest.now, o.until));
      reason += " – " + left + " s left";
    } else if (manual && o.until) {
      reason += " (then automatic)";
    }
    c.querySelector(".reason").textContent = reason;

    // Buttons only work while greenhouse.py runs; grey them out otherwise.
    c.querySelectorAll("button").forEach((b) => { b.disabled = !running; });
    if (name === "pump") {
      c.querySelector(".water").disabled = !running || o.on;
      c.querySelector(".stop").disabled = !running || !o.on;
    } else {
      const active = manual ? (o.on ? "on" : "off") : "auto";
      c.querySelectorAll(".segmented .btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.mode === active);
      });
    }
  }
}

function renderSchedule(sch) {
  const days = sch.water_every_days === 1 ? "every day" : "every " + sch.water_every_days + " days";
  const rows = [
    ["Grow light", sch.light],
    ["Fan cooling", "on at " + sch.fan_on_temp + " °C, off at " + sch.fan_off_temp + " °C"],
    ["Fan airing", sch.fan_circulate_minutes + " min every hour"],
    ["Watering", sch.water_time + ", " + sch.water_seconds + " s, " + days],
    ["Next watering", sch.next_watering ? sch.next_watering.replace("T", " ") : "–"],
    ["Last watered", sch.last_watered || "–"],
    ["Daily photo", sch.photo_time],
  ];
  const dl = $("schedule");
  dl.replaceChildren();
  for (const [k, v] of rows) dl.append(el("dt", "", k), el("dd", "", v));
}

function renderPhoto(name) {
  const img = $("photo");
  if (!name) return;
  const src = "/photo/" + encodeURIComponent(name);
  if (img.getAttribute("src") !== src) img.src = src;  // only reload when a new photo exists
  img.hidden = false;
  // Photo names look like 2026-10-25_14-53-42.jpg
  const m = name.match(/^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})/);
  $("photo-caption").textContent = m ? "Taken " + m[1] + " " + m[2] + ":" + m[3] : name;
}

function renderEvents(events) {
  const ol = $("events");
  ol.replaceChildren();
  if (!events.length) ol.append(el("li", "muted", "No events yet"));
  for (const line of events) {
    const cls = line.includes("WARNING") ? "warn" : line.includes(" web: ") ? "web" : "";
    ol.append(el("li", cls, line));
  }
}

poll();
