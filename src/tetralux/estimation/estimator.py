"""Phase 2 - sun-vector estimation engine.

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the mathematical heart of the project. Everything else exists to feed
this file numbers or to display what it produces. Six brightness readings go in,
one direction pointing at the sun comes out.

THE IDEA, IN PLAIN WORDS. Stand in a room with one lamp and hold up a cube. The
face pointing at the lamp is brightest; the face pointing away is dark; the ones
in between are partly lit. Now work backwards: given how bright each face is,
where is the lamp? Take each face's outward direction, scale it by how brightly
that face is lit, and add all six together. The bright faces dominate the sum,
so the total leans toward the lamp. Shrink that sum to length 1 and you have a
pure direction: the sun vector.

That is four formulas, applied in order:

    Formula 1  corrected_reading  clean up each raw reading
    Formula 2  face_weight        turn readings into shares that add to 1
    Formula 3  direction_vector   add up the weighted face directions
    Formula 4  sun_vector         shrink to length 1  <- the answer

Formula 5 (cosine_proxy) is a separate, related quantity: how directly light
strikes one face, which the physics and calibration code needs.

These formulas are LOCKED. docs/architecture.md specifies them exactly, the
project report derives them, and the code must match that derivation rather than
some cleverer equivalent. Do not "improve" them.

WHY THE 1/total IN FORMULA 2 DOES NOT CHANGE THE ANSWER. Dividing every reading
by the same total scales the whole sum by one constant, and formula 4 then
divides by the sum's length, cancelling that constant exactly. So raw readings
and normalized weights give an identical direction. The weights are computed
anyway because they are meaningful to display: each face's share of the light,
summing to 1.

WHERE IT SITS IN THE FLOW
    pipeline.py     calls these on every incoming frame
    calibration.py  wraps formulas 1 and 5 with per-face calibration data
    sim/            produces readings in exactly the shape these expect

New to Python? Read docs/python-primer.md first; it explains def, parameters,
return, raise and so on once, so these comments can stay about the maths.
"""

from __future__ import annotations

# Mapping and Sequence are type hints describing SHAPE rather than exact type.
# Sequence means "something you can walk through in order", so a list or a tuple
# both qualify. Mapping means "something you look values up in by key", so a
# dict qualifies. Using the general form documents what the function actually
# needs instead of over-promising that only a list will do.
from collections.abc import Mapping, Sequence

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


# A custom error type (primer section 11). `(Exception)` means it inherits from
# Python's built-in Exception, so it behaves like any other error.
#
# The body is only a docstring because nothing more is needed: the value of this
# class is its NAME. Callers can write `except LowSignalError:` and catch
# exactly this situation, while a genuine bug such as a typo still crashes
# loudly instead of being silently swallowed by a catch-all.
#
# WHEN IT FIRES: in darkness, when the readings are too weak to point anywhere.
# That is a legitimate operating condition, not a malfunction, so pipeline.py
# catches it and records sun_vector as None rather than stopping the ground
# station.
class LowSignalError(Exception):
    """Raised when total signal (or direction magnitude) is below MIN_EPSILON."""


# --- Formula 1: clean up one face's raw reading ---
#
# PARAMETERS
#   V_i - the raw ADC count from photodiode i, 0 to 1023, straight off the
#         hardware. "V" for voltage, "_i" is maths shorthand for "face number
#         i". Comes from SensorFrame.photodiodes.
#   D_i - the DARK OFFSET for that face: what it reads with no light at all.
#         Real photodiodes are not perfectly zero in the dark; each has its own
#         small leakage current, typically 4 to 7 counts here. Measured once
#         per prototype by calibration_tool.py.
#   G_i - the GAIN for that face: a correction factor near 1.0 for sensitivity.
#         Two photodiodes under identical light do not give identical numbers,
#         so gain scales each one onto a common footing. Also measured by
#         calibration_tool.py.
# RETURNS
#   the corrected reading R_i, in calibrated counts.
#
# WHY IT MATTERS. The whole method rests on comparing six faces fairly. If one
# photodiode reads 3% high, the estimated direction leans permanently toward it,
# and that shows up as bias_deg in the validation metrics. Subtracting dark and
# multiplying by gain removes each sensor's individual quirks so a difference
# between faces means a real difference in light.
def corrected_reading(V_i: float, D_i: float, G_i: float) -> float:
    """Formula 1 - corrected face reading: ``R_i = (V_i - D_i) * G_i``."""
    # Subtract first, then scale. Order matters: gain corrects the response to
    # actual light, and the dark offset is not light, so it must be removed
    # before scaling or it would be amplified too.
    return (V_i - D_i) * G_i


