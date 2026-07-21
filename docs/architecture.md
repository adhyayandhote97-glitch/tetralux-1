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
Example: `x_cie=0.30, y_cie=0.40 → n≈−0.179`.

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
