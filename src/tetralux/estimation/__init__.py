"""Phase 2: estimation engine — recover the sun vector from face readings.

Implements the LOCKED formulas 1-4 (see docs/architecture.md) and raises
``LowSignalError`` when total signal < MIN_EPSILON.
"""

from tetralux.estimation.estimator import (
    LowSignalError,
    corrected_reading,
    cosine_proxy,
    direction_vector,
    estimate_sun_vector,
    face_weight,
    sun_vector,
)

__all__ = [
    "LowSignalError",
    "corrected_reading",
    "face_weight",
    "direction_vector",
    "sun_vector",
    "cosine_proxy",
    "estimate_sun_vector",
]