# --- Formula 2: one face's share of the total light ---
#
# PARAMETERS
#   R_i   - one face's corrected reading, from corrected_reading above.
#   all_R - corrected readings for ALL SIX faces. Needed because a "share" only
#           means anything relative to a total, so this function cannot work
#           from one face alone.
# RETURNS
#   w_i, that face's fraction of the total, dimensionless. Called
#   "dimensionless" because it is counts divided by counts: the units cancel,
#   leaving a pure ratio. All six weights add up to exactly 1.
#
# Raises LowSignalError when the total is essentially zero.
def face_weight(R_i: float, all_R: Sequence[float]) -> float:
    """Formula 2 - face weight: ``w_i = R_i / sum(all_R)``."""
    # sum() adds every number in the sequence. float() forces a decimal result.
    total = float(sum(all_R))

    # GUARD. In darkness every reading is about zero, so total is about zero,
    # and the division below would be meaningless. abs() ignores sign, so this
    # catches a total of -0.0000001 as well as +0.0000001.
    #
    # Testing against MIN_EPSILON rather than `== 0` is the important part: real
    # sensors read tiny noise values, never an exact zero, so an equality test
    # would let a near-zero total through and produce an enormous fake weight
    # that looks like a confident measurement.
    if abs(total) < MIN_EPSILON:
        # raise stops this function immediately and reports to the caller
        # (primer 11). The message is an f-string; `.2e` formats as scientific
        # notation with 2 decimals, `.0e` with none. Two adjacent strings on
        # separate lines are joined automatically by Python.
        raise LowSignalError(
            f"total signal {total:.2e} below MIN_EPSILON ({MIN_EPSILON:.0e}); "
            "low-signal/invalid frame"
        )
    return R_i / total


# --- Formula 3: add up the weighted face directions ---
#
# This is the step that converts brightness into geometry.
#
# PARAMETERS
#   weights      - the six w_i values from face_weight, in FACE_NAMES order.
#   face_normals - the six outward directions from constants.FACE_NORMALS, in
#                  the SAME order. The two lists are matched by position, so
#                  weights[2] must belong to face_normals[2]. This is exactly
#                  why FACE_NAMES fixes one canonical ordering.
# RETURNS
#   d, a 3-element vector pointing roughly at the light. Its DIRECTION is the
#   useful part; its length carries no physical meaning and is discarded by
#   formula 4.
#
# HOW IT WORKS. Each face contributes its own direction, scaled by how lit it
# is. A face pointing at the sun has a large weight and pulls the sum strongly
# toward itself; a dark face contributes almost nothing. Opposite faces
# partially cancel, which is the mechanism that makes the result accurate: if
# +x and -x are equally lit the light must be sideways to both, and their
# contributions cancel to zero along x, correctly.
def direction_vector(
    weights: Sequence[float], face_normals: Sequence[np.ndarray]
) -> np.ndarray:
    """Formula 3 - direction vector: ``d = sum(w_i * n_hat_i)``."""
    # np.zeros(3) creates array([0., 0., 0.]), the running total starting at the
    # origin. Summing into a zero start is the standard accumulator pattern.
    d = np.zeros(3)
    # zip walks both sequences together (primer 10), giving one weight and its
    # matching normal per pass. Six passes, one per face.
    for w, n in zip(weights, face_normals):
        # np.asarray(n, dtype=float) guarantees n is a numpy float array even if
        # a plain list was passed in, so the arithmetic below behaves the same
        # for either. Multiplying an array by a number scales all 3 components;
        # adding two arrays adds them component by component.
        d = d + float(w) * np.asarray(n, dtype=float)
    return d


