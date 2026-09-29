"""Phase 3 - fault detection for the sun-direction estimate.

WHAT THIS FILE CONTRIBUTES
--------------------------
The estimator will produce an answer from almost any input. This file decides
whether that answer deserves to be believed.

An instrument that reports a confident number under conditions where its
assumptions have broken is worse than one that reports nothing, because a wrong
answer with no warning gets used. Three specific conditions break the sun
estimate, and each is detected here:

    LOW_SIGNAL    Too dark. The readings are noise, and dividing by their near
                  zero total gives a direction assembled from nothing.

    SATURATION    A face has hit the ADC ceiling. Its reading UNDERSTATES the
                  real light, because the sensor stopped counting, so the
                  estimate is pulled toward the unsaturated faces. Dangerous
                  precisely because it happens in BRIGHT conditions, where
                  everything looks healthy.

    MULTI_SOURCE  Two opposite faces are both well lit. One sun cannot do that,
                  so a second source is present, perhaps sunlight reflected off
                  the Earth. The single-source assumption underpinning the whole
                  method no longer holds.

The file also provides safe_estimate, which combines assessment and estimation
into a call that never raises: it returns either a vector or None, plus the
health report explaining why. That is what a ground station running unattended
for hours needs.

WHERE IT SITS IN THE FLOW
    estimator.py  supplies the formulas and the LowSignalError this catches
    pipeline.py   calls assess_frame per frame and stores the fault codes
    dashboard     shows the fault list and health indicator on the Live page

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# enum: for defining a fixed set of named options. See FaultCode below.
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
#
# The three axes of the cube. These pairs are the whole basis of the
# multi-source test: with one light source, at most ONE face of each pair can be
# lit, because they point in exactly opposite directions and no single source
# lies in both directions at once.
FACE_PAIRS: list[tuple[str, str]] = [("+x", "-x"), ("+y", "-y"), ("+z", "-z")]

# Defaults for the fault thresholds. `LOW_SIGNAL_THRESHOLD` is the divide-by-zero
# guard; callers that know their intensity scale can pass a larger value.
#
# The default is deliberately the bare mathematical minimum: it only catches
# signals so small the arithmetic breaks. A caller working in ADC counts, where
# a real measurement is in the hundreds, should pass something like 10.0, since
# a total of 3 counts is technically computable and physically meaningless.
LOW_SIGNAL_THRESHOLD: float = MIN_EPSILON
# 0.20 means: flag when opposite-face overlap reaches 20% of the total signal.
# Not zero, because noise and the cube's own light scatter always produce a
# little overlap; 20% is well above that floor and well below what a genuine
# second source produces.
OPPOSITION_THRESHOLD: float = 0.20


# An ENUM: a fixed set of named constants. `enum.Enum` is the base class.
#
# WHY NOT PLAIN STRINGS. Writing "low_signal" everywhere invites a typo, and
# `if fault == "lowsignal"` fails silently forever, always False, no error.
# FaultCode.LOW_SIGNAL is checked by Python: misspell it and you get an
# AttributeError immediately. The string value is kept for logging and display.
class FaultCode(enum.Enum):
    """Discrete fault categories a frame can carry."""

    LOW_SIGNAL = "low_signal"
    SATURATION = "saturation"
    MULTI_SOURCE = "multi_source"


# frozen=True makes instances IMMUTABLE: once created, no field can be changed.
# Attempting it raises an error rather than silently succeeding.
#
# That is right for a verdict. This is the assessment of one specific frame at
# one instant, and nothing downstream has any business editing it. Freezing it
# means a health report cannot be quietly "corrected" by a later stage into
# saying something the sensors never supported.
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
    #
    # `tuple[FaultCode, ...]` means "a tuple of any number of FaultCodes"; the
    # `...` is literal syntax for "however many". Tuples rather than lists
    # because a frozen dataclass holding a list would only be half frozen: the
    # list inside could still be modified.
    #
    # ok               - the single summary: no faults at all.
    # total_signal     - the sum of corrected readings, kept so a person can see
    #                    HOW dark "too dark" was.
    # dominant_face    - the brightest face, a quick sanity check: it should be
    #                    the one pointing nearest the light.
    # opposition_ratio - the multi-source number itself, reported even when
    #                    below the threshold so a slow drift toward trouble is
    #                    visible before it trips.
    # details          - an open dict for extra findings that do not warrant
    #                    their own field. default_factory=dict gives each
    #                    instance its own empty dict (primer 12).

    # PARAMETER
    #   code - the FaultCode to look for.
    # RETURNS
    #   True if this frame carries that fault.
    #
    # `in` tests membership in a sequence. A one-line method rather than making
    # callers write `FaultCode.LOW_SIGNAL in health.faults` everywhere: it reads
    # better as `health.has(FaultCode.LOW_SIGNAL)` and it means the internal
    # shape of `faults` could change without touching any call site.
    def has(self, code: FaultCode) -> bool:
        """Return True if ``code`` is among this frame's faults."""
        return code in self.faults


