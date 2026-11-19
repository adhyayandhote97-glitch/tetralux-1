# Tetralux-1 Dataset

Real telemetry recorded from the Tetralux-1 1U CubeSat prototype (Arduino Nano 33 IoT,
6 × S1223 photodiodes, 6 × BH1750, QMC5883L magnetometer, 4 × OPT4048, 6 × DS18B20,
TCA9548A I²C multiplexer). All data is from the physical hardware (`source: real`) unless stated.

- **Code:** MIT licence (see `LICENSE`)
- **Data in this file's scope:** CC BY 4.0: free to reuse with credit to *Adhyayan Dhote, Tetralux-1 (2026)*

## Contents

| Location | What | Size |
|---|---|---|
| `overnight_test/test_logs/endurance_20261118_005845*` | **2-hour endurance run** (18 Nov 2026), plus summary and plots | 18,977 frames |
| `overnight_test/test_logs/endurance_20261118_001508.csv`, `_001749.csv` | Short warm-up runs before the endurance test | ~6,900 lines |
| `data/logs/S20260815_100243/` | Ground-station session, 15 Aug 2026 (~3 min, light moved by hand) | 4,900 records |
| `data/logs/S20260723_110252/records_sample.jsonl` | Sample from first live session, 23 Jul 2026 | 2,000 records |
| `data/logs/S20260730_*`, `S20260809_*`, `S20260812_*` | Shorter bring-up sessions | 1–759 records each |
| `hardware/` | BOM, Blender CAD model, circuit and architecture diagrams | — |
| `docs/papers/` | System architecture paper (June 2026) | — |

---

## 1. Endurance run: `endurance_20261118_005845.csv`

Captured over USB serial (115200 baud) by `overnight_test/endurance_log.py`.
**One row per line received from the board**, including non-telemetry status text.
Use `parse_ok == 1` to keep only valid telemetry frames.

| Column | Unit / type | Meaning |
|---|---|---|
| `host_iso` | ISO 8601, +05:30 | Laptop time the line arrived |
| `host_mono` | s | Laptop monotonic clock (use for intervals) |
| `parse_ok` | 0/1 | 1 = valid JSON frame with correct checksum |
| `reject_reason` | text | Why a line was rejected (e.g. `not a JSON frame`) |
| `seq` | int | Frame sequence number from the board (gaps = lost frames) |
| `ts_ms` | ms | Arduino `millis()` at send time |
| `pd_px … pd_nz` | ADC counts (0–4095) | S1223 photodiode, faces +x, −x, +y, −y, +z, −z |
| `lux_px … lux_nz` | lux | BH1750 ambient light per face |
| `mag_x, mag_y, mag_z` | raw counts | QMC5883L magnetometer |
| `opt0_X … opt3_lux` | CIE XYZ, lux | OPT4048 spectral sensors 0–3 |
| `temp_px … temp_nz` | °C | DS18B20 temperature per face |
| `flags` | bitfield | Firmware status flags (1 = sent over Wi-Fi) |
| `chk` | int | 8-bit XOR checksum sent by the board |
| `est_x, est_y, est_z` | unit vector | Estimated sun direction (body frame) |
| `est_az_deg, est_el_deg` | degrees | Estimated azimuth / elevation |
| `saturated_faces` | list | Faces flagged as saturated |
| `raw` | text | Original line when it was not a valid frame |

Companion files (same prefix):
- `_summary.md`: results: **100 % packet reliability (18,977/18,977), no gaps, no restarts**, update interval, temperature stats
- `_buckets.csv`: per-5-minute loss %, mean temperature, mean photodiode sum
- `_gaps.csv`: sequence gaps (empty = none)
- `_events.csv`: logger events (start, port open)
- `_markers.csv`, `_poses.csv`: pose markers for accuracy tests (**empty in this run**)
- `_intervals.png`, `_loss.png`, `_temperature.png`: plots

## 2. Ground-station sessions: `data/logs/<session>/records.jsonl`

Newline-delimited JSON, one processed frame per line, written by the dashboard ground station
(`python -m tetralux.groundstation`). `session.json` holds the session id and start time.

| Field | Unit / type | Meaning |
|---|---|---|
| `seq`, `timestamp_ms` | int, ms | Board sequence number and `millis()` |
| `received_at` | ISO 8601 UTC | Laptop receive time |
| `source` | `real` / `virtual` | Hardware or simulator (all files here are `real`) |
| `photodiodes` | ADC counts per face | Raw S1223 readings |
| `lux` | lux per face | BH1750 readings |
| `magnetometer` | raw counts x/y/z | QMC5883L |
| `corrected` | counts per face | Photodiode minus dark offset |
| `cosine_proxy` | 0–1 per face | Corrected reading ÷ face maximum |
| `irradiance` | W/m² per face | Estimated irradiance |
| `weights` | 0–1 per face | Each face's share of total signal |
| `sun_vector` | unit vector [x, y, z] | Estimated sun direction |
| `azimuth_deg`, `elevation_deg` | degrees | Sun direction in angles |
| `confidence` | 0–1 | Estimate confidence |
| `srp_forces`, `srp_net` | N | Solar radiation pressure per face / net vector |
| `srp_magnitude_n`, `srp_azimuth_deg`, `srp_elevation_deg` | N, degrees | Net SRP |
| `angular_error_deg`, `bias_deg`, `repeatability_deg` | degrees | Validation metrics (**see note below**) |
| `saturated_faces`, `saturation_flag` | list, bool | Saturation detection |
| `checksum`, `checksum_ok` | int, bool | Packet integrity |
| `faults`, `health_ok` | list, bool | Fault detector output |
| `opposition_ratio` | ratio | Opposite-face signal ratio (multi-source check) |
| `thermal` | object | DS18B20 temperatures, drift rates, rolling means, flags |
| `opt` | object | OPT4048 colour temperature (CCT), trust gate, light-source guess |
| `stream` | object | Running counts: received, accepted, rejected, gaps, rate (Hz) |
| `processing_time_ms` | ms | Ground-station processing time per frame |

Formulas behind every derived field are in [`docs/architecture.md`](docs/architecture.md).

---

## Known limitations

- **No ground-truth accuracy data yet.** In the ground-station logs, `angular_error_deg` is scored
  against a default reference of +x `[1, 0, 0]`, not against a measured light position, so it
  is **not** a real accuracy figure. The endurance run has no pose markers.
- **Update interval:** median **379 ms** (~2.6 Hz) in the endurance run, well below the 10 ms design target.
- **BH1750:** the board printed `[BH1750] Device is not configured!` 56,931 times during the
  endurance run; lux values are non-zero in only 5,528 of 18,977 frames.
- **OPT4048:** all zero in the endurance run (not yet integrated in firmware).
- **−x photodiode:** was unresponsive during early bring-up (likely reversed polarity).
- **Calibration** (`calibration.json`, dark offsets and gains) is specific to this unit and not included.
- Lighting was a hand-held torch / room light indoors, not sunlight.

## Planned additions

- **8-hour overnight endurance run**
- Pose-marked accuracy and repeatability tests against known light positions

## Cite

> Dhote, A. (2026). *Tetralux-1: telemetry dataset from a 1U CubeSat sun-direction sensing prototype.* GitHub: adhyayandhote97-glitch/tetralux-1
