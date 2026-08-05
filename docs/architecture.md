# Tetralux-1 — Architecture & Math Reference

This document is the durable reference for every phase. Future phases should
read it instead of re-deriving hardware details or math.

---

## 1. Hardware map (context for later phases)

- **6× S1223 photodiodes** (analog, face-mounted) — **primary direction
  sensing**. One per cube face: `+x`, `-x`, `+y`, `-y`, `+z`, `-z`.
- **6× BH1750** (I2C, digital lux) — ambient/brightness context. **Not** used in
  the estimation math directly.
- **QMC5883L magnetometer** — yaw/heading reference; an independent validation
  layer.
- **4× OPT4048** (I2C) — tristimulus color validation; produces a boolean
  "trusted illumination profile" flag. Mounted on cube **edges**, not faces.
- **6× DS18B20** — thermal monitoring; unrelated to direction estimation.
- **Telemetry** — fixed-length binary packets, 8-bit checksum, ~10–20 Hz.

### Failure modes to design around

- Divide-by-zero when total light ≈ 0.
- Saturation clipping.
- Corrupted / truncated packets.
- Multi-source lighting giving an ambiguous "average" vector.

---

## 2. Design notes carried from the v0 prototype

A previous prototype (`Tetralux-1 (Code1)*/python/app/`) already implemented a
working `SunEstimator`. We do **not** reuse its code or its uppercase `+X` key
convention, but three design lessons carry forward:

1. **Raw-sum and normalized-weight forms are algebraically identical.** The old
   code computed `d = Σ R_i · n̂_i` on **raw** readings and then normalized to a
   unit vector. Dividing by the total `Σ R_j` first (to get weights `w_i`) only
   multiplies `d` by a positive scalar `1/Σ R_j`, which **cancels** at the final
   unit-normalization `ŝ = d/|d|`. So the direction output is the same either
   way. Consequence: the **simulator correctly emits raw readings**, and the
   estimator may normalize weights (per the locked spec) with no change to the
   result.
2. **Epsilon guard returns "no estimate", never NaN.** With `ε = 1e-9`, when the
   total signal is near zero the estimator must signal low-signal/invalid rather
   than divide by ~0 and emit a noise-driven garbage vector. This directly
   defends the *divide-by-zero when total light ≈ 0* failure mode. Two tiers: a
   per-face dead-band (`R_i < ε` dropped) and a whole-vector reject (`|d| < ε`).
3. **Saturation trips just below the hard rail.** The old ADC used
   `SATURATION_THRESHOLD = 1020` versus `ADC_MAX = 1023` — flagged a few counts
   below the true maximum for analog headroom. Downstream estimation must be able
   to **exclude saturated faces**, which is why the simulator emits a per-face
   `saturated` flag.

These are estimator/architecture notes. The Phase 1 simulator math is unchanged.

---

## 3. Math Specification (LOCKED)

The 16 formulas below are the single source of math truth for the whole project.
Use them **exactly** — do not substitute or "improve" them.

### Sun-direction estimation

> **Formulas 1–4 are the LOCKED sun-estimation pipeline.** No alternative
> weighting schemes, no least-squares fits, no calibration curves at this stage.

**1. Corrected face reading** — removes dark offset, applies per-face gain.

```
R_i = (V_i − D_i) · G_i
```
Example: `V_i=720, D_i=20, G_i=1.05 → R_i=735`.

**2. Face weight** — normalized share of total signal across all six faces.

```
w_i = R_i / Σ(R_j for j = 1..6)
```
Example: `R_i=735, total=2940 → w_i=0.25`.

**3. Direction vector from faces** — weighted sum of face normals.

```
d = Σ(w_i · n̂_i)
```
Example: if `+x` and `+y` are both strong, `d = (0.50, 0.25, 0.00)`.

**4. Estimated sun vector** — normalizes `d` into a unit vector (final output).

```
ŝ = d / |d|
```
Example: `d=(0.50,0.25,0.00) → |d|≈0.559 → ŝ≈(0.894,0.447,0.000)`.

> **Epsilon behavior (LOCKED).** If `Σ(R_j) < MIN_EPSILON (1e-9)`, treat the
> frame as low-signal/invalid and **raise `LowSignalError`** (a clearly-named
> exception) rather than dividing by near-zero and returning a silent garbage
> vector. The **same guard applies when normalizing `d`**: if `|d| < 1e-9`, that
> is also low-signal/invalid. `LowSignalError` is defined and implemented in
> Phase 2 (estimation); its name and semantics are locked here now.