# The same scalar-or-dict resolver as in estimator.py and simulator.py. See the
# note there: fault detection is deliberately able to stand alone.
def _resolve(param: "float | Mapping[str, float]", face: str, default: float) -> float:
    """Resolve a scalar-or-per-face calibration parameter to a float."""
    if isinstance(param, Mapping):
        return float(param.get(face, default))
    return float(param)


# --- Calibrate a whole frame ---
#
# PARAMETERS
#   face_readings - the simulator-style nested dict, {"+x": {"reading": ...}}.
#   dark_offset   - scalar or per-face dark offsets.
#   gain          - scalar or per-face gains.
# RETURNS
#   a flat dict of corrected readings, floored at zero.
#
# This mirrors calibration.corrected_readings but takes the nested reading shape
# and loose parameters rather than a Calibration object, so the fault code can
# be used on raw simulator output with no calibration file in hand.
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
        # Floor at zero for the same reason as in calibration.py: subtracting
        # the dark offset can push a shadowed face slightly negative, and
        # negative light does not exist.
        corrected[face] = max(0.0, r_i)
    return corrected


# --- The multi-source test ---
#
# PARAMETER
#   corrected - corrected readings per face, from corrected_frame above.
# RETURNS
#   a ratio from 0 to 1. Near 0 means one clean light source; higher means
#   opposite faces are both lit, so something else is illuminating the cube.
#
# HOW IT WORKS. For each opposite pair, min() takes the SMALLER of the two
# readings. That smaller value is light which cannot be explained by a single
# source: whichever way the sun is, it can only light one of the two, so
# whatever the darker one reads must have come from somewhere else. Summing
# those three minimums gives the total unexplained light.
#
# The factor of 2 scales the result onto 0 to 1. At the extreme, all six faces
# equally lit, each pair's minimum equals each reading, so overlap is half the
# total and 2 * (total/2) / total = 1. Without the 2 the maximum would be 0.5,
# and a threshold on it would be harder to reason about.
def opposition_ratio(corrected: Mapping[str, float]) -> float:
    """Multi-source indicator in ``[0, 1]`` from corrected readings."""
    # A generator expression inside sum(): produce values one at a time and add
    # them, without building an intermediate list.
    total = float(sum(corrected[f] for f in FACE_NAMES))
    # In darkness the ratio is undefined, since there is no light to attribute
    # to any source. Returning 0.0 rather than raising avoids reporting a
    # multi-source fault on a frame whose actual problem is that it is dark;
    # the low-signal check handles that case, and one clear fault is more useful
    # than two overlapping ones.
    if total < MIN_EPSILON:
        return 0.0
    overlap = sum(min(corrected[a], corrected[b]) for a, b in FACE_PAIRS)
    return float(2.0 * overlap / total)