# --- Formula 4 (LOCKED): the final answer ---
#
# PARAMETER
#   d - the direction vector from formula 3.
# RETURNS
#   s_hat, a UNIT vector: same direction as d, but length exactly 1. The "hat"
#   in the maths notation means unit length.
#
# WHY NORMALIZE. Brighter light makes every reading larger, which makes d
# longer, but the sun has not moved. Length here encodes intensity, which is not
# what is being measured. Dividing by the length throws it away and leaves pure
# direction, so the same answer comes out in bright and dim conditions alike.
# This is also where the 1/total from formula 2 cancels out.
#
# Raises LowSignalError when d has essentially no length.
def sun_vector(d: np.ndarray) -> np.ndarray:
    """Formula 4 (LOCKED) - sun vector: ``s_hat = d / |d|``."""
    d = np.asarray(d, dtype=float)
    # np.linalg.norm computes the vector's length by Pythagoras in 3D:
    # sqrt(x^2 + y^2 + z^2). "norm" is the mathematical term for length.
    magnitude = float(np.linalg.norm(d))

    # GUARD, and a subtly different one from formula 2. The total signal can be
    # healthy while d is still near zero: if all six faces are equally lit, as
    # in diffuse light with no clear source, every direction cancels against its
    # opposite and the sum collapses. There is genuinely no direction to report,
    # so this refuses rather than returning noise amplified to length 1.
    if magnitude < MIN_EPSILON:
        raise LowSignalError(
            f"|d| {magnitude:.2e} below MIN_EPSILON ({MIN_EPSILON:.0e}); "
            "no resolvable direction"
        )
    # Dividing an array by a number divides every component, scaling the vector
    # to length 1 while keeping its direction.
    return d / magnitude


# --- Formula 5: how directly light strikes one face ---
#
# Not part of the direction estimate. This is a separate quantity that
# calibration.py and the physics code need.
#
# PARAMETERS
#   R_i     - one face's corrected reading.
#   V_max_i - what that face reads when the light hits it dead-on, its maximum.
#             Measured per face during calibration.
# RETURNS
#   cos(theta_i), where theta is the angle between the light and the face's
#   normal. 1.0 means straight on, 0.0 means edge-on. Dimensionless.
#
# THE PHYSICS. Lambert's cosine law: a surface tilted away from a light source
# collects less of it, in exact proportion to the cosine of the tilt angle. So
# dividing a reading by its dead-on maximum recovers that cosine directly, and
# from it the angle.
def cosine_proxy(R_i: float, V_max_i: float) -> float:
    """Formula 5 - cosine proxy: ``cos(theta_i) = R_i / V_max_i``."""
    # A zero maximum means the calibration is wrong or that face is dead, so
    # there is no scale to measure against. ValueError rather than
    # LowSignalError, because this is a bad configuration, not a dark sky: the
    # caller should fix the calibration, not shrug and continue.
    if abs(V_max_i) < MIN_EPSILON:
        raise ValueError("V_max_i must be non-zero to form a cosine proxy")
    return R_i / V_max_i


