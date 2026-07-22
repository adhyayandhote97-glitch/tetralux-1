"""Phase 5 — replay data preparation (pure, no UI dependency).

Decodes a telemetry byte stream into per-frame records ready for display: each
frame carries its sequence number, timestamp, readings, estimated sun vector,
fault health, and (if a reference trajectory is supplied) the angular error.

This layer imports only numpy and the earlier phases, so it is fully unit
testable without Dash or Plotly installed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

import numpy as np

from tetralux.constants import FACE_NAMES
from tetralux.faults.detector import FrameHealth, safe_estimate
from tetralux.telemetry.packet import DEFAULT_RATE_HZ, iter_packets
from tetralux.validation.metrics import angular_error


@dataclass(frozen=True)
class ReplayFrame:
    """One decoded, estimated, and scored telemetry frame."""

    index: int
    seq: int
    time_s: float
    readings: dict            # {face: ADC count}
    saturated: dict           # {face: bool}
    sun_vector: Optional[np.ndarray]
    reference: Optional[np.ndarray]
    health: FrameHealth
    angular_error_deg: Optional[float]


def build_replay(
    stream: bytes,
    references: Optional[Sequence[np.ndarray]] = None,
    rate_hz: float = DEFAULT_RATE_HZ,
    dark_offset: "float | dict" = 0.0,
    gain: "float | dict" = 1.0,
) -> list[ReplayFrame]:
    """Decode a telemetry stream into a list of :class:`ReplayFrame`.

    Args:
        stream: Concatenated packet bytes (as from ``pack_stream``). Corrupted or
            truncated packets are skipped by the underlying resync parser.
        references: Optional ground-truth directions aligned to *decoded* frame
            order; when present, each frame's angular error is computed.
        rate_hz: Nominal rate; frame ``i`` is timestamped ``i / rate_hz``.
        dark_offset: Calibration dark offset ``D_i`` (scalar or per-face).
        gain: Calibration gain ``G_i`` (scalar or per-face).

    Returns:
        One :class:`ReplayFrame` per successfully decoded packet, in order.
    """
    dt = 1.0 / rate_hz if rate_hz > 0 else 0.0
    frames: list[ReplayFrame] = []

    for i, decoded in enumerate(iter_packets(stream)):
        estimator_frame = {f: {"reading": decoded["readings"][f]} for f in FACE_NAMES}
        vector, health = safe_estimate(estimator_frame, dark_offset, gain)

        reference = None
        if references is not None and i < len(references):
            reference = np.asarray(references[i], dtype=float)

        err_deg: Optional[float] = None
        if vector is not None and reference is not None:
            err_deg = float(np.degrees(angular_error(vector, reference)))

        frames.append(
            ReplayFrame(
                index=i,
                seq=decoded["seq"],
                time_s=i * dt,
                readings=dict(decoded["readings"]),
                saturated=dict(decoded["saturated"]),
                sun_vector=vector,
                reference=reference,
                health=health,
                angular_error_deg=err_deg,
            )
        )
    return frames