**5. Cosine proxy** — treats each calibrated reading as proportional to the
cosine of the angle to the sun.

```
cos(θ_i) = R_i / V_max_i
```
Example: `R_i=735, V_max_i=1000 → cos(θ_i)=0.735 → θ_i≈42.7°`.

### Solar radiation pressure (SRP)

**6. SRP force per face** — converts irradiance into force on one illuminated
face.

```
F_i = (I_i · A / c) · (1 + ρ)
```
Example: `I_i=1361 W/m², A=0.01 m², c=3e8, ρ=0.30 → F_i≈5.9e-8 N (59 nN)`.

**7. Net SRP force vector** — sum of SRP forces from all six faces.

```
F_net = Σ(F_i · n̂_i)
```
Example: if `+x, +y, +z` lit → `F_net ≈ (59, 59, 40) nN`.

**8. SRP force magnitude**

```
|F_net| = sqrt(Fx² + Fy² + Fz²)
```
Example: `F_net=(59,59,40) nN → |F_net|≈93 nN`.

**9. SRP azimuth** — horizontal direction of net SRP force in body frame.

```
θ_SRP = arctan2(F_y, F_x)
```
Example: `Fx=59, Fy=59 → θ_SRP=45°`.

**10. SRP elevation** — vertical angle of net SRP force relative to horizontal.

```
φ_SRP = arcsin(F_z / |F_net|)
```
Example: `Fz=40, |F_net|=93 → φ_SRP≈25.5°`.

### Validation

**11. Angular error vs reference** — compares estimated sun direction to a known
reference direction.

```
θ_error = arccos(clamp(ŝ · ŝ_ref, −1, 1))
```
Example: `dot=0.98 → θ_error≈11.5°`.

**12. Repeatability** — std deviation of angular error over a rolling window.

```
σ = std(θ_error)
```
Example: recent errors `[10°,11°,12°,11°,10°] → σ≈0.7°`.

**13. Bias** — rolling mean angular error (systematic over/under-estimation).

```
bias = mean(θ_error)
```
Example: recent errors average `11° → bias=11°`.

### Thermal

**14. Temperature drift rate** — rate of change of sensor temperature.

```
dT/dt_i = (T_i(t) − T_i(t − Δt)) / Δt
```
Example: `24.0°C → 24.5°C in 1 min → dT/dt = 0.5°C/min`.

### Color (OPT4048)

**15. CIE chromaticity coordinates** — converts tristimulus `(X,Y,Z)` into
normalized color coordinates.

```
x_cie = X / (X + Y + Z)
y_cie = Y / (X + Y + Z)
```
Example: `X=30, Y=40, Z=30 → x_cie=0.30, y_cie=0.40`.

**16. McCamy intermediate value** — intermediate quantity for estimating
correlated color temperature (CCT).

```
n = (x_cie − 0.3320) / (y_cie − 0.1858)
```
Example: `x_cie=0.30, y_cie=0.40 → n = −0.0320/0.2142 ≈ −0.149`.

---

## 4. Simulator ↔ estimation contract (Phase 1 → Phase 2)

The Phase 1 simulator (`tetralux/sim/`) is the **forward model**:

- Its per-face `reading` corresponds to the raw pre-calibration value **`V_i`**
  in formula 1; the `dark_current` argument corresponds to **`D_i`**.
- `generate_sweep()` returns `(light_dir, face_readings)` pairs where
  **`light_dir` is the ground-truth `ŝ_ref`**.

Phase 2 will feed `face_readings` through the LOCKED formulas 1–4 to recover `ŝ`,
then validate against `light_dir` using formula 11. No estimation code exists in
Phase 1 — only the data shape is guaranteed to support this.

---

## 5. Fault detection (Phase 3)

`tetralux/faults/` classifies frame health *before* the estimate is trusted,
mapping the four failure modes to concrete checks:

| Failure mode | Where it's handled | How |
|---|---|---|
| Divide-by-zero (total light ≈ 0) | `estimator` raises `LowSignalError`; `detector` reports `LOW_SIGNAL` | `Σ R < MIN_EPSILON` |
| Saturation clipping | `detector` → `SATURATION` | simulator's per-face `saturated` flag; `dominant_saturated` marks an unreliable direction |
| Multi-source / ambiguous average | `detector` → `MULTI_SOURCE` | `opposition_ratio` = `2·Σ_pairs min(R⁺,R⁻) / Σ R` ∈ [0,1]; a single point source lights at most one face per opposite pair, so the ratio is ~0 |
| Corrupted / truncated packets | `faults/packets.py` primitives (Phase 4 builds the concrete framing) | fixed-length check + 8-bit additive checksum |