# --- Which faces hit the ceiling ---
#
# PARAMETER
#   face_readings - the nested dict; each face carries a "saturated" flag set by
#                   the simulator or by the telemetry decoder.
# RETURNS
#   a tuple of face names, in canonical order.
#
# `.get("saturated", False)` rather than ["saturated"] so a reading dict without
# the key is treated as not saturated instead of raising KeyError. A tuple
# rather than a list because this goes into the frozen FrameHealth.
def saturated_face_names(
    face_readings: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    """Names of faces the simulator flagged as saturated, in canonical order."""
    return tuple(f for f in FACE_NAMES if bool(face_readings[f].get("saturated", False)))


# --- The full assessment ---
#
# PARAMETERS
#   face_readings        - the nested per-face dict.
#   dark_offset, gain    - calibration, scalar or per-face.
#   low_signal_threshold - below this total, flag LOW_SIGNAL.
#   opposition_threshold - at or above this ratio, flag MULTI_SOURCE.
# RETURNS
#   one FrameHealth verdict.
#
# NOTE THE BARE `*` IN THE PARAMETER LIST. Everything after it is
# KEYWORD-ONLY: it must be passed by name, so `assess_frame(readings, 0, 1,
# 10.0)` is an error and `assess_frame(readings, 0, 1,
# low_signal_threshold=10.0)` is required. With two similar float thresholds
# side by side, positional passing would make them trivially easy to swap, and
# a swapped pair here would produce a silently wrong health verdict rather than
# a crash.
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
        # max() with a `key` function: instead of comparing the face NAMES,
        # which would return "-z" alphabetically, it compares what the key
        # function returns for each. A lambda is a small unnamed function, so
        # `lambda f: corrected[f]` means "for face f, compare its reading".
        #
        # Guarded by the total check because "the brightest face" is meaningless
        # when everything is dark; it would return whichever face happened to
        # carry the most noise.
        dominant = max(FACE_NAMES, key=lambda f: corrected[f])

    ratio = opposition_ratio(corrected)

    # Collect every fault rather than stopping at the first. A frame can be both
    # saturated and multi-source, and knowing both matters: reporting only the
    # first found would hide the second and send an operator after half the
    # problem.
    faults: list[FaultCode] = []
    if total < low_signal_threshold:
        faults.append(FaultCode.LOW_SIGNAL)
    # A non-empty tuple is truthy in Python, so this reads as "if any face was
    # saturated".
    if saturated:
        faults.append(FaultCode.SATURATION)
    if ratio >= opposition_threshold:
        faults.append(FaultCode.MULTI_SOURCE)

    # An extra detail worth surfacing: the BRIGHTEST face being the saturated
    # one is much worse than a side face clipping. The dominant face carries
    # most of the directional information, so when it is the one whose reading
    # has stopped being truthful, the estimate is badly compromised rather than
    # slightly biased.
    dominant_saturated = dominant is not None and dominant in saturated

    return FrameHealth(
        # `not faults` is True when the list is empty. Empty means healthy.
        ok=not faults,
        faults=tuple(faults),
        total_signal=total,
        dominant_face=dominant,
        saturated_faces=saturated,
        opposition_ratio=ratio,
        details={"dominant_saturated": dominant_saturated},
    )


# --- Estimation that cannot crash ---
#
# PARAMETERS
#   face_readings     - the nested per-face dict.
#   dark_offset, gain - calibration.
#   **assess_kwargs   - see below.
# RETURNS
#   a TUPLE of (vector or None, FrameHealth). Unpack with
#   `vector, health = safe_estimate(...)`.
#
# `**assess_kwargs` collects any extra KEYWORD arguments into a dict, which is
# then unpacked back out with `**` at the call to assess_frame. That lets a
# caller pass low_signal_threshold straight through without this function having
# to name and forward each threshold itself, so adding a fourth threshold to
# assess_frame later needs no change here.
#
# WHY IT EXISTS. estimate_sun_vector raises LowSignalError in darkness, which is
# correct for a mathematical function: refuse rather than invent. But a ground
# station receiving frames continuously must not stop when a cloud passes. This
# wrapper converts that exception into a None result plus an explanation, so the
# caller handles darkness with an `if` rather than a try/except at every site.
def safe_estimate(
    face_readings: Mapping[str, Mapping[str, object]],
    dark_offset: "float | Mapping[str, float]" = 0.0,
    gain: "float | Mapping[str, float]" = 1.0,
    **assess_kwargs: object,
) -> tuple[Optional[np.ndarray], FrameHealth]:
    """Assess a frame and estimate its sun vector, never raising on bad input."""
    health = assess_frame(face_readings, dark_offset, gain, **assess_kwargs)  # type: ignore[arg-type]
    # Fast path: if the frame is already known to be too dark, do not bother
    # running the estimator just to catch the exception it must raise.
    if health.has(FaultCode.LOW_SIGNAL):
        return None, health
    try:
        vector = estimate_sun_vector(face_readings, dark_offset, gain)
    # The second net. Total signal can pass the threshold while the DIRECTION
    # still cancels to nothing, when all six faces are equally lit in diffuse
    # light. assess_frame cannot see that, but formula 4 does. Both checks are
    # needed; neither subsumes the other.
    except LowSignalError:
        return None, health
    # Health is returned in every case, including success, so the caller always
    # has the saturation and multi-source findings even when a vector was
    # produced. A usable answer can still be a compromised one.
    return vector, health
