"""Phase 1 - sun-vector simulator (pure forward model)."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from tetralux.constants import FACE_NAMES, FACE_NORMALS, MIN_EPSILON


def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face parameter to a float for ``face``."""
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)


def _unit(v: np.ndarray) -> np.ndarray:
    """Return ``v`` normalized to unit length."""
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
    """Simulate the six photodiode face readings for a given light direction."""
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
    """Sweep the light direction across the +z hemisphere and return ground-truth ``(light_dir, face_readings)`` pairs."""
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