`assess_frame(...) → FrameHealth` returns a frozen report (`ok`, `faults`,
`dominant_face`, `saturated_faces`, `opposition_ratio`). `safe_estimate(...)`
pairs it with the estimator and returns `(vector_or_None, health)` — low-signal
frames yield `None`; saturation/multi-source are surfaced in `health` but do not
suppress the vector, leaving the trust decision to the caller.

**Scope note:** packet integrity is provided as *format-agnostic primitives*
(`checksum8`, `verify_checksum`, `validate_packet`) because the fixed-length
binary packet layout is a Phase 4 (telemetry) artifact. Phase 4 assembles the
real packet on top of these.

---

## 6. Telemetry packet (Phase 4)

`tetralux/telemetry/` implements the CubeSat downlink as a **17-byte
fixed-length, big-endian binary packet**, built on the Phase 3 integrity
primitives:

| offset | size | field |
|---|---|---|
| 0 | 1 | SYNC byte `0xAA` (frame start / resync marker) |
| 1 | 2 | `seq` — uint16 sequence counter (wraps at 65535) |
| 3 | 12 | 6 × uint16 face readings, in `FACE_NAMES` order (ADC counts) |
| 15 | 1 | saturation bitfield — bit *i* set == `FACE_NAMES[i]` saturated |
| 16 | 1 | 8-bit additive checksum over bytes 0–15 |

- **Quantization:** readings are clamped to `[0, 65535]` and rounded to 16-bit
  ADC counts — the realistic lossy step of a real ADC front end. Saturation
  flags survive losslessly in the bitfield.
- **Codec** (`packet.py`): `encode_packet(seq, face_readings)` /
  `decode_packet(raw)`; `decode_packet` raises `PacketError` (carrying a
  `PacketFault`) on wrong length, bad sync, or checksum mismatch.
- **Resync parser:** `iter_packets(stream)` scans for SYNC and decodes full
  packets, advancing one byte past a bad checksum or false sync — so corrupted
  or truncated packets are skipped, not fatal (the corrupted/truncated failure
  mode, end to end).
- **Generator** (`generator.py`): `generate_telemetry(light_dirs, rate_hz=10)`
  simulates + encodes one packet per direction, stamping frame *i* at
  `i / rate_hz` (nominal ~10–20 Hz; no real-time sleeping so replay can run at
  any speed).

---

## 7. Dashboard (Phase 5)

`tetralux/dashboard/` is a Plotly Dash app over the whole pipeline. It is split
so the data logic stays dependency-light:

- **`replay.py` (pure, numpy-only):** `build_replay(stream, references, ...)`
  runs each decoded packet through `safe_estimate` and scores it, yielding a
  list of frozen `ReplayFrame` records (seq, time, readings, sun vector,
  `FrameHealth`, angular error). Importable without Dash/Plotly, and unit tested.
- **`figures.py` (needs plotly):** pure `go.Figure` builders — 3D estimated-vs-
  true sun vector, per-face ADC bars (saturated faces in red), angular-error
  timeline.
- **`app.py` (needs dash):** `create_app(frames)` wires a scrub/play slider to
  the figures plus an HTML fault-health panel; `main()` serves a demo stream on
  port 8050 (`python -m tetralux.dashboard`).

Dash and Plotly are an **optional extra** (`pip install -e ".[dashboard]"`); the
core package stays numpy-only. Dashboard tests `importorskip` the extra so the
suite passes without it.

---

## 8. Ground station (Phases 6–9)

Turns the twin into a real ground station: one frame contract, two data sources,
one pipeline.

### 8.1 Real wire format & ingestion (Phase 6)

The firmware transmits one **newline-delimited ASCII JSON** object per sample:
`{"seq","ts","pd"[6],"lux"[6],"mag"{x,y,z},"opt"[4]{X,Y,Z,lux},"temp"[6],"flags","chk"}`.
The checksum is an **8-bit XOR of the raw body bytes before `,"chk"`** —
`telemetry/json_frame.py` reproduces this byte-for-byte (encode + decode), so the
virtual twin and the real device share one codec. `ingest/` provides a FastAPI
`POST /ingest` (enqueue-only) and a `SerialReader`, both feeding one queue;
`StreamMonitor` tracks received/dropped(seq-gap)/corrupt(checksum)/rate/connection.
`SensorFrame` (`frames.py`) is the common currency.

