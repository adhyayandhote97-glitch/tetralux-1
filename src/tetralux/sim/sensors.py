"""Virtual sensor synthesis (Phase 7).

Extends the Phase 1 photodiode simulator into a *full* `SensorFrame` — lux,
temperature, OPT4048 colour, and magnetometer — so Virtual mode can populate
every dashboard panel without hardware. Photodiodes remain the physical model
(`simulate_faces`); the other sensors use simple, plausible models.

The result is round-tripped through the real JSON codec so a virtual frame is
byte-identical to what the firmware would send (correct checksum included).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from tetralux.calibration import DEFAULT_DARK, DEFAULT_GAIN
from tetralux.constants import ADC_MAX, FACE_NAMES
from tetralux.estimation.estimator import angles_to_vector
from tetralux.frames import SensorFrame
from tetralux.sim.simulator import simulate_faces
from tetralux.telemetry.json_frame import decode_json_frame, encode_json_frame

# BH1750 lux per ADC count (so a bright face ~ full daylight ~1e5 lx).
LUX_PER_COUNT = 120.0
# Magnetometer field magnitude (raw units).
MAG_MAGNITUDE = 300.0
# Default source chromaticity: CIE daylight ~5500 K (OPT trust gate PASSes).
DAYLIGHT_CHROMATICITY = (0.3324, 0.3474)


def simulate_sensor_frame(
    light_dir: np.ndarray,
    seq: int = 0,
    timestamp_ms: int = 0,
    intensity: float = 900.0,
    noise_std: float = 0.0,
    rng: Optional[np.random.Generator] = None,
    source_chromaticity: tuple = DAYLIGHT_CHROMATICITY,
    base_temp_c: float = 25.0,
    heading_deg: float = 0.0,
    received_at: Optional[datetime] = None,
    gain: Optional[dict] = None,
    dark: Optional[dict] = None,
) -> SensorFrame:
    """Synthesize a full sensor frame for a given light direction.

    Args:
        light_dir: Direction from the cube toward the light (need not be unit).
        seq: Sequence counter.
        timestamp_ms: Device timestamp (ms); also drives a tiny thermal ramp.
        intensity: Peak photodiode signal (maps ~1:1 to ADC counts).
        noise_std: Per-face Gaussian noise (ADC counts) applied to photodiodes.
        rng: Optional seeded generator for reproducible noise.
        source_chromaticity: (x, y) CIE coords of the light source (sets OPT CCT).
        base_temp_c: Baseline temperature for the DS18B20 sensors.
        heading_deg: Magnetometer heading.
        received_at: Ground-station receive time (defaults to now).

    Returns:
        A wire-valid :class:`SensorFrame` (``source="virtual"``).
    """
    if rng is None and noise_std > 0.0:
        rng = np.random.default_rng()
    received_at = received_at or datetime.now(timezone.utc)
    gain = DEFAULT_GAIN if gain is None else gain
    dark = DEFAULT_DARK if dark is None else dark

    # --- photodiodes: physical Lambertian model -> 10-bit ADC ---
    # Emit raw V = S/G + D so the default calibration inverts it exactly.
    faces = simulate_faces(light_dir, intensity=intensity, noise_std=noise_std,
                           rng=rng, gain=gain, dark_current=dark)
    readings = {f: faces[f]["reading"] for f in FACE_NAMES}
    photodiodes = [int(min(ADC_MAX, max(0, round(readings[f])))) for f in FACE_NAMES]

    # --- BH1750 lux: proportional to the (noise-free-ish) reading ---
    lux = [round(readings[f] * LUX_PER_COUNT, 1) for f in FACE_NAMES]

    # --- DS18B20 temperatures: baseline + per-face offset + slow ramp + noise ---
    ramp = 0.1 * (timestamp_ms / 60000.0)  # 0.1 degC/min (below the 0.5 drift flag)
    temperatures = []
    for i in range(6):
        t = base_temp_c + 0.3 * i + ramp
        if rng is not None and noise_std > 0.0:
            t += float(rng.normal(0.0, 0.03))
        temperatures.append(round(t, 2))

    # --- OPT4048: 4 sensors at the source chromaticity, luminance ~ brightness ---
    x_c, y_c = source_chromaticity
    brightness = float(np.mean(photodiodes))
    y_lum = max(1.0, 0.05 * brightness + 1.0)
    opt = []
    for _ in range(4):
        xs, ys = x_c, y_c
        if rng is not None and noise_std > 0.0:
            xs += float(rng.normal(0.0, 0.001))
            ys += float(rng.normal(0.0, 0.001))
        big_x = xs * y_lum / ys
        big_z = (1.0 - xs - ys) * y_lum / ys
        opt.append({
            "X": round(big_x, 3), "Y": round(y_lum, 3),
            "Z": round(big_z, 3), "lux": round(y_lum * 100.0, 1),
        })

    # --- QMC5883L magnetometer from heading ---
    h = np.radians(heading_deg)
    mag = {"x": int(round(MAG_MAGNITUDE * np.cos(h))),
           "y": int(round(MAG_MAGNITUDE * np.sin(h))),
           "z": int(round(10.0))}
    if rng is not None and noise_std > 0.0:
        mag = {k: int(v + round(float(rng.normal(0.0, 2.0)))) for k, v in mag.items()}

    flags = 0x01  # bit0 = "WiFi connected"

    draft = SensorFrame(
        seq=seq, timestamp_ms=timestamp_ms, photodiodes=photodiodes, lux=lux,
        magnetometer=mag, opt=opt, temperatures=temperatures, flags=flags,
        checksum=0, received_at=received_at, source="virtual",
    )
    # Round-trip through the real codec so the checksum is correct and the frame
    # is provably wire-valid.
    return decode_json_frame(encode_json_frame(draft), source="virtual",
                             received_at=received_at)


def frame_from_angles(
    azimuth_deg: float,
    elevation_deg: float,
    **kwargs,
) -> SensorFrame:
    """Convenience wrapper: build a frame from azimuth/elevation sliders."""
    return simulate_sensor_frame(angles_to_vector(azimuth_deg, elevation_deg), **kwargs)
