"""Solar radiation pressure (SRP) physics (formulas 6-10 from docs/architecture.md)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def srp_force_per_face(I_i: float, A: float, c: float, rho: float) -> float:
    """Formula 6 - SRP force on one illuminated face."""
    return (I_i * A / c) * (1.0 + rho)


def srp_net_force(
    forces: Sequence[float], face_normals: Sequence[np.ndarray]
) -> np.ndarray:
    """Formula 7 - net SRP force vector: ``F_net = sum(F_i * n_hat_i)``."""
    f_net = np.zeros(3)
    for f, n in zip(forces, face_normals):
        f_net = f_net + float(f) * np.asarray(n, dtype=float)
    return f_net


def srp_magnitude(F_net: np.ndarray) -> float:
    """Formula 8 - SRP force magnitude: ``|F_net| = sqrt(Fx^2 + Fy^2 + Fz^2)``."""
    return float(np.linalg.norm(np.asarray(F_net, dtype=float)))


def srp_azimuth(Fx: float, Fy: float) -> float:
    """Formula 9 - SRP azimuth (radians): ``arctan2(Fy, Fx)``."""
    return float(np.arctan2(Fy, Fx))


def srp_elevation(Fz: float, F_net_mag: float) -> float:
    """Formula 10 - SRP elevation (radians): ``arcsin(Fz / |F_net|)``."""
    if F_net_mag == 0:
        raise ValueError("F_net_mag must be non-zero")
    ratio = max(-1.0, min(1.0, Fz / F_net_mag))
    return float(np.arcsin(ratio))
