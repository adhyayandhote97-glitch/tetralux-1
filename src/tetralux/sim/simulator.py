"""Phase 1 — sun-vector simulator (pure forward model).

Ground truth for later phases. Models six face-mounted photodiodes on a 1U
CubeSat and, given a light direction, produces the raw per-face readings a real
sensor array would report. No hardware, no serial — just physics.

The simulator emits raw pre-calibration voltages ``V_i``. Optional per-face gain
``G_i`` and dark offset ``D_i`` let it produce readings that Phase 2's
calibration step inverts exactly: ``corrected_reading(V_i, D_i, G_i)`` recovers
the noise-free optical signal ``S_i``.

Sensor pipeline, applied per face in this exact order:

    S     = intensity * max(0, dot(face_normal, light_dir))   # Lambertian cosine (S_i)
    value = S / G_i + D_i                                      # raw voltage V_i
    value = value + N(0, noise_std)                           # Gaussian noise
    value = max(0.0, value)                                   # no negative photocurrent
    if saturation_limit is not None and value >= saturation_limit:
        value, saturated = saturation_limit, True             # clip + flag

With the defaults (``gain=1.0``, ``dark_current=0.0``) this reduces to
``V_i = S_i`` — the plain forward model. Because calibration is the inverse
(``R_i = (V_i - D_i) * G_i``), a noise-free reading round-trips back to ``S_i``.

Everything here is a pure function with type hints — no classes, no global
state. Noise is made reproducible by passing a seeded ``numpy`` generator.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face parameter to a float for ``face``.

    A plain number applies to every face; a mapping supplies per-face values
    (falling back to ``default`` for any face it omits).
    """
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)


def _unit(v: np.ndarray) -> np.ndarray:
    """Return ``v`` normalized to unit length.

    Args:
        v: Any 3-vector.

    Returns:
        ``v / |v|`` as a float array.

    Raises:
        ValueError: if ``|v| < MIN_EPSILON`` (no direction can be defined).
    """
    v = np.asarray(v, dtype=float)
    norm = float(np.linalg.norm(v))
    if norm < MIN_EPSILON:
        raise ValueError(
            f"light_dir has near-zero length ({norm:.2e}); cannot define a direction"
        )
    return v / norm


def simulate_faces(
    light_dir: np.ndarray,
    intensity: float = 1.0,
    noise_std: float = 0.0,
    dark_current: "float | Mapping[str, float]" = 0.0,
    saturation_limit: float | None = None,
    rng: np.random.Generator | None = None,
    gain: "float | Mapping[str, float]" = 1.0,
) -> dict[str, dict]:
    """Simulate the six photodiode face readings for a given light direction.

    Args:
        light_dir: 3-vector pointing from the cube toward the light source. Need
            not be unit length; it is normalized internally.
        intensity: Peak optical signal of a face pointed straight at the light.
        noise_std: Standard deviation of additive Gaussian noise, per face.
        dark_current: Dark offset ``D_i`` added to every face. Scalar (same for
            all faces) or a mapping of face name -> offset. This is the value
            Phase 2's ``corrected_reading`` subtracts back out.
        saturation_limit: If set, any reading ``>=`` this value is clipped to it
            and flagged as saturated.
        rng: Optional NumPy ``Generator`` for reproducible noise. If ``None`` and
            ``noise_std > 0``, a fresh ``default_rng()`` is created
            (nondeterministic). Pass ``np.random.default_rng(seed)`` for
            reproducible output.
        gain: Per-face responsivity ``G_i``. Scalar or a mapping of face name ->
            gain. The signal is divided by ``G_i`` so that calibration
            (which multiplies by ``G_i``) recovers it. Defaults to 1.0.

    Returns:
        Dict keyed by face name (``"+x"``, ``"-x"``, ...) in canonical order.
        Each value is ``{"reading": float, "saturated": bool}``.

    Raises:
        ValueError: if ``light_dir`` has near-zero length.
    """
    direction = _unit(light_dir)

    if noise_std > 0.0 and rng is None:
        rng = np.random.default_rng()

    result: dict[str, dict] = {}
    for name in FACE_NAMES:
        normal = FACE_NORMALS[name]
        gain_i = _resolve(gain, name, 1.0)
        dark_i = _resolve(dark_current, name, 0.0)

        signal = intensity * max(0.0, float(np.dot(normal, direction)))  # S_i
        value = signal / gain_i + dark_i                                 # raw V_i
        if noise_std > 0.0:
            value += float(rng.normal(0.0, noise_std))
        value = max(0.0, value)                # photodiodes can't read negative

        saturated = False
        if saturation_limit is not None and value >= saturation_limit:
            value = float(saturation_limit)
            saturated = True

        result[name] = {"reading": value, "saturated": saturated}

    return result


def generate_sweep(
    step_deg: float = 15.0,
    intensity: float = 1.0,
    noise_std: float = 0.0,
    dark_current: "float | Mapping[str, float]" = 0.0,
    saturation_limit: float | None = None,
    rng: np.random.Generator | None = None,
    gain: "float | Mapping[str, float]" = 1.0,
) -> list[tuple[np.ndarray, dict]]:
    """Sweep the light direction across the +z hemisphere and return ground-truth
    ``(light_dir, face_readings)`` pairs.

    Azimuth runs ``[0, 360)`` degrees and elevation runs ``[0, 90]`` degrees,
    both at ``step_deg`` spacing. At the pole (elevation 90 deg) every azimuth
    collapses to the same ``+z`` vector, so a single sample is emitted there.
    Ordering is deterministic (elevation-major, then azimuth).

    Each ``light_dir`` is a unit vector and is the ground-truth ``s_hat_ref`` for
    Phase 2 angular-error validation (formula 11 in ``docs/architecture.md``).

    Args:
        step_deg: Angular spacing, in degrees, for both azimuth and elevation.
        intensity: Passed through to :func:`simulate_faces`.
        noise_std: Passed through to :func:`simulate_faces`.
        dark_current: Passed through to :func:`simulate_faces`.
        saturation_limit: Passed through to :func:`simulate_faces`.
        rng: Passed through to :func:`simulate_faces` for reproducible noise.
        gain: Passed through to :func:`simulate_faces`.

    Returns:
        List of ``(light_dir, face_readings)`` pairs, where ``light_dir`` is a
        unit ``np.ndarray`` and ``face_readings`` is the dict returned by
        :func:`simulate_faces`.

    Raises:
        ValueError: if ``step_deg`` is not positive.
    """
    if step_deg <= 0.0:
        raise ValueError(f"step_deg must be positive, got {step_deg}")

    n_az = int(round(360.0 / step_deg))   # azimuth steps, 360 deg excluded
    n_el = int(round(90.0 / step_deg))    # elevation steps up to and including 90

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
        return light_dir, readings

    pairs: list[tuple[np.ndarray, dict]] = []
    for i_el in range(n_el + 1):
        elev = i_el * step_deg
        if elev >= 90.0:                  # pole: single +z sample, all azimuths equal
            pairs.append(_sample(np.array([0.0, 0.0, 1.0])))
            continue

        el_r = np.radians(elev)
        for i_az in range(n_az):
            az_r = np.radians(i_az * step_deg)
            light_dir = np.array(
                [
                    np.cos(el_r) * np.cos(az_r),
                    np.cos(el_r) * np.sin(az_r),
                    np.sin(el_r),
                ]
            )
            pairs.append(_sample(light_dir))

    return pairs
