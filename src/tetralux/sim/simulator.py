"""Phase 1 - sun-vector simulator (pure forward model).

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the estimator run backwards. estimator.py asks "given six brightness
readings, where is the light?"; this file asks "given a light direction, what
would the six photodiodes read?". That is what "forward model" means: it follows
physics in its natural direction, from cause to effect.

WHY THAT IS WORTH BUILDING. Without it there is no way to know whether the
estimator works. Point real hardware at a lamp and it produces an answer, but
nothing tells you the true direction to score it against. Here the true
direction is an input, so the whole loop can be closed: pick a direction,
simulate what the sensors would see, feed that to the estimator, and compare its
answer against the direction you started from. Any error is the estimator's.

That loop is why angular_error_deg exists in Virtual mode and not on real
hardware, and it is how the entire project was developed and tested before a
single component was soldered.

THE PHYSICS: LAMBERT'S COSINE LAW. A flat surface collects light in proportion
to the cosine of the angle between the light and the surface's normal. Straight
on gives cosine 1, full brightness; at 60 degrees, cosine 0.5, half; edge-on,
cosine 0, nothing. A face pointing away from the light is not negatively lit, it
is simply dark, which is what the max(0, ...) below enforces.

The dot product of two unit vectors IS that cosine, so the physics reduces to a
single np.dot per face.

WHAT IT MODELS BEYOND THE IDEAL. Real sensors are not perfect, so this can
optionally add gain spread, dark current, random noise, and saturation clipping.
Turning those on is how the estimator gets tested against realistic imperfect
data rather than only against clean textbook numbers.

WHERE IT SITS IN THE FLOW
    sim/sensors.py      wraps this to build complete SensorFrames
    dashboard/state.py  drives it from the azimuth/elevation sliders
    estimator.py        consumes the dict shape this produces

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


# Internal helper (primer 12), the same scalar-or-dict resolver as in
# estimator.py. It is duplicated rather than imported to keep this module a
# self-contained forward model with no dependency on the estimation code it
# exists to test. A simulator that imported from the thing under test could hide
# a shared bug from both.
#
# PARAMETERS
#   param   - one number for all faces, or a per-face dict.
#   face    - which face is being asked about.
#   default - fallback if a dict has no entry for this face.
# RETURNS
#   one plain float.
def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face parameter to a float for ``face``."""
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)


# PARAMETER
#   v - any 3D vector.
# RETURNS
#   the same direction at length 1.
#
# The caller may pass [3, 4, 0], meaning "toward positive x and y", without
# having to normalize it first. Lambert's law needs a unit vector, because the
# dot product only equals the cosine when both vectors have length 1; feeding it
# a length-5 vector would report brightness five times too high.
def _unit(v: np.ndarray) -> np.ndarray:
    """Return ``v`` normalized to unit length."""
    v = np.asarray(v, dtype=float)
    norm = float(np.linalg.norm(v))
    # A zero-length vector points nowhere, so there is nothing to simulate.
    # ValueError, not LowSignalError: this is a caller mistake, not a dark sky.
    # To simulate darkness, pass a valid direction with intensity=0.0.
    if norm < MIN_EPSILON:
        raise ValueError(
            f"light_dir has near-zero length ({norm:.2e}); cannot define a direction"
        )
    return v / norm


# --- The forward model itself ---
#
# PARAMETERS
#   light_dir        - REQUIRED. The direction the light comes FROM, as a 3D
#                      vector. Need not be unit length; _unit handles that.
#   intensity        - how bright the source is, in whatever scale the caller
#                      wants. 1.0 gives readings between 0 and 1 for maths;
#                      sensors.py passes hundreds to imitate ADC counts.
#   noise_std        - the standard deviation of random noise added to each
#                      reading. 0.0 means a perfectly clean sensor. Larger
#                      values imitate a real noisy photodiode.
#   dark_current     - what each face reads with no light. Scalar or per-face.
#                      Mirrors the D_i that calibration removes.
#   saturation_limit - the ceiling a reading is clipped at, or None for no
#                      ceiling. Real hardware passes ADC_MAX.
#   rng              - a random number generator, or None. See below.
#   gain             - per-face sensitivity, mirroring the G_i in calibration.
# RETURNS
#   {"+x": {"reading": 812.4, "saturated": False}, ...} for all six faces.
#
# Only light_dir is required; every imperfection defaults to off. So a one-line
# call gives the ideal physics, and each flaw can be switched on individually to
# see what it does to the estimate. That is the point of the defaults.
def simulate_faces(
    light_dir: np.ndarray,
    intensity: float = 1.0,
    noise_std: float = 0.0,
    dark_current: "float | Mapping[str, float]" = 0.0,
    saturation_limit: float | None = None,
    rng: np.random.Generator | None = None,
    gain: "float | Mapping[str, float]" = 1.0,
) -> dict[str, dict]:
    """Simulate the six photodiode face readings for a given light direction."""
    direction = _unit(light_dir)

    # Create a generator only if noise was actually requested. Passing an rng in
    # is what makes a test REPRODUCIBLE: seed it, and the same "random" noise
    # comes out every run, so a test that passes today cannot fail tomorrow for
    # no reason. Left as None here, the results differ each call, which is what
    # a live demo wants.
    if noise_std > 0.0 and rng is None:
        rng = np.random.default_rng()

    result: dict[str, dict] = {}
    for name in FACE_NAMES:
        normal = FACE_NORMALS[name]
        gain_i = _resolve(gain, name, 1.0)
        dark_i = _resolve(dark_current, name, 0.0)

        # LAMBERT'S COSINE LAW, the one line that carries the physics.
        #
        # np.dot(normal, direction) is the cosine of the angle between this
        # face and the light, because both are unit vectors.
        #
        # max(0.0, ...) is the physically essential part. A face pointing away
        # gives a NEGATIVE dot product, and negative light does not exist; that
        # face is simply in shadow. Without this clip the simulator would report
        # negative readings, the weights in formula 2 would go haywire, and the
        # estimator would appear broken when the fault was here.
        signal = intensity * max(0.0, float(np.dot(normal, direction)))  # S_i

        # Now run the calibration equation BACKWARDS to produce a raw reading.
        #
        # Formula 1 recovers signal from raw as (V_i - D_i) * G_i. Inverting it
        # gives V_i = signal / G_i + D_i, exactly this line. Doing it this way
        # means that when the estimator applies the matching calibration it
        # recovers the original signal exactly, which is what makes the
        # round-trip test meaningful rather than circular.
        value = signal / gain_i + dark_i                                 # raw V_i
        if noise_std > 0.0:
            # Gaussian ("normal") noise centred on zero: usually small, rarely
            # large, symmetric around the true value. That is how thermal noise
            # in real electronics behaves.
            value += float(rng.normal(0.0, noise_std))
        value = max(0.0, value)                # photodiodes can't read negative
        # The second clip is needed because noise can push a near-zero reading
        # below zero, which no ADC can output.

        # SATURATION. Above its ceiling a real ADC simply stops counting, so the
        # true brightness becomes unknowable: 1023 could mean 1023 or ten times
        # that. Clipping models exactly that loss of information.
        #
        # The flag matters as much as the clipped value. A saturated reading
        # UNDERSTATES the true light, so a face at its ceiling drags the
        # estimate toward the other faces. The fault detector and the SRP
        # calculation both read this flag and exclude those faces.
        saturated = False
        if saturation_limit is not None and value >= saturation_limit:
            value = float(saturation_limit)
            saturated = True

        # The nested dict shape carries the flag alongside the number. A bare
        # number could not say whether it was clipped, and every consumer
        # downstream needs to know.
        result[name] = {"reading": value, "saturated": saturated}

    return result


