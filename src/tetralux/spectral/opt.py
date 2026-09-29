"""OPT4048 colour validation (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
cie.py handles the colour maths for one sensor. This file applies it to all four
OPT4048 sensors on the satellite and produces one verdict about the light.

Four sensors rather than one because a single colour sensor is a single point of
failure, and because averaging four readings suppresses noise. If one is shaded,
faulty, or returns garbage, the other three still give a usable answer. The
whole design here is built around that: each sensor is processed independently,
failures are recorded as NaN rather than allowed to crash the batch, and the
average is taken over whichever sensors actually worked.

The output is an OPTResult, which carries not just the verdict but everything
that went into it: the per-sensor values, the average, the reference, the
tolerance, the gap, and a plain-English guess at what kind of lamp this is.
Reporting "FAIL" alone would tell an operator nothing actionable; reporting
"FAIL, measured 2850 K against 5500 K, looks like tungsten" tells them a desk
lamp is lighting the prototype.

WHERE IT SITS IN THE FLOW
    spectral/cie.py  supplies the per-sensor colour maths
    pipeline.py      calls analyze_opt once per frame, stores the result
    dashboard        shows gate, CCT and light_source on the Live page

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tetralux.constants import CCT_REFERENCE_DAYLIGHT, CCT_TOLERANCE_DEFAULT
from tetralux.spectral.cie import cie_chromaticity, mccamy_cct, trust_gate

# Rough CCT bands -> light-source class (informational).
#
# A tuple of tuples: each inner one is (low, high, label). Written as tuples
# rather than lists because these bands are fixed reference data and a tuple
# cannot be modified after creation, which says so structurally.
#
# The bands are approximate and the classification is INFORMATIONAL: it never
# affects the trust gate, it only helps a person recognise what is in front of
# the sensor. The boundaries are conventional lighting-industry ranges, not
# sharp physical divisions, so a source near a boundary could reasonably be
# labelled either way.
_CLASSES = (
    (0.0, 3000.0, "Tungsten / incandescent"),
    (3000.0, 4500.0, "Warm white LED"),
    (4500.0, 6500.0, "Cool white LED / daylight"),
    (6500.0, 25000.0, "Fluorescent / HMI"),
)


@dataclass
class OPTResult:
    """Result of analysing the four OPT4048 sensors."""

    # Every field is required. This is a RESULT object: unlike Calibration, it
    # is never created empty and filled in later, so defaults would be
    # meaningless. It is built once, complete, by analyze_opt below.
    #
    # It carries the inputs as well as the answer, so a reading in a log file
    # can be understood months later without needing to know what the reference
    # and tolerance were configured to at the time.
    cct_values: list          # per-sensor CCT (K), nan where invalid
    cct_average: float        # mean of valid CCTs (K), nan if none
    reference: float          # reference CCT (K)
    tolerance: float          # tolerance (K)
    delta: float              # |avg - reference| (K), nan if none
    gate: str                 # "PASS" | "FAIL" | "ADVISORY"
    trusted: bool             # gate == "PASS"
    light_source: str         # classification from average CCT
    #
    # cct_values keeps all four even the failed ones, as NaN. Four NaNs point at
    # a wiring problem; one NaN points at one dead sensor. Discarding the
    # failures would erase that distinction.
    #
    # trusted duplicates information already in gate, deliberately. Callers that
    # only need a yes/no can test `if result.trusted:` without having to know
    # that "PASS" is the magic string, and if a fourth gate value is ever added,
    # they keep working.


# Internal helper (primer 12).
#
# PARAMETER
#   cct - an average colour temperature in kelvin, possibly NaN.
# RETURNS
#   a plain-English description of the likely light source.
def _classify(cct: float) -> str:
    # The NaN test again: NaN is unequal to itself (see cie.trust_gate). Said
    # plainly, because "Unknown" here means the sensors failed, not that the
    # light is exotic.
    if cct != cct:  # nan
        return "Unknown (no valid data)"
    # Unpacking three values per pass, since each _CLASSES entry is a triple.
    for lo, hi, label in _CLASSES:
        # Python allows chained comparisons: this reads exactly as it looks,
        # "lo is less than or equal to cct, which is less than hi". Note `<=` on
        # the low side and `<` on the high side, so the bands touch without
        # overlapping and every value falls in exactly one.
        if lo <= cct < hi:
            return label
    # Reached only if cct is outside every band, above 25000 K or negative.
    # mccamy_cct should already have turned those into NaN, so this is a
    # backstop rather than an expected path.
    return "Unknown"


# --- The main entry point ---
#
# PARAMETERS
#   opt_sensors - a list of four dicts, each {"X":..., "Y":..., "Z":...,
#                 "lux":...}, straight from SensorFrame.opt.
#   reference   - the daylight benchmark, defaulting to the project constant so
#                 the value lives in one place, while still being overridable
#                 for a test with a different light source.
#   tolerance   - how far from the reference still counts as daylight.
# RETURNS
#   one OPTResult summarising all four sensors.
def analyze_opt(
    opt_sensors: list,
    reference: float = CCT_REFERENCE_DAYLIGHT,
    tolerance: float = CCT_TOLERANCE_DEFAULT,
) -> OPTResult:
    """Compute per-sensor CCT, the average, and the trust gate."""
    ccts: list = []
    for o in opt_sensors:
        # try/except around EACH sensor individually (primer 11). This placement
        # is the whole fault-tolerance design: putting the try around the loop
        # instead would mean one bad sensor aborts the other three.
        try:
            # Formula 15 then the McCamy cubic, chained.
            x, y = cie_chromaticity(float(o["X"]), float(o["Y"]), float(o["Z"]))
            ccts.append(mccamy_cct(x, y))
        # Three named error types, each a real failure mode:
        #   ValueError - X+Y+Z was zero (dark) or the McCamy pole was hit.
        #   KeyError   - the dict has no "X" key, so the packet was malformed.
        #   TypeError  - a value was None or text, so float() could not convert.
        # Named rather than a bare `except:`, so a genuine bug in this file
        # still crashes loudly instead of being silently logged as a dead
        # sensor.
        except (ValueError, KeyError, TypeError):
            # NaN records "this sensor gave nothing usable" while keeping the
            # list four long, so position still identifies which sensor failed.
            ccts.append(float("nan"))

    # `c == c` is false only for NaN, so this keeps the valid readings.
    valid = [c for c in ccts if c == c]  # drop nan
    # Averaging must exclude NaN, because one NaN in a mean makes the whole mean
    # NaN. `if valid else` guards the empty case: np.mean of an empty list warns
    # and returns NaN anyway, so this states the intent explicitly instead.
    avg = float(np.mean(valid)) if valid else float("nan")
    gate = trust_gate(avg, reference, tolerance)
    # How far from daylight, as a positive number. Guarded so that a NaN average
    # produces a NaN delta rather than a misleading figure.
    delta = abs(avg - reference) if avg == avg else float("nan")

    # Build the result. Keyword arguments throughout: with eight fields,
    # positional order would be unreadable and one transposition would silently
    # swap reference with tolerance.
    return OPTResult(
        cct_values=ccts,
        cct_average=avg,
        reference=reference,
        tolerance=tolerance,
        delta=delta,
        gate=gate,
        # The comparison is evaluated here and stored as a plain True or False.
        trusted=(gate == "PASS"),
        light_source=_classify(avg),
    )
