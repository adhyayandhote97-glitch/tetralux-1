"""Phase 3: fault detection.

Sensor/estimation faults (low-signal, saturation, multi-source ambiguity) live
in :mod:`tetralux.faults.detector`; packet-integrity primitives
(corrupted/truncated telemetry) live in :mod:`tetralux.faults.packets`.
"""

from tetralux.faults.detector import (
    FaultCode,
    FrameHealth,
    assess_frame,
    corrected_frame,
    opposition_ratio,
    safe_estimate,
    saturated_face_names,
)
from tetralux.faults.packets import (
    PacketFault,
    checksum8,
    is_truncated,
    validate_packet,
    verify_checksum,
)

__all__ = [
    # detector
    "FaultCode",
    "FrameHealth",
    "assess_frame",
    "safe_estimate",
    "corrected_frame",
    "opposition_ratio",
    "saturated_face_names",
    # packets
    "PacketFault",
    "checksum8",
    "verify_checksum",
    "is_truncated",
    "validate_packet",
]
