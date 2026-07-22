# Tetralux-1

A **software-only digital twin** of a 1U CubeSat sun-direction estimation
system. Hardware comes later — for now this repo is pure physics and math that
acts as ground truth for every downstream phase.

## What it does

A 1U CubeSat carries six face-mounted photodiodes (`+x`, `-x`, `+y`, `-y`, `+z`,
`-z`). By comparing how brightly each face is lit, the system estimates a unit
vector pointing toward the dominant light source (the "sun vector") using a
normalized-weight model:

```
w_i = R_i / Σ R_j          # each face's share of total signal
d   = Σ w_i · n̂_i          # weighted sum of face normals
ŝ   = d / |d|              # final unit sun vector
```

The full, locked math specification (16 formulas covering estimation, solar
radiation pressure, validation, thermal, and color) lives in
[`docs/architecture.md`](docs/architecture.md).

## Phase roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **0** | Project scaffolding (src layout, tests, packaging) | ✅ done |
| **1** | Sun-vector **simulator** (`tetralux/sim/`) — pure forward model / ground truth | ✅ done |
| **2** | Estimation engine (`tetralux/estimation/`) + validation/physics/spectral (formulas 1–16) | ✅ done |
| **3** | Fault detection (`tetralux/faults/`) — low-signal, saturation, multi-source; packet-integrity primitives | ✅ done |
| **4** | Fake telemetry (`tetralux/telemetry/`) — 17-byte binary packets, 8-bit checksum, resync parser, ~10–20 Hz | ✅ done |
| **5** | Dashboard (`tetralux/dashboard/`) — Plotly Dash: 3D vector, face bars, error timeline, fault health, replay | ✅ done |
| **6–9** | **Ground station** — real JSON ingestion, full sensor pipeline, Firebase RTDB logging, multi-page dashboard (Virtual/Real) | ✅ done |
| **10** | **Hardware bring-up** — firmware (`firmware/`), guided calibration tool, [`docs/bringup.md`](docs/bringup.md) runbook | ✅ done |

## Project layout

```
src/tetralux/
  constants.py        # FACE_NAMES, FACE_NORMALS, MIN_EPSILON, ADC/CCT/window constants
  frames.py           # SensorFrame / RejectedFrame contract (matches real firmware JSON)
  calibration.py      # corrected readings, cosine proxy, irradiance (formulas 1,5) + save/load
  calibration_tool.py # Phase 10: guided dark/gain/max calibration CLI
  record.py           # GroundStationRecord (everything the UI shows) + JSON-safe to_dict
  pipeline.py         # process(frame) -> record, chaining every phase
  groundstation.py    # CLI: HTTP+serial ingest -> processing -> record (real path)
  sim/                # Phase 1/7: photodiode simulator + full virtual sensor synthesis
  estimation/         # Phase 2: estimator (formulas 1-5) + az/el + LowSignalError
  validation/         # Phase 2/6: metrics (11-14) + RollingValidator + burst_metrics
  physics/  spectral/ # Phase 2: SRP (6-10); CIE + McCamy CCT + OPT trust gate (15-16)
  faults/             # Phase 3: fault detection + packet-integrity primitives
  telemetry/          # Phase 4/6: binary packet codec + real JSON codec (XOR checksum)
  thermal/            # Phase 6: DS18B20 drift / rolling stats
  ingest/             # Phase 6: HTTP + serial ingest, StreamMonitor
  store/              # Phase 8: local JSONL + Firebase RTDB + session control + query
  dashboard/          # Phase 9: multi-page Dash app (Virtual/Real), units registry
firmware/             # Phase 10: Arduino Nano 33 IoT firmware (PlatformIO project)
tests/                # pytest suite (123 tests)
docs/architecture.md  # hardware map + locked math spec + ground-station design
docs/bringup.md       # Phase 10: hardware bring-up runbook
```

## Running the ground-station dashboard

Needs the `dashboard` extra (Dash + Plotly):

```bash
pip install -e ".[dashboard]"
python -m tetralux.dashboard      # serves http://127.0.0.1:8050
```

Pages: **Live** (Virtual/Real toggle), **3D Vector**, **Light in 3D**,
**Time-series**, **History / Logs**, **About**.

- **Virtual mode** — the azimuth/elevation sliders drive an *instantaneous*
  recompute of every value (sun vector, weights, angular error, bias,
  repeatability, OPT trust, temperatures …). No stream, no timeline.
- **Real mode** — a live telemetry stream fills a rolling buffer; azimuth/
  elevation are read-only and a connection indicator shows link health. Use the
  **Simulated device feed** toggle to demo the real path without hardware.
- **History / Logs** — browse recorded sessions (with size/duration/packet
  count), filter by a time range, and export a CSV.

Every displayed value carries its unit (or is labeled "dimensionless").

## Running the real ingest server (for a physical prototype)

Needs the `ingest` extra (`fastapi`, `uvicorn`, `pyserial`):

```bash
pip install -e ".[ingest]"
python -m tetralux.groundstation --port 8000 --record        # WiFi HTTP POST
python -m tetralux.groundstation --serial /dev/tty.usb… --record  # USB serial
```

The firmware POSTs newline-delimited JSON (`seq,ts,pd,lux,mag,opt,temp,flags,chk`,
8-bit XOR checksum) to `/ingest`. `--record` starts a logging session (off by
default). Point `python -m tetralux.dashboard` at the same machine to view it.

## Hardware bring-up (firmware + calibration)

Flashing and wiring instructions live in [`docs/bringup.md`](docs/bringup.md);
the Arduino firmware is in [`firmware/`](firmware/) (PlatformIO project — copy
`firmware/include/secrets.h.example` to `secrets.h`, fill in your WiFi/server
details, `pio run -t upload`).

Once telemetry is flowing, measure *this* prototype's actual dark/gain/max
values (the defaults in `calibration.py` are generic placeholders):

```bash
python -m tetralux.calibration_tool --port 8000 --out calibration.json
python -m tetralux.groundstation --port 8000 --record --calibration calibration.json
```

Or load a calibration file live from the dashboard's Live page without
restarting anything.

## Online logging (Firebase Realtime Database)

Full per-packet logging goes to Firebase RTDB (one node per packet). Needs the
`firebase` extra and your own credentials (never committed):

```bash
pip install -e ".[firebase]"
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/serviceAccount.json
export FIREBASE_DATABASE_URL=https://<project>.firebaseio.com
```

A **local JSONL mirror is always written** regardless, so full fidelity is
preserved offline. See `docs/architecture.md` for the rate/cost trade-offs.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Quick example

```python
import numpy as np
from tetralux.sim.simulator import simulate_faces

faces = simulate_faces(np.array([1.0, 0.0, 0.0]), intensity=1000.0)
print(faces["+x"])   # {'reading': 1000.0, 'saturated': False}  <- max
print(faces["-x"])   # {'reading': 0.0,    'saturated': False}  <- facing away
```
