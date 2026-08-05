"""Phase 3 - fault detection for the sun-direction estimate."""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from tetralux.constants import FACE_NAMES, MIN_EPSILON
from tetralux.estimation.estimator import (
    LowSignalError,
    corrected_reading,
    estimate_sun_vector,
)

# Opposite face pairs used for the multi-source (opposition) test.
FACE_PAIRS: list[tuple[str, str]] = [("+x", "-x"), ("+y", "-y"), ("+z", "-z")]

# Defaults for the fault thresholds. `LOW_SIGNAL_THRESHOLD` is the divide-by-zero
# guard; callers that know their intensity scale can pass a larger value.
LOW_SIGNAL_THRESHOLD: float = MIN_EPSILON
OPPOSITION_THRESHOLD: float = 0.20


class FaultCode(enum.Enum):
    """Discrete fault categories a frame can carry."""

    LOW_SIGNAL = "low_signal"
    SATURATION = "saturation"
    MULTI_SOURCE = "multi_source"


@dataclass(frozen=True)
class FrameHealth:
    """Result of assessing one sensor frame."""

    ok: bool
    faults: tuple[FaultCode, ...]
    total_signal: float
    dominant_face: Optional[str]
    saturated_faces: tuple[str, ...]
    opposition_ratio: float
    details: dict = field(default_factory=dict)

    def has(self, code: FaultCode) -> bool:
        """Return True if ``code`` is among this frame's faults."""
        return code in self.faults


def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face calibration parameter to a float."""
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)


def corrected_frame(
    face_readings: Mapping[str, Mapping[str, float]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
) -> dict[str, float]:
    """Calibrate a raw frame to corrected readings ``R_i``, floored at 0."""
    corrected: dict[str, float] = {}
    for face in FACE_NAMES:
        v_i = float(face_readings[face]["reading"])
        r_i = corrected_reading(
            v_i, _resolve(dark_offset, face, 0.0), _resolve(gain, face, 1.0)
        )
        corrected[face] = max(0.0, r_i)
    return corrected


def opposition_ratio(corrected: Mapping[str, float]) -> float:
    """Multi-source indicator in ``[0, 1]`` from corrected readings."""
    total = float(sum(corrected[f] for f in FACE_NAMES))
    if total < MIN_EPSILON:
        return 0.0
    overlap = sum(min(corrected[a], corrected[b]) for a, b in FACE_PAIRS)
    return float(2.0 * overlap / total)


def saturated_face_names(
    face_readings: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    """Names of faces the simulator flagged as saturated, in canonical order."""
    return tuple(f for f in FACE_NAMES if bool(face_readings[f].get("saturated", False)))


def assess_frame(
    face_readings: Mapping[str, Mapping[str, object]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
    *,
    low_signal_threshold: float = LOW_SIGNAL_THRESHOLD,
    opposition_threshold: float = OPPOSITION_THRESHOLD,
) -> FrameHealth:
    """Assess one raw sensor frame and return a :class:`FrameHealth`."""
    corrected = corrected_frame(face_readings, dark_offset, gain)
    total = float(sum(corrected.values()))
    saturated = saturated_face_names(face_readings)

    dominant: Optional[str] = None
    if total >= MIN_EPSILON:
        dominant = max(FACE_NAMES, key=lambda f: corrected[f])

    ratio = opposition_ratio(corrected)

    faults: list[FaultCode] = []
    if total < low_signal_threshold:
        faults.append(FaultCode.LOW_SIGNAL)
    if saturated:
        faults.append(FaultCode.SATURATION)
    if ratio >= opposition_threshold:
        faults.append(FaultCode.MULTI_SOURCE)

    dominant_saturated = dominant is not None and dominant in saturated

    return FrameHealth(
        ok=not faults,
        faults=tuple(faults),
        total_signal=total,
        dominant_face=dominant,
        saturated_faces=saturated,
        opposition_ratio=ratio,
        details={"dominant_saturated": dominant_saturated},
    )


def safe_estimate(
    face_readings: Mapping[str, Mapping[str, object]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
    **assess_kwargs: object,
) -> tuple[Optional[np.ndarray], FrameHealth]:
    """Assess a frame and estimate its sun vector, never raising on bad input."""
    health = assess_frame(face_readings, dark_offset, gain, **assess_kwargs)  # type: ignore[arg-type]
    if health.has(FaultCode.LOW_SIGNAL):
        return None, health
    try:
        vector = estimate_sun_vector(face_readings, dark_offset, gain)
    except LowSignalError:
        return None, health
    return vector, health
