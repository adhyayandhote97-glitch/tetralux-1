"""Virtual sensor synthesis (Phase 7).

WHAT THIS FILE CONTRIBUTES
--------------------------
simulator.py models the six photodiodes. This file models the ENTIRE satellite:
photodiodes, the six BH1750 lux sensors, the six DS18B20 temperature sensors,
the four OPT4048 colour sensors, and the QMC5883L magnetometer, all consistent
with one another and packaged as a complete SensorFrame.

WHY THAT MATTERS. It is what makes Virtual mode a genuine test rather than a
demo. The frame produced here is the same type real hardware produces, so it
travels through the same pipeline, the same fault detection, the same logging
and the same dashboard. If Virtual mode works, that is evidence the real path
works, because it IS the real path with a different source of numbers.

THE LAST STEP IS THE INTERESTING ONE. Rather than stamping a checksum on
directly, this file encodes the frame to JSON with the real telemetry codec and
decodes it straight back. That forces every virtual frame through the actual
wire format, so the checksum is genuinely computed rather than asserted, and a
bug in the codec shows up in Virtual mode instead of hiding until hardware
arrives.

CONSISTENCY IS THE DESIGN CONSTRAINT. The lux values track the photodiode
readings, the OPT4048 luminance tracks overall brightness, and the temperatures
ramp gently over time. Sensors that disagreed with each other would produce
frames no real satellite could generate, and testing against impossible data
proves nothing.

WHERE IT SITS IN THE FLOW
    sim/simulator.py         supplies the photodiode physics
    telemetry/json_frame.py  supplies the encode/decode round trip
    dashboard/state.py       calls frame_from_angles from the sliders

New to Python? Read docs/python-primer.md first.
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
#
# A conversion factor chosen so the numbers land in a realistic range: a fully
# lit face at roughly 900 counts becomes about 108,000 lux, which is genuinely
# what direct sunlight measures. Realistic magnitudes matter because a display
# bug that shows lux where counts belong is obvious at 108000 and invisible if
# both were in the hundreds.
LUX_PER_COUNT = 120.0
# Magnetometer field magnitude (raw units). The magnetometer plays no part in
# the sun estimate; it is carried for completeness of the frame.
MAG_MAGNITUDE = 300.0
# Default source chromaticity: CIE daylight ~5500 K (OPT trust gate PASSes).
#
# These two coordinates are the input to formula 15's inverse. Chosen so the
# McCamy cubic returns about 5500 K and the trust gate returns PASS, meaning
# Virtual mode simulates sunlight by default. Change them to imitate a tungsten
# lamp and watch the gate go to FAIL.
DAYLIGHT_CHROMATICITY = (0.3324, 0.3474)


# PARAMETERS
#   light_dir           - REQUIRED. Where the light comes from, as a 3D vector.
#   seq                 - packet sequence number for this frame.
#   timestamp_ms        - simulated device clock. Also drives the thermal ramp.
#   intensity           - brightness in ADC-count scale. 900 sits below the 1023
#                         ceiling, so a fully lit face is bright but not
#                         saturated, which is the normal healthy case.
#   noise_std           - random noise level. 0.0 gives perfectly clean data.
#   rng                 - a seeded generator for reproducible tests, or None.
#   source_chromaticity - the light's colour, defaulting to daylight.
#   base_temp_c         - starting temperature for the DS18B20 sensors.
#   heading_deg         - satellite heading, used only for the magnetometer.
#   received_at         - ground-station arrival time, or None for now.
#   gain, dark          - per-face calibration. Defaults match calibration.py's
#                         defaults exactly, which is what makes the round trip
#                         invert cleanly. See the note at the photodiode step.
# RETURNS
#   a complete, wire-valid SensorFrame.
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
    """Synthesize a full sensor frame for a given light direction."""
    if rng is None and noise_std > 0.0:
        rng = np.random.default_rng()
    # `a or b` returns a if a is truthy, otherwise b. A compact way to say
    # "use what was passed, or fall back to now".
    received_at = received_at or datetime.now(timezone.utc)
    # These use an explicit `is None` test rather than `or`, and the difference
    # matters: an empty dict is falsy, so `gain or DEFAULT_GAIN` would silently
    # replace a deliberately empty dict with the defaults. `is None` only
    # substitutes when nothing was passed at all.
    gain = DEFAULT_GAIN if gain is None else gain
    dark = DEFAULT_DARK if dark is None else dark

    # --- photodiodes: physical Lambertian model -> 10-bit ADC ---
    # Emit raw V = S/G + D so the default calibration inverts it exactly.
    #
    # This is the key to the whole round trip. The simulator applies gain and
    # dark BACKWARDS to produce a raw reading; the pipeline's calibration then
    # applies them forwards and recovers the original signal. Any residual error
    # in the final estimate therefore comes from quantization and geometry, not
    # from a mismatch between the two, which is what makes the sub-1.5-degree
    # accuracy assertion in the tests meaningful.
    faces = simulate_faces(light_dir, intensity=intensity, noise_std=noise_std,
                           rng=rng, gain=gain, dark_current=dark)
    readings = {f: faces[f]["reading"] for f in FACE_NAMES}
    # QUANTIZATION: a real 10-bit ADC reports whole numbers only, so round()
    # discards the fractional part. That lost precision is a genuine error
    # source, and modelling it is why the estimate is not perfect even with zero
    # noise. min/max clamp into the ADC's physical 0 to 1023 range.
    photodiodes = [int(min(ADC_MAX, max(0, round(readings[f])))) for f in FACE_NAMES]

    # --- BH1750 lux: proportional to the (noise-free-ish) reading ---
    # Derived from the same readings as the photodiodes, so the two sensor
    # families agree with each other as they would physically. Rounded to one
    # decimal, matching the BH1750's actual reporting resolution.
    lux = [round(readings[f] * LUX_PER_COUNT, 1) for f in FACE_NAMES]

    # --- DS18B20 temperatures: baseline + per-face offset + slow ramp + noise ---
    #
    # 0.1 degC per minute is DELIBERATELY below DRIFT_THRESHOLD_C_PER_MIN (0.5).
    # A gentle warm-up is realistic for powered electronics, and keeping it
    # under the threshold means Virtual mode does not permanently raise a drift
    # flag. Raise this above 0.5 to test that the drift detection actually
    # fires.
    ramp = 0.1 * (timestamp_ms / 60000.0)  # 0.1 degC/min (below the 0.5 drift flag)
    temperatures = []
    for i in range(6):
        # 0.3 * i gives each sensor its own small offset, so the six are
        # distinguishable rather than identical. Real sensors never agree
        # exactly, and identical values would hide a bug that mixed them up.
        t = base_temp_c + 0.3 * i + ramp
        if rng is not None and noise_std > 0.0:
            # Much smaller noise than the photodiodes get: the DS18B20 is a
            # precise digital sensor, so 0.03 degC of jitter is realistic.
            t += float(rng.normal(0.0, 0.03))
        temperatures.append(round(t, 2))

    # --- OPT4048: 4 sensors at the source chromaticity, luminance ~ brightness ---
    #
    # This runs formula 15 IN REVERSE. cie_chromaticity turns X, Y, Z into x, y;
    # here x, y and a luminance are turned back into X, Y, Z, so that when the
    # pipeline decodes them it recovers the colour temperature that was
    # intended. Y is luminance directly, and the standard relations give
    # X = x*Y/y and Z = (1-x-y)*Y/y.
    x_c, y_c = source_chromaticity
    brightness = float(np.mean(photodiodes))
    # Tie colour-sensor luminance to overall brightness, so a dim scene produces
    # dim colour readings. max(1.0, ...) keeps it above zero, since X+Y+Z of
    # zero would make cie_chromaticity raise.
    y_lum = max(1.0, 0.05 * brightness + 1.0)
    opt = []
    # Four independent sensors, so four passes. The underscore means the counter
    # is unused (primer 10).
    for _ in range(4):
        xs, ys = x_c, y_c
        if rng is not None and noise_std > 0.0:
            # Tiny chromaticity noise, 0.001, because colour coordinates live in
            # a 0 to 1 range where 0.001 is already a visible shift. This is
            # what makes the four sensors disagree slightly, which is exactly
            # the situation the averaging in analyze_opt exists to handle.
            xs += float(rng.normal(0.0, 0.001))
            ys += float(rng.normal(0.0, 0.001))
        big_x = xs * y_lum / ys
        big_z = (1.0 - xs - ys) * y_lum / ys
        opt.append({
            "X": round(big_x, 3), "Y": round(y_lum, 3),
            "Z": round(big_z, 3), "lux": round(y_lum * 100.0, 1),
        })

    # --- QMC5883L magnetometer from heading ---
    #
    # Not used by the sun estimate at all. It is included because the real
    # firmware sends it, and a virtual frame missing a field the wire format
    # expects would not round-trip through the codec.
    h = np.radians(heading_deg)
    mag = {"x": int(round(MAG_MAGNITUDE * np.cos(h))),
           "y": int(round(MAG_MAGNITUDE * np.sin(h))),
           # A small fixed vertical component, standing in for the Earth field's
           # dip angle.
           "z": int(round(10.0))}
    if rng is not None and noise_std > 0.0:
        # A dict comprehension rebuilding all three axes with noise added.
        mag = {k: int(v + round(float(rng.normal(0.0, 2.0)))) for k, v in mag.items()}

    # 0x01 is hexadecimal for 1, which in binary is 00000001: only the lowest
    # bit set. Written in hex because this is a BITFIELD (see frames.py), where
    # hex makes the individual bit positions readable in a way decimal does not.
    flags = 0x01  # bit0 = "WiFi connected"

    draft = SensorFrame(
        seq=seq, timestamp_ms=timestamp_ms, photodiodes=photodiodes, lux=lux,
        magnetometer=mag, opt=opt, temperatures=temperatures, flags=flags,
        checksum=0, received_at=received_at, source="virtual",
    )
    # checksum=0 above is a placeholder. The real value cannot be known yet,
    # because a checksum is computed over the encoded text of everything else.
    #
    # Round-trip through the real codec so the checksum is correct and the frame
    # is provably wire-valid.
    #
    # Reading inside out: encode_json_frame turns the draft into the exact text
    # the firmware would transmit, computing a genuine checksum;
    # decode_json_frame parses that text back, verifying that checksum as it
    # goes.
    #
    # This is not a formality. It means every Virtual-mode frame has been proven
    # to survive the real wire format, so a codec bug surfaces here rather than
    # on the day hardware is first connected.
    return decode_json_frame(encode_json_frame(draft), source="virtual",
                             received_at=received_at)


# --- The slider-friendly wrapper ---
#
# PARAMETERS
#   azimuth_deg, elevation_deg - the sun direction as two angles, which is what
#                                the dashboard sliders produce.
#   **kwargs                   - collects any other keyword arguments into a
#                                dict and forwards them, unpacked, to
#                                simulate_sensor_frame. So a caller can pass
#                                intensity or noise_std here and they arrive
#                                intact, without this function having to list
#                                all eleven parameters and keep them in sync.
# RETURNS
#   a complete SensorFrame.
#
# A two-line convenience function, but it removes a conversion step from every
# call site in the dashboard and the tests, which is where most of the calls
# are.
def frame_from_angles(
    azimuth_deg: float,
    elevation_deg: float,
    **kwargs,
) -> SensorFrame:
    """Convenience wrapper: build a frame from azimuth/elevation sliders."""
    return simulate_sensor_frame(angles_to_vector(azimuth_deg, elevation_deg), **kwargs)
