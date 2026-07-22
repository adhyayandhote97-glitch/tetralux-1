"""Phase 3 — fault detection for the sun-direction estimate.

Classifies the health of a single sensor frame *before* trusting its estimate,
covering three of the project's failure modes:

- **Low signal** — total light ~ 0 (the divide-by-zero case the estimator
  guards with ``LowSignalError``); here it is reported as a status, not raised.
- **Saturation** — one or more faces pinned at the ADC rail; the direction is
  unreliable when the *dominant* face is saturated.
- **Multi-source ambiguity** — the light field does not look like a single point
  source, so the weighted-average vector is a meaningless "in between" direction.

The multi-source signal uses a simple, interpretable property of a single point
source: within each opposite face pair (``+x``/``-x`` etc.) at most one face is
lit, so ``min(R+, R-)`` is ~0. When both faces of a pair are strongly lit, light
is arriving from both sides. ``opposition_ratio`` aggregates this into ``[0, 1]``
(0 = clean single source, 1 = fully bidirectional).

Packet-integrity faults (corrupted/truncated telemetry) live in
:mod:`tetralux.faults.packets`.
"""

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
    """Result of assessing one sensor frame.

    Attributes:
        ok: True when no faults were raised (the estimate can be trusted).
        faults: The fault codes present, in detection order.
        total_signal: Sum of (floored) corrected readings across all faces.
        dominant_face: Face with the largest corrected reading (or None if dark).
        saturated_faces: Names of faces flagged saturated by the simulator.
        opposition_ratio: Multi-source indicator in [0, 1].
        details: Extra diagnostic values (e.g. dominant_saturated).
    """

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
    """Calibrate a raw frame to corrected readings ``R_i``, floored at 0.

    Photodiodes cannot report negative current, so noise pushing ``R_i`` below
    zero is clamped — this keeps the opposition/total metrics physical.
    """
    corrected: dict[str, float] = {}
    for face in FACE_NAMES:
        v_i = float(face_readings[face]["reading"])
        r_i = corrected_reading(
            v_i, _resolve(dark_offset, face, 0.0), _resolve(gain, face, 1.0)
        )
        corrected[face] = max(0.0, r_i)
    return corrected


def opposition_ratio(corrected: Mapping[str, float]) -> float:
    """Multi-source indicator in ``[0, 1]`` from corrected readings.

    ``2 * sum_pairs(min(R+, R-)) / total``. 0 for a clean single source, 1 when
    light is split evenly across opposite faces. Returns 0.0 for a dark frame.
    """
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
    """Assess one raw sensor frame and return a :class:`FrameHealth`.

    Args:
        face_readings: ``simulate_faces``-style mapping (raw ``V_i`` + saturated).
        dark_offset: Dark offset ``D_i`` for calibration (scalar or per-face).
        gain: Gain ``G_i`` for calibration (scalar or per-face).
        low_signal_threshold: Total corrected signal below this -> LOW_SIGNAL.
        opposition_threshold: ``opposition_ratio`` at/above this -> MULTI_SOURCE.

    Returns:
        A frozen :class:`FrameHealth` describing the frame.
    """
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
    """Assess a frame and estimate its sun vector, never raising on bad input.

    Returns ``(sun_vector, health)``. The vector is ``None`` when the frame is
    low-signal (no resolvable direction); otherwise it is the unit estimate.
    Faults such as saturation or multi-source do **not** suppress the estimate —
    they are reported in ``health`` so the caller can decide whether to trust it.
    """
    health = assess_frame(face_readings, dark_offset, gain, **assess_kwargs)  # type: ignore[arg-type]
    if health.has(FaultCode.LOW_SIGNAL):
        return None, health
    try:
        vector = estimate_sun_vector(face_readings, dark_offset, gain)
    except LowSignalError:
        return None, health
    return vector, health