# --- Sweeping the whole sky ---
#
# One direction proves the estimator works at one direction. This walks a grid
# of directions across the hemisphere so accuracy can be checked everywhere,
# which is how a systematic weakness at certain angles gets caught.
#
# PARAMETERS
#   step_deg - grid spacing in degrees. 15.0 gives a manageable few hundred
#              samples; smaller is finer and slower.
#   the rest - passed straight through to simulate_faces, unchanged.
# RETURNS
#   a list of (true_direction, readings) pairs. Each pair is a test case with
#   its own answer key attached.
def generate_sweep(
    step_deg: float = 15.0,
    intensity: float = 1.0,
    noise_std: float = 0.0,
    dark_current: "float | Mapping[str, float]" = 0.0,
    saturation_limit: float | None = None,
    rng: np.random.Generator | None = None,
    gain: "float | Mapping[str, float]" = 1.0,
) -> list[tuple[np.ndarray, dict]]:
    """Sweep the light direction across the +z hemisphere and return ground-truth ``(light_dir, face_readings)`` pairs."""
    # A step of zero would divide by zero below; a negative step is meaningless.
    # The f-string quotes the offending value so the message is actionable.
    if step_deg <= 0.0:
        raise ValueError(f"step_deg must be positive, got {step_deg}")

    n_az = int(round(360.0 / step_deg))   # azimuth steps, 360 deg excluded
    n_el = int(round(90.0 / step_deg))    # elevation steps up to and including 90
    # 360 is excluded because it is the same direction as 0, so sampling both
    # would duplicate a whole ring of test cases.

    # A NESTED FUNCTION: a def inside a def. _sample exists only inside
    # generate_sweep and can see its parameters directly, which is why it need
    # not take intensity, noise_std and the rest as arguments. That keeps the
    # two call sites below short instead of repeating seven arguments twice.
    def _sample(light_dir: np.ndarray) -> tuple[np.ndarray, dict]:
        readings = simulate_faces(
            light_dir,
            intensity=intensity,
            noise_std=noise_std,
            dark_current=dark_current,
            saturation_limit=saturation_limit,
            rng=rng,
            gain=gain,
        )
        # Returning the truth alongside the readings is what makes the pair a
        # test case rather than just data.
        return light_dir, readings

    pairs: list[tuple[np.ndarray, dict]] = []
    # Outer loop: elevation, from the horizon up to straight overhead.
    # `n_el + 1` because range stops one short, and elevation 90 must be
    # included.
    for i_el in range(n_el + 1):
        elev = i_el * step_deg
        # THE POLE. Straight up is a single direction: at elevation 90 every
        # azimuth describes the same point, the way every direction from the
        # North Pole is south. Running the azimuth loop here would generate n_az
        # identical samples. One is taken instead, then `continue` skips to the
        # next elevation.
        if elev >= 90.0:                  # pole: single +z sample, all azimuths equal
            pairs.append(_sample(np.array([0.0, 0.0, 1.0])))
            continue

        el_r = np.radians(elev)
        # Inner loop: azimuth, all the way around at this elevation.
        for i_az in range(n_az):
            az_r = np.radians(i_az * step_deg)
            # The same spherical-to-cartesian conversion as
            # estimator.angles_to_vector: cos(el) is the horizontal reach, split
            # into x and y by the azimuth, and sin(el) is the height.
            light_dir = np.array(
                [
                    np.cos(el_r) * np.cos(az_r),
                    np.cos(el_r) * np.sin(az_r),
                    np.sin(el_r),
                ]
            )
            pairs.append(_sample(light_dir))

    return pairs