### 8.2 Pipeline & record (Phase 6)

`pipeline.process(frame, ctx) -> GroundStationRecord` chains: calibrate
(`calibration.py`, formulas 1 & 5) → estimate + az/el → validation (rolling or
burst) → faults → thermal (`thermal/`, drift + rolling) → OPT trust
(`spectral/opt.py`, McCamy CCT vs 5500 K ± 500 K). The record carries **every**
displayed quantity and serializes NaN→null / numpy→python via `to_dict()`.

### 8.3 Virtual sensors (Phase 7)

`sim/sensors.py` synthesizes a full `SensorFrame` (photodiodes via `simulate_faces`
emitting `V = S/G + D` so calibration inverts exactly; plus lux, temperature,
OPT4048 tristimulus, magnetometer). `frame_from_angles(az, el)` feeds the Virtual
mode's instantaneous recompute.

### 8.4 Logging store (Phase 8)

`store/` writes every record to a **local JSONL mirror** (always, full fidelity)
and, when configured, to **Firebase Realtime Database — one node per packet**
(`sessions/{sid}/packets/{ts_seq}`). `SessionController` gates all logging behind
a manual **start/stop** (off by default) and tracks packet count / duration /
accumulated bytes; `query.py` lists sessions and exports CSV. Credentials come
from `GOOGLE_APPLICATION_CREDENTIALS` + `FIREBASE_DATABASE_URL` — never committed.

**Rate/cost (100 Hz target):** RTDB is billed on storage/bandwidth, not per write,
so it sustains per-packet logging (~18 MB / 10-min session). Firestore per-packet
would be Blaze-only (~$15/day at 24×7); the local JSONL guarantees full fidelity
regardless. No auto-pruning/throttling — visibility only, delete sessions manually.

### 8.5 Dashboard v2 (Phase 9)

`dashboard/app.py` is a multi-page app (Live, 3D Vector, Time-series,
History/Logs, About) with a Virtual/Real toggle. Virtual recomputes
instantly from the az/el sliders; Real streams from `AppState` (ingest queue →
processing thread → rolling buffer), with a built-in simulated-device feed for
demos. All values render through `units.py` (no bare numbers).

The real path also runs headless: `python -m tetralux.groundstation --port 8000
[--record] [--serial PORT]`.

---

## 9. Hardware bring-up (Phase 10)

`firmware/` is a fresh Arduino Nano 33 IoT (PlatformIO) implementation of the
wire contract in §8.1 — same field order, same byte-exact XOR checksum
(`firmware/src/telemetry/packet.cpp` mirrors `xor_checksum()`), WiFi HTTP POST
primary with Serial fallback. It intentionally does **not** repeat two v0 bugs:
the `#ifdef CONFIG_H` guard (fixed to `#ifndef`) and the checksum-verifier
re-serialization mismatch (the ground station already XORs raw received bytes,
per §8.1). The OPT4048 driver (`firmware/src/sensors/opt4048.cpp`) is a labeled
first draft — its channel-to-XYZ matrix is a placeholder pending datasheet
verification on real hardware.

**Calibration** (`calibration.py` + `calibration_tool.py`) gained runtime
plumbing: `Calibration.save()/load()` (JSON), a guided CLI that captures
dark/gain/max from a live telemetry stream (`calibration_tool.py`'s
`run_guided_calibration()` is pure — testable against the simulated device feed
with no hardware), and `--calibration <path>` on `groundstation.py` /
a "Load calibration file" control on the dashboard's Live page.

One correctness note from live-testing the guided CLI: a real device streams
continuously between prompts, so frames posted *before* the operator finished
repositioning the light (still reflecting the previous step) would sit at the
front of the ingest queue and get consumed as the new step's data. `collect()`
now flushes the queue (`_flush_queue()`) the moment the operator confirms
readiness, before sampling — confirmed live by driving the CLI against a
continuously-streaming simulated feed with deliberately stale frames queued.

See `docs/bringup.md` for the full step-by-step procedure and a troubleshooting
table mapping `RejectedFrame` reasons to likely hardware causes.
