"""Validation metrics (formulas 11-14 from docs/architecture.md)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def angular_error(s_hat: np.ndarray, s_hat_ref: np.ndarray) -> float:
    """Formula 11 - angular error (radians) between estimate and reference."""
    a = np.asarray(s_hat, dtype=float)
    b = np.asarray(s_hat_ref, dtype=float)
    dot = float(np.dot(a, b))
    dot = max(-1.0, min(1.0, dot))
    return float(np.arccos(dot))


def repeatability(theta_error_series: Sequence[float]) -> float:
    """Formula 12 - repeatability: standard deviation of the angular-error series."""
    return float(np.std(np.asarray(theta_error_series, dtype=float)))


def bias(theta_error_series: Sequence[float]) -> float:
    """Formula 13 - bias: mean of the angular-error series (systematic offset)."""
    return float(np.mean(np.asarray(theta_error_series, dtype=float)))


def temp_drift_rate(T_now: float, T_prev: float, dt: float) -> float:
    """Formula 14 - temperature drift rate: ``(T_now - T_prev) / dt``."""
    if dt == 0:
        raise ValueError("dt must be non-zero")
    return (T_now - T_prev) / dt
