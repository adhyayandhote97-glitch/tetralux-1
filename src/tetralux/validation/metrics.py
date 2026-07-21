"""Validation metrics (formulas 11-14 from docs/architecture.md).

Pure functions used to score estimation quality against a known reference.
Consumed later by the Phase 6 test suite; kept separate from the estimator so
the direction pipeline has no dependency on how it is graded.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def angular_error(s_hat: np.ndarray, s_hat_ref: np.ndarray) -> float:
    """Formula 11 — angular error (radians) between estimate and reference.

    ``theta_error = arccos(clamp(s_hat . s_hat_ref, -1, 1))``

    The dot product is clamped to ``[-1, 1]`` so floating-point drift just past
    the unit range never yields NaN.

    Example: two unit vectors with dot ~0.98 -> ~0.199 rad (~11.5 deg).
    """
    a = np.asarray(s_hat, dtype=float)
    b = np.asarray(s_hat_ref, dtype=float)
    dot = float(np.dot(a, b))
    dot = max(-1.0, min(1.0, dot))
    return float(np.arccos(dot))


def repeatability(theta_error_series: Sequence[float]) -> float:
    """Formula 12 — repeatability: standard deviation of the angular-error series.

    Uses the population standard deviation (``ddof=0``).

    Example: ``[10, 11, 12, 11, 10] -> ~0.748``.
    """
    return float(np.std(np.asarray(theta_error_series, dtype=float)))


def bias(theta_error_series: Sequence[float]) -> float:
    """Formula 13 — bias: mean of the angular-error series (systematic offset).

    Example: ``[10, 11, 12] -> 11.0``.
    """
    return float(np.mean(np.asarray(theta_error_series, dtype=float)))


def temp_drift_rate(T_now: float, T_prev: float, dt: float) -> float:
    """Formula 14 — temperature drift rate: ``(T_now - T_prev) / dt``.

    Example: ``temp_drift_rate(24.5, 24.0, 1.0) == 0.5`` (deg per unit time).

    Raises:
        ValueError: if ``dt`` is zero.
    """
    if dt == 0:
        raise ValueError("dt must be non-zero")
    return (T_now - T_prev) / dt
