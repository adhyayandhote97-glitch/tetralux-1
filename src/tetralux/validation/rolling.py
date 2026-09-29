"""Rolling and burst validation metrics (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
metrics.py computes accuracy figures from a list of errors but keeps no history.
This file supplies the history.

Bias and repeatability are meaningless for a single frame: an average of one
number is that number, and its spread is zero. They only say something once
there is a run of estimates to compare. So something has to remember recent
frames, and that is what lives here.

Two ways of gathering that history, for two different situations:

    RollingValidator - for a LIVE STREAM. Frames arrive continuously and
                       forever, so it keeps only the most recent 60 and lets
                       older ones fall off the end. Metrics stay current: a
                       calibration fixed two minutes ago should stop affecting
                       today's numbers.

    burst_metrics    - for a DELIBERATE TEST. Hold the light fixed, take 30
                       readings on purpose, report how they scattered. This is
                       the controlled bench measurement, not the live monitor.

WHY A FIXED-SIZE WINDOW. Averaging over all frames since startup would mean an
hour-old problem still dragging on the average an hour later, and a memory
footprint that grows without limit during a long session. Sixty frames at about
10 Hz is roughly the last six seconds: recent enough to reflect current
conditions, long enough for a standard deviation to mean something.

WHERE IT SITS IN THE FLOW
    pipeline.py         holds a RollingValidator in its PipelineContext
    dashboard/state.py  creates one per streaming context
    metrics.py          supplies the actual formulas this file feeds

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# deque ("deck") is a list optimised for adding and removing at both ends, and
# crucially it can be given a maximum length. See its use below.
from collections import deque
# Callable is a type hint for "a function passed as an argument".
from typing import Callable, Optional

import numpy as np

from tetralux.constants import MIN_EPSILON, ROLLING_WINDOW_SIZE
from tetralux.validation.metrics import angular_error, bias, repeatability


# Internal helper (primer 12).
#
# PARAMETER
#   v - any 3D vector.
# RETURNS
#   the same direction scaled to length 1.
#
# WHY IT IS NEEDED. angular_error's dot-product maths is only valid for unit
# vectors: for anything longer the dot product exceeds 1, gets clamped, and
# returns a confidently wrong 0-degree error. So every reference vector entering
# this file is normalized first, once, here.
#
# This duplicates estimator.sun_vector's arithmetic but not its meaning: that
# one raises LowSignalError, a normal dark-sky condition, while a zero-length
# REFERENCE is a caller bug. Different error type, different response, so a
# separate function is right rather than sharing one.
def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    norm = float(np.linalg.norm(v))
    # A zero-length vector has no direction to preserve, so there is nothing to
    # scale. ValueError, not LowSignalError: nobody can supply a meaningful
    # reference of length zero, so this is a mistake to fix, not a condition to
    # handle.
    if norm < MIN_EPSILON:
        raise ValueError("reference vector has near-zero length")
    return v / norm


# A CLASS rather than a function (primer 12), because this needs MEMORY. A
# function forgets everything when it returns; an object keeps its data between
# calls, and remembering the last 60 errors is the entire point.
class RollingValidator:
    """Streaming angular-error window against a fixed reference direction."""

    # __init__ is the constructor: it runs automatically when someone writes
    # RollingValidator(reference=...). Its job is to set up starting state.
    #
    # PARAMETERS
    #   self      - the object being built. Never passed by the caller.
    #   reference - the true sun direction to score estimates against.
    #   window    - how many recent errors to keep. Defaults to
    #               ROLLING_WINDOW_SIZE (60) from constants.py, so the default
    #               is defined in one place project-wide.
    # RETURNS
    #   None. A constructor sets up the object rather than producing a value.
    def __init__(self, reference: np.ndarray, window: int = ROLLING_WINDOW_SIZE) -> None:
        # Anything assigned to self.something is stored ON THE OBJECT and
        # survives until the next call. A plain local variable would vanish when
        # __init__ returned.
        #
        # The leading underscore marks both as internal: outside code should use
        # the methods below, not reach in and edit these directly.
        self._ref = _unit(reference)
        # THIS IS WHY deque IS USED. maxlen=window makes it self-limiting: at 60
        # items, appending a 61st automatically drops the oldest from the front.
        # No length check, no manual trimming, no way to forget the trimming and
        # leak memory during an eight-hour session. The data structure enforces
        # the window by construction.
        self._errors: deque = deque(maxlen=window)

    # The method called once per incoming frame.
    #
    # PARAMETERS
    #   sun_vector - this frame's estimate, or None if the frame was too dark to
    #                resolve a direction. Optional[np.ndarray] is the hint for
    #                "an array or None".
    # RETURNS
    #   a dict of three metrics, in DEGREES, ready for the record and the
    #   dashboard.
    def update(self, sun_vector: Optional[np.ndarray]) -> dict:
        """Add an estimate and return angular error + rolling bias/repeatability."""
        # A dark frame produced no estimate, so there is no error to measure.
        #
        # Note what this does NOT do: it does not append anything to the window.
        # Recording a zero error for a frame that made no measurement would be a
        # lie that improves the statistics, making the system look more accurate
        # the darker it gets. Returning three Nones states plainly that this
        # frame contributed nothing.
        if sun_vector is None:
            return {"angular_error_deg": None, "bias_deg": None, "repeatability_deg": None}
        # Formula 11 returns radians; np.degrees converts. Everything stored in
        # the window from here on is in degrees, so the bias and repeatability
        # computed from it come out in degrees too, with no further conversion.
        err = float(np.degrees(angular_error(sun_vector, self._ref)))
        # Add to the window. If it is already full, the oldest silently drops.
        self._errors.append(err)
        return {
            # This frame's own error.
            "angular_error_deg": err,
            # Formula 13 over the whole window: the systematic lean.
            "bias_deg": float(bias(self._errors)),
            # Formula 12 over the whole window: the jitter.
            "repeatability_deg": float(repeatability(self._errors)),
        }

    # PARAMETER
    #   reference - a new true direction.
    # RETURNS
    #   None; it changes the object's state.
    #
    # Used when the Virtual-mode sliders move: the truth has changed.
    #
    # THE .clear() IS THE POINT OF THIS METHOD. Errors already in the window
    # were measured against the OLD reference. Keeping them would mix errors
    # from two different truths into one average, producing a bias figure that
    # describes nothing real. Changing the reference invalidates the history, so
    # the history is discarded.
    def set_reference(self, reference: np.ndarray) -> None:
        self._ref = _unit(reference)
        self._errors.clear()

    # Throw away the history but keep the same reference. Used when starting a
    # fresh recording session, so results from a previous run do not bleed in.
    def reset(self) -> None:
        self._errors.clear()


# --- The deliberate bench measurement ---
#
# PARAMETERS
#   sample_fn - A FUNCTION, passed as an argument. Callable[[], Optional[...]]
#               is the hint: the empty [] means it takes no arguments, and it
#               returns either a vector or None.
#
#               Functions are ordinary values in Python and can be handed around
#               like numbers. That is what makes this work with any source: pass
#               a function that reads the real hardware and this measures the
#               prototype; pass one that runs the simulator and it measures the
#               model. Neither case needs a change here, because this function
#               does not know or care where the estimates come from. Note it is
#               `sample_fn` with no brackets when passed in, and `sample_fn()`
#               with brackets below where it is actually called.
#   reference - the true direction the light is held at during the test.
#   n         - how many samples to take. Default 30.
# RETURNS
#   a dict with bias_deg, repeatability_deg, and n (how many samples actually
#   contributed).
def burst_metrics(
    sample_fn: Callable[[], Optional[np.ndarray]],
    reference: np.ndarray,
    n: int = 30,
) -> dict:
    """Bias/repeatability from ``n`` fresh estimates at a fixed direction."""
    ref = _unit(reference)
    errors = []
    # range(n) counts 0, 1, 2 ... n-1. The underscore as a loop variable is
    # convention for "the counter is not used"; only the number of passes
    # matters here, not which pass this is.
    for _ in range(n):
        v = sample_fn()
        # `continue` skips the rest of THIS pass and moves to the next one, so a
        # dark sample is discarded rather than counted. Same honesty rule as
        # update() above: a failed measurement is not a zero-error measurement.
        if v is None:
            continue
        errors.append(float(np.degrees(angular_error(v, ref))))
    # `if not errors` is Python's idiom for "if the list is empty". Every sample
    # failed, meaning the light was off or the sensor is dead.
    #
    # NaN ("not a number") is returned rather than 0.0 because zero would read
    # as "perfectly accurate", the exact opposite of the truth. NaN means "no
    # answer exists", and record.py converts it to JSON null on the way out.
    if not errors:
        return {"bias_deg": float("nan"), "repeatability_deg": float("nan"), "n": 0}
    return {
        "bias_deg": float(bias(errors)),
        "repeatability_deg": float(repeatability(errors)),
        # len(errors) may be less than n if some samples were skipped. Reporting
        # the real count matters: bias over 3 usable samples out of 30 deserves
        # far less confidence than bias over all 30, and hiding that would
        # present a shaky result as a solid one.
        "n": len(errors),
    }
