"""Fault detection: low signal, saturation, and multi-source ambiguity.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `faults/` as a package and re-exports everything in detector.py.

This subpackage decides whether an estimate deserves to be believed. The
estimator produces an answer from almost any input, and three specific
conditions make that answer untrustworthy:

    low signal    too dark; the readings are noise
    saturation    a face hit the ADC ceiling and its reading now understates
                  the truth, which happens in BRIGHT conditions where everything
                  otherwise looks healthy
    multi-source  opposite faces both lit, so more than one light source is
                  present and the single-source assumption has broken

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
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

# The two types first, then the two main entry points, then the helpers those
# are built from. Ordered by how likely a caller is to need them.
__all__ = [
    "FaultCode",             # the enum of fault categories
    "FrameHealth",           # the frozen verdict for one frame
    "assess_frame",          # the full assessment
    "safe_estimate",         # assess and estimate, never raising
    "corrected_frame",
    "opposition_ratio",
    "saturated_face_names",
]
