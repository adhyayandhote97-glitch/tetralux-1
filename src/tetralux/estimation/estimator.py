"""Phase 2 - sun-vector estimation engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


class LowSignalError(Exception):
    """Raised when total signal (or direction magnitude) is below MIN_EPSILON."""


def corrected_reading(V_i: float, D_i: float, G_i: float) -> float:
    """Formula 1 - corrected face reading: ``R_i = (V_i - D_i) * G_i``."""
    return (V_i - D_i) * G_i


def face_weight(R_i: float, all_R: Sequence[float]) -> float:
    """Formula 2 - face weight: ``w_i = R_i / sum(all_R)``."""
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
    """Formula 3 - direction vector: ``d = sum(w_i * n_hat_i)``."""
    d = np.zeros(3)
    for w, n in zip(weights, face_normals):
        d = d + float(w) * np.asarray(n, dtype=float)
    return d


def sun_vector(d: np.ndarray) -> np.ndarray:
    """Formula 4 (LOCKED) - sun vector: ``s_hat = d / |d|``."""
    d = np.asarray(d, dtype=float)
    magnitude = float(np.linalg.norm(d))
    if magnitude < MIN_EPSILON:
        raise LowSignalError(
            f"|d| {magnitude:.2e} below MIN_EPSILON ({MIN_EPSILON:.0e}); "
            "no resolvable direction"
        )
    return d / magnitude


def cosine_proxy(R_i: float, V_max_i: float) -> float:
    """Formula 5 - cosine proxy: ``cos(theta_i) = R_i / V_max_i``."""
    if abs(V_max_i) < MIN_EPSILON:
        raise ValueError("V_max_i must be non-zero to form a cosine proxy")
    return R_i / V_max_i


def estimate_sun_vector(
    face_readings: Mapping[str, Mapping[str, float]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
) -> np.ndarray:
    """Full estimation pipeline over :func:`simulate_faces`-style readings."""
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


def sun_angles(sun_vector: np.ndarray) -> "tuple[float, float]":
    """Attitude angles of a unit sun vector, in degrees."""
    x, y, z = (float(c) for c in sun_vector)
    azimuth = float(np.degrees(np.arctan2(y, x)))
    elevation = float(np.degrees(np.arcsin(max(-1.0, min(1.0, z)))))
    return azimuth, elevation


def angles_to_vector(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Unit vector for a given azimuth/elevation (inverse of :func:`sun_angles`)."""
    az = np.radians(azimuth_deg)
    el = np.radians(elevation_deg)
    return np.array(
        [np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)]
    )
