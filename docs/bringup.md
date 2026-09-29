# Tetralux-1 — Hardware Bring-Up Runbook

A mechanical, in-order checklist for going from a soldered/wired 1U CubeSat
prototype to trusted live telemetry on the ground-station dashboard. Do the
steps in order — each one isolates a smaller set of possible failures than the
next, so skipping ahead makes debugging much harder.

Everything referenced here (`groundstation.py`, `calibration_tool.py`, the
dashboard) is already built and tested against the **simulated device feed** —
this runbook is what changes when a real board replaces that simulation.

---

## 1. Bench power-up

Before wiring any sensors:

- Power the Arduino Nano 33 IoT alone (USB is fine) and open a Serial Monitor
  at 115200 baud (`SERIAL_BAUD` in `firmware/include/config.h`).
- Confirm it boots without hanging (a hung `setup()` usually means an I2C
  device isn't responding — but you haven't wired sensors yet, so this should
  just boot clean).
- Double-check every pin assignment in `firmware/include/config.h` against
  your actual wiring **before** connecting anything — a wrong pin is much
  easier to fix now than after everything is glued into the frame.

## 2. Firmware flash

- Copy `firmware/include/secrets.h.example` to `firmware/include/secrets.h`
  (gitignored — never commit this) and fill in your WiFi SSID/password and the
  ground station's IP + port.
- `cd firmware && pio run -t upload` (PlatformIO), or open in Arduino IDE with
  the equivalent library installs from `platformio.ini`'s `lib_deps`.
- Watch the Serial Monitor: you should see JSON lines start printing once
  `loop()` begins (Serial fallback fires immediately if WiFi isn't connected
  yet, which is expected at this stage).

## 3. Serial-first smoke test

Verify the checksum/structure contract **before** WiFi enters the picture —
if this step fails, the problem is in the packet itself, not networking.

```bash
python -m tetralux.groundstation --serial /dev/tty.usbmodemXXXX --record
```

In another terminal:
```bash
curl -s http://127.0.0.1:8000/health
```

Confirm:
- `total_accepted` is climbing every poll.
- `total_rejected` stays at **0** — any rejection here means the firmware's
  JSON/checksum doesn't match `tetralux.telemetry.json_frame` yet (see the
  troubleshooting table below).
- `connected: true`.

## 4. WiFi bring-up

Once step 3 is clean:

- Leave the ground station running on `--port` (same as `SERVER_PORT` in
  `secrets.h`).
- Power-cycle the board so it attempts WiFi from `setup()`.
- Confirm the firmware's `flags` bit 0 flips to 1 once associated — the
  decoded record's `flags` field (or a quick `curl .../ingest` inspection)
  should show it.
- Once WiFi frames are confirmed arriving at `/health`, **unplug the USB
  serial connection** (or stop the `--serial` ground station) so only one
  physical path feeds the queue — running both simultaneously will double up
  frames with duplicate sequence numbers and confuse `StreamMonitor`'s
  gap-detection.

## 5. Dashboard live check

Stop the ground station from step 4 first (it holds port 8000, and frames it
receives never reach the dashboard). The dashboard then listens itself:

```bash
python -m tetralux.dashboard --ingest-port 8000          # WiFi
python -m tetralux.dashboard --serial /dev/tty.usb…      # or USB serial
```

- Switch to **Real-time** mode (do *not* enable "Simulated device feed" — that
  would compete with your real hardware on the same ingest queue).
- Confirm 🟢 **Connected · N Hz** on the Live page.
- With the bench dark (sensors covered / lights off), you should see the
  **LOW_SIGNAL** fault and no sun vector — that's correct at this stage.
- Check every panel populates: raw photodiodes/lux, magnetometer, OPT4048
  values, and DS18B20 temperatures (a `null`/missing sensor shows up in the
  thermal panel's "missing" list rather than crashing anything).

## 6. Run the guided calibration

The dark/gain/max values in `calibration.py` are **placeholders from a
different prototype** — this step measures *your* sensors.

```bash
python -m tetralux.calibration_tool --port 8000 --out calibration.json
```

(Use `--serial /dev/tty...` instead of `--port` if you're still on serial.)
Follow the prompts in order:
1. **Dark** — cover all sensors / turn off all light.
2. **Gain** (once per face) — aim a known reference light dead-on at that
   face only.
3. **Max illumination** — present the brightest exposure you expect to test
   with.

The tool writes `calibration.json`. Point the ground station at it going
forward:

```bash
python -m tetralux.groundstation --port 8000 --record --calibration calibration.json
```

Or load it live from the dashboard's **Live** page ("Calibration file (Real
mode)" field + **Load calibration** button) without restarting anything.

## 7. Point-source validation

- Shine a single light source at a known angle relative to the cube.
- On the Live page, check `Angular error` — it should be within a few degrees
  of the true angle. If it's wildly off, revisit calibration (step 6) or
  double-check the face-normal-to-pin mapping in `config.h`.
- Move the light slowly and confirm the 3D Vector page's sun-vector arrow
  tracks it, and the Time-series page shows a smooth trace (not a jumpy or
  flat line).

## 8. (Optional) Firebase online logging

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/serviceAccount.json
export FIREBASE_DATABASE_URL=https://<project>.firebaseio.com
python -m tetralux.groundstation --port 8000 --record
```

Confirm the startup line: `[tetralux] Firebase RTDB online logging enabled.`
If it's silent, the ground station is still logging locally (JSONL is always
written) — check both env vars are set and the credentials file is valid.

## 9. Troubleshooting table

| Symptom (`RejectedFrame.reason` / `/health`) | Likely cause |
|---|---|
| `"missing chk field"` | Firmware isn't appending `,"chk":N}` — check `packet.cpp`'s `build_packet()` return value isn't 0 (buffer too small). |
| `"checksum mismatch: transmitted X, computed Y"` | Firmware and `xor_checksum()` disagree on the checksummed byte range — reconfirm it's XOR'd **up to but not including** `,"chk"`, over the *exact transmitted bytes* (not a re-serialized copy). |
| `"pd value out of range 0-1023"` | ADC wiring issue, wrong analog pin, or a mux channel swap — verify `PIN_PD_*` in `config.h` against physical wiring. |
| `"opt must have 4 items"` / malformed `opt` | OPT4048 mux channel read failing silently — check `MUX_CHANNEL_OPT4048_BASE` and I2C address `0x44`; the OPT4048 driver in `firmware/src/sensors/opt4048.cpp` is a first draft (see its header comment) — verify register addresses against your specific datasheet revision. |
| Temperature always `null` | DS18B20 one-wire pin/pull-up issue, or `DEVICE_DISCONNECTED_C` (-127°C) from the library — check wiring and the 4.7kΩ pull-up resistor on each one-wire line. |
| `total_rejected` climbs but `seq` looks sequential | Almost always a checksum contract mismatch, not a dropped-packet problem — see the checksum row above. |
| Dashboard shows 🔴 Disconnected despite Serial Monitor showing JSON | `StreamMonitor`'s `timeout_s` (1.0s) elapsed since the last **accepted** (not just received) frame — if frames are being rejected, connection shows red even though data is arriving. Check `/health`'s `total_rejected`. |
| `flags` bit 0 never sets even though WiFi looks connected | `wifi_is_connected()` re-checks `WiFi.status()` every loop — a flaky AP or weak signal can bounce it; check RSSI, or bring the board closer to the AP during bring-up. |
