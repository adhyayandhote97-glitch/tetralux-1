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
| 2 | Estimation engine (`tetralux/estimation/`) — recover ŝ from readings, validate vs ground truth | planned |
| 3 | Fault detection — saturation, low-signal, corrupted packets, multi-source ambiguity | planned |
| 4 | Fake telemetry (`tetralux/telemetry/`) — fixed-length binary packets, checksum, ~10–20 Hz | planned |
| 5 | Dashboard (`tetralux/dashboard/`) — live vectors, health, replay | planned |

## Project layout

```
src/tetralux/
  constants.py        # FACE_NAMES, FACE_NORMALS, MIN_EPSILON (single source of truth)
  sim/                # Phase 1: sun-vector simulator
  estimation/         # Phase 2 (stub)
  telemetry/          # Phase 4 (stub)
  dashboard/          # Phase 5 (stub)
tests/                # pytest suite
docs/architecture.md  # hardware map + locked math spec
```

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
