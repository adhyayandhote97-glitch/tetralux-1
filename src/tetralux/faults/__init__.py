"""Fault detection: low signal, saturation, and multi-source ambiguity."""

from tetralux.faults.detector import (
    FaultCode,
    FrameHealth,
    assess_frame,
    corrected_frame,
    opposition_ratio,
    safe_estimate,
    saturated_face_names,
)

__all__ = [
    "FaultCode",
    "FrameHealth",
    "assess_frame",
    "safe_estimate",
    "corrected_frame",
    "opposition_ratio",
    "saturated_face_names",
]
