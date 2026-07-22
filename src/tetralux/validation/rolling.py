"""Rolling and burst validation metrics (Phase 6).

Wraps the pure formulas 11-13 (`angular_error`, `bias`, `repeatability`) with the
state they need for live use:

- `RollingValidator` — a 60-frame window for streaming (Real mode): each update
  returns instantaneous angular error plus rolling bias/repeatability.
- `burst_metrics` — for Virtual mode's instantaneous slider: draw a short burst of
  noisy estimates at a fixed direction to get a meaningful bias/repeatability
  without a running timeline.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Optional

import numpy as np

from tetralux.constants import MIN_EPSILON, ROLLING_WINDOW_SIZE
from tetralux.validation.metrics import angular_error, bias, repeatability


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    norm = float(np.linalg.norm(v))
    if norm < MIN_EPSILON:
        raise ValueError("reference vector has near-zero length")
    return v / norm


class RollingValidator:
    """Streaming angular-error window against a fixed reference direction."""

    def __init__(self, reference: np.ndarray, window: int = ROLLING_WINDOW_SIZE) -> None:
        self._ref = _unit(reference)
        self._errors: deque = deque(maxlen=window)

    def update(self, sun_vector: Optional[np.ndarray]) -> dict:
        """Add an estimate and return angular error + rolling bias/repeatability.

        A ``None`` estimate (low signal) records nothing and returns nan metrics.
        Angles are in **degrees**.
        """
        if sun_vector is None:
            return {"angular_error_deg": None, "bias_deg": None, "repeatability_deg": None}
        err = float(np.degrees(angular_error(sun_vector, self._ref)))
        self._errors.append(err)
        return {
            "angular_error_deg": err,
            "bias_deg": float(bias(self._errors)),
            "repeatability_deg": float(repeatability(self._errors)),
        }

    def set_reference(self, reference: np.ndarray) -> None:
        self._ref = _unit(reference)
        self._errors.clear()

    def reset(self) -> None:
        self._errors.clear()


def burst_metrics(
    sample_fn: Callable[[], Optional[np.ndarray]],
    reference: np.ndarray,
    n: int = 30,
) -> dict:
    """Bias/repeatability from ``n`` fresh estimates at a fixed direction.

    Args:
        sample_fn: Zero-arg callable returning a (noisy) sun vector, or ``None``.
        reference: Ground-truth direction to measure error against.
        n: Number of samples to draw.

    Returns:
        ``{"bias_deg", "repeatability_deg", "n"}`` in degrees.
    """
    ref = _unit(reference)
    errors = []
    for _ in range(n):
        v = sample_fn()
        if v is None:
            continue
        errors.append(float(np.degrees(angular_error(v, ref))))
    if not errors:
        return {"bias_deg": float("nan"), "repeatability_deg": float("nan"), "n": 0}
    return {
        "bias_deg": float(bias(errors)),
        "repeatability_deg": float(repeatability(errors)),
        "n": len(errors),
    }
