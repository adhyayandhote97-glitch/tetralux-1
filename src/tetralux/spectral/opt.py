"""OPT4048 colour validation (Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tetralux.constants import CCT_REFERENCE_DAYLIGHT, CCT_TOLERANCE_DEFAULT
from tetralux.spectral.cie import cie_chromaticity, mccamy_cct, trust_gate

# Rough CCT bands -> light-source class (informational).
_CLASSES = (
    (0.0, 3000.0, "Tungsten / incandescent"),
    (3000.0, 4500.0, "Warm white LED"),
    (4500.0, 6500.0, "Cool white LED / daylight"),
    (6500.0, 25000.0, "Fluorescent / HMI"),
)


@dataclass
class OPTResult:
    """Result of analysing the four OPT4048 sensors."""

    cct_values: list          # per-sensor CCT (K), nan where invalid
    cct_average: float        # mean of valid CCTs (K), nan if none
    reference: float          # reference CCT (K)
    tolerance: float          # tolerance (K)
    delta: float              # |avg - reference| (K), nan if none
    gate: str                 # "PASS" | "FAIL" | "ADVISORY"
    trusted: bool             # gate == "PASS"
    light_source: str         # classification from average CCT


def _classify(cct: float) -> str:
    if cct != cct:  # nan
        return "Unknown (no valid data)"
    for lo, hi, label in _CLASSES:
        if lo <= cct < hi:
            return label
    return "Unknown"


def analyze_opt(
    opt_sensors: list,
    reference: float = CCT_REFERENCE_DAYLIGHT,
    tolerance: float = CCT_TOLERANCE_DEFAULT,
) -> OPTResult:
    """Compute per-sensor CCT, the average, and the trust gate."""
    ccts: list = []
    for o in opt_sensors:
        try:
            x, y = cie_chromaticity(float(o["X"]), float(o["Y"]), float(o["Z"]))
            ccts.append(mccamy_cct(x, y))
        except (ValueError, KeyError, TypeError):
            ccts.append(float("nan"))

    valid = [c for c in ccts if c == c]  # drop nan
    avg = float(np.mean(valid)) if valid else float("nan")
    gate = trust_gate(avg, reference, tolerance)
    delta = abs(avg - reference) if avg == avg else float("nan")

    return OPTResult(
        cct_values=ccts,
        cct_average=avg,
        reference=reference,
        tolerance=tolerance,
        delta=delta,
        gate=gate,
        trusted=(gate == "PASS"),
        light_source=_classify(avg),
    )