# --- The whole pipeline in one call ---
#
# Formulas 1 to 4 chained together. This is the convenience entry point used by
# tests and simple callers; pipeline.py runs the steps individually because it
# needs the intermediate values for display.
#
# PARAMETERS
#   face_readings - a dict of dicts: {"+x": {"reading": 812.0, ...}, ...}, the
#                   shape sim/simulator.py produces. The nesting exists because
#                   each face carries more than one field ("saturated" as well
#                   as "reading").
#   dark_offset   - EITHER one number for all faces OR a dict of six per-face
#                   values. Default 0.0 means no correction.
#   gain          - same either-or, default 1.0 meaning no scaling.
# RETURNS
#   the unit sun vector.
#
# The defaults make this usable in one line for a quick test, while the per-face
# dicts serve real calibrated hardware. _resolve below is what allows both.
def estimate_sun_vector(
    face_readings: Mapping[str, Mapping[str, float]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
) -> np.ndarray:
    """Full estimation pipeline over :func:`simulate_faces`-style readings."""
    # Two empty lists to fill as the loop walks the faces. The `: list[float]`
    # annotations document what will go in them.
    corrected: list[float] = []
    normals: list[np.ndarray] = []
    # Iterating over FACE_NAMES rather than over the dict's own keys guarantees
    # canonical order, so corrected[2] and normals[2] always mean the same face.
    # Dict ordering should not be relied on for something this load-bearing.
    for face in FACE_NAMES:
        v_i = float(face_readings[face]["reading"])
        d_i = _resolve(dark_offset, face, 0.0)
        g_i = _resolve(gain, face, 1.0)
        # .append adds one item to the end of a list.
        corrected.append(corrected_reading(v_i, d_i, g_i))
        normals.append(FACE_NORMALS[face])

    # A list comprehension (primer 10): formula 2 for each face. Note every call
    # passes the FULL corrected list as well as the single value, because a
    # share needs the total.
    weights = [face_weight(r_i, corrected) for r_i in corrected]
    d = direction_vector(weights, normals)
    # Returning the call directly: sun_vector runs, and its result is handed
    # straight back to whoever called estimate_sun_vector.
    return sun_vector(d)


# Internal helper (leading underscore, primer 12).
#
# PARAMETERS
#   param   - either a single number or a per-face dict. This function is what
#             lets the caller above accept both.
#   face    - which face is being asked about, used only in the dict case.
#   default - what to use if param is a dict that has no entry for this face.
# RETURNS
#   one plain float.
#
# Without this, every calibration parameter would need two code paths at every
# call site. One small function absorbs that difference once.
def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face calibration parameter to a float."""
    # isinstance asks "is this a dict-like thing?". If so, look up this face.
    # .get returns the default when the key is missing instead of raising
    # KeyError, so a partial calibration file still works.
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    # Otherwise it is a single number: the same value applies to every face.
    return float(param)


# --- Converting a vector into two angles ---
#
# PARAMETER
#   sun_vector - a unit vector [x, y, z]. Note this parameter name shadows the
#                sun_vector function above INSIDE this function only. That is
#                legal and harmless here because this function never calls it.
# RETURNS
#   a tuple (azimuth, elevation) in degrees. Unpack with `az, el = ...`.
#
# WHY BOTH FORMS. [0.813, 0.469, 0.342] and "30 degrees round, 20 degrees up"
# describe the same direction, but only the second is readable by a person, so
# the dashboard shows angles and the maths uses vectors.
#
#   azimuth   - the compass-style angle in the horizontal plane, -180 to +180.
#   elevation - the angle above the horizontal plane, -90 to +90.
def sun_angles(sun_vector: np.ndarray) -> "tuple[float, float]":
    """Attitude angles of a unit sun vector, in degrees."""
    # Unpacking three values from the vector at once. The brackets hold a
    # generator expression, a comprehension that produces values one at a time.
    x, y, z = (float(c) for c in sun_vector)
    # arctan2(y, x) recovers an angle from two coordinates. The two-argument
    # form is used rather than arctan(y/x) because it knows which quadrant the
    # point is in, so it distinguishes 45 degrees from 225 degrees. The plain
    # one-argument form cannot, and would silently fold half the sky onto the
    # other half. np.degrees converts radians to degrees.
    azimuth = float(np.degrees(np.arctan2(y, x)))
    # arcsin(z) gives the angle above horizontal, since for a unit vector the z
    # component IS the sine of the elevation.
    #
    # The max/min pair clamps z into [-1, 1]. Mathematically z is already in
    # that range for a unit vector, but floating-point arithmetic can leave it
    # at 1.0000000000000002, and arcsin of anything past 1 is NaN. That single
    # NaN would then spread through every downstream calculation. Reading
    # outward: min(1.0, z) caps the top, max(-1.0, ...) catches the bottom.
    elevation = float(np.degrees(np.arcsin(max(-1.0, min(1.0, z)))))
    # Returning two values makes a tuple (primer 5).
    return azimuth, elevation


# --- The inverse: two angles back into a vector ---
#
# PARAMETERS
#   azimuth_deg   - horizontal angle in degrees.
#   elevation_deg - angle above horizontal in degrees.
# RETURNS
#   the matching unit vector.
#
# WHERE IT IS USED. Virtual mode: the dashboard's sliders give azimuth and
# elevation, and this turns them into the true sun direction that the simulator
# lights the cube from. That true direction is also the reference the estimate
# is scored against, which is what makes angular_error_deg computable in
# Virtual mode and not on real hardware.
def angles_to_vector(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Unit vector for a given azimuth/elevation (inverse of :func:`sun_angles`)."""
    # Trigonometric functions work in radians, so convert first.
    az = np.radians(azimuth_deg)
    el = np.radians(elevation_deg)
    # Standard spherical-to-cartesian conversion. cos(el) is the shadow the
    # vector casts on the horizontal plane, which is then split into x and y by
    # the azimuth; sin(el) is the height. The result automatically has length 1
    # because sin^2 + cos^2 = 1.
    return np.array(
        [np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]
    )
