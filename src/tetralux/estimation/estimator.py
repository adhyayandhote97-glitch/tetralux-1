"""Phase 2 — sun-vector estimation engine.

Implements the LOCKED formulas 1-5 from ``docs/architecture.md`` as pure,
independently testable functions, plus a full pipeline that runs them against
Phase 1's :func:`tetralux.sim.simulator.simulate_faces` output:

    raw readings (V_i) -> corrected (R_i) -> weights (w_i) -> direction (d) -> sun vector (s_hat)

Divide-by-zero is guarded per the locked epsilon behavior: when the total signal
or the direction magnitude falls below ``MIN_EPSILON``, :class:`LowSignalError`
is raised instead of returning a noise-driven garbage vector.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


class LowSignalError(Exception):
    """Raised when total signal (or direction magnitude) is below MIN_EPSILON.

    Signals a low-signal/invalid frame (e.g. total light ~ 0) so callers can
    skip it rather than divide by ~0 and emit a meaningless direction.
    """


def corrected_reading(V_i: float, D_i: float, G_i: float) -> float:
    """Formula 1 — corrected face reading: ``R_i = (V_i - D_i) * G_i``.

    Removes the dark offset ``D_i`` and applies the per-face gain ``G_i``.

    Example: ``corrected_reading(720, 20, 1.05) == 735.0``.
    """
    return (V_i - D_i) * G_i


def face_weight(R_i: float, all_R: Sequence[float]) -> float:
    """Formula 2 — face weight: ``w_i = R_i / sum(all_R)``.

    Args:
        R_i: This face's corrected reading.
        all_R: Corrected readings for all six faces.

    Returns:
        The normalized share of total signal for this face.

    Raises:
        LowSignalError: if ``sum(all_R) < MIN_EPSILON`` (total light ~ 0).
    """
    total = float(sum(all_R))
    if abs(total) < MIN_EPSILON:
        raise LowSignalError(
            f"total signal {total:.2e} below MIN_EPSILON ({MIN_EPSILON:.0e}); "
            "low-signal/invalid frame"
        )
    return R_i / total


def direction_vector(
    weights: Sequence[float], face_normals: Sequence[np.ndarray]
) -> np.ndarray:
    """Formula 3 — direction vector: ``d = sum(w_i * n_hat_i)``.

    Weighted sum of face normals. ``weights`` and ``face_normals`` must be
    aligned (same order, same length).
    """
    d = np.zeros(3)
    for w, n in zip(weights, face_normals):
        d = d + float(w) * np.asarray(n, dtype=float)
    return d


def sun_vector(d: np.ndarray) -> np.ndarray:
    """Formula 4 (LOCKED) — sun vector: ``s_hat = d / |d|``.

    Args:
        d: The unnormalized direction vector from :func:`direction_vector`.

    Returns:
        The unit sun-direction vector.

    Raises:
        LowSignalError: if ``|d| < MIN_EPSILON`` (ambiguous / no direction).
    """
    d = np.asarray(d, dtype=float)
    magnitude = float(np.linalg.norm(d))
    if magnitude < MIN_EPSILON:
        raise LowSignalError(
            f"|d| {magnitude:.2e} below MIN_EPSILON ({MIN_EPSILON:.0e}); "
            "no resolvable direction"
        )
    return d / magnitude


def cosine_proxy(R_i: float, V_max_i: float) -> float:
    """Formula 5 — cosine proxy: ``cos(theta_i) = R_i / V_max_i``.

    Treats each calibrated reading as proportional to the cosine of the angle
    between the face normal and the sun.

    Raises:
        ValueError: if ``V_max_i`` is ~0 (undefined reference).
    """
    if abs(V_max_i) < MIN_EPSILON:
        raise ValueError("V_max_i must be non-zero to form a cosine proxy")
    return R_i / V_max_i


def estimate_sun_vector(
    face_readings: Mapping[str, Mapping[str, float]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
) -> np.ndarray:
    """Full estimation pipeline over :func:`simulate_faces`-style readings.

    Runs formulas 1 -> 2 -> 3 -> 4 end to end:
    calibrate each raw ``V_i`` to ``R_i``, normalize to weights, build the
    weighted direction vector, and normalize to the unit sun vector.

    Args:
        face_readings: Mapping of face name -> ``{"reading": V_i, ...}`` exactly
            as returned by :func:`tetralux.sim.simulator.simulate_faces`.
        dark_offset: Dark offset ``D_i`` used for calibration. Scalar or per-face
            mapping. Must match what the simulator used to recover ``S_i``.
        gain: Per-face gain ``G_i`` used for calibration. Scalar or per-face
            mapping.

    Returns:
        The estimated unit sun-direction vector (``np.ndarray`` shape ``(3,)``).

    Raises:
        LowSignalError: if the frame carries no resolvable signal.
    """
    corrected: list[float] = []
    normals: list[np.ndarray] = []
    for face in FACE_NAMES:
        v_i = float(face_readings[face]["reading"])
        d_i = _resolve(dark_offset, face, 0.0)
        g_i = _resolve(gain, face, 1.0)
        corrected.append(corrected_reading(v_i, d_i, g_i))
        normals.append(FACE_NORMALS[face])

    weights = [face_weight(r_i, corrected) for r_i in corrected]
    d = direction_vector(weights, normals)
    return sun_vector(d)


def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face calibration parameter to a float."""
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)
