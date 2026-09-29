"""Validation metrics (formulas 11-14 from docs/architecture.md).

WHAT THIS FILE CONTRIBUTES
--------------------------
The estimator always produces an answer. This file asks how good that answer is.

An estimate with no error figure attached is not a measurement, it is a guess
with a decimal point. These four small functions turn a stream of estimates into
statements about accuracy:

    Formula 11  angular_error    how far off is this one estimate?
    Formula 12  repeatability    how much does the answer jitter?
    Formula 13  bias             does it lean consistently one way?
    Formula 14  temp_drift_rate  are the sensors heating up?

BIAS AND REPEATABILITY ARE THE INTERESTING PAIR, because together they say what
KIND of problem you have. Bias is the average error, repeatability is the spread
around it. Large bias with small spread means a steady offset: something is
systematically wrong, most likely a miscalibrated face, and it is fixable. Small
bias with large spread means noise: the answer is right on average but any
single reading is unreliable, so average more frames. Reporting only one number
would hide that distinction, and the two problems have opposite fixes.

Everything here is stateless: pass numbers in, get a number back, nothing
remembered between calls. Keeping history is rolling.py's job, which is why
these are trivially testable.

WHERE IT SITS IN THE FLOW
    validation/rolling.py  calls these over a sliding window of recent frames
    pipeline.py            fills angular_error_deg / bias_deg / repeatability_deg
    thermal/analysis.py    uses formula 14 for drift detection

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


# --- Formula 11: the angle between two directions ---
#
# PARAMETERS
#   s_hat     - the estimated sun vector, a unit vector from the estimator.
#   s_hat_ref - the reference (true) direction, also unit length. In Virtual
#               mode this comes from the azimuth/elevation sliders, so the truth
#               is known exactly and the error can be measured.
# RETURNS
#   the angle between them, IN RADIANS. Note the unit: everything displayed to a
#   person is in degrees, and the conversion happens in rolling.py, not here.
#
# THE MATHS. For two unit vectors, the dot product equals the cosine of the
# angle between them. So arccos of the dot product recovers the angle: identical
# directions give 1, arccos(1) = 0 radians, no error. Perpendicular gives 0,
# arccos(0) = 90 degrees. Opposite gives -1, arccos(-1) = 180 degrees.
#
# WHY AN ANGLE RATHER THAN A DISTANCE. A sun sensor measures direction and
# nothing else; it cannot know how far away the sun is. Subtracting two vectors
# would produce a length, implying a distance error that this instrument is
# incapable of measuring. The angle is the only honest error measure.
def angular_error(s_hat: np.ndarray, s_hat_ref: np.ndarray) -> float:
    """Formula 11 - angular error (radians) between estimate and reference."""
    # asarray accepts plain lists as well as numpy arrays, so callers do not
    # have to convert first.
    a = np.asarray(s_hat, dtype=float)
    b = np.asarray(s_hat_ref, dtype=float)
    # np.dot multiplies matching components and sums them:
    # a.x*b.x + a.y*b.y + a.z*b.z.
    dot = float(np.dot(a, b))
    # CLAMP, and it is essential rather than defensive. Mathematically the dot
    # product of two unit vectors is always within [-1, 1], but floating-point
    # arithmetic can land on 1.0000000000000002, and arccos of anything past 1
    # is NaN. A single NaN then contaminates the mean and standard deviation of
    # the whole error window, destroying every metric downstream from one
    # rounding artefact.
    dot = max(-1.0, min(1.0, dot))
    return float(np.arccos(dot))


# --- Formula 12: how much the answer jitters ---
#
# PARAMETER
#   theta_error_series - a sequence of past angular errors, in whatever unit
#                        they were collected in. rolling.py passes degrees.
# RETURNS
#   the standard deviation of that series, in the same unit as the input.
#
# Standard deviation measures spread: how far a typical value sits from the
# average. Near zero means the estimate lands in the same place every time,
# which is what "repeatable" means. Note that repeatable is not the same as
# accurate: an estimate consistently 5 degrees off is perfectly repeatable and
# entirely wrong. That is precisely why bias is reported alongside.
def repeatability(theta_error_series: Sequence[float]) -> float:
    """Formula 12 - repeatability: standard deviation of the angular-error series."""
    # np.std does the whole calculation. float() converts numpy's float64 to a
    # plain Python float, which matters because record.py has to write these as
    # JSON and numpy types are not JSON-serializable.
    return float(np.std(np.asarray(theta_error_series, dtype=float)))


# --- Formula 13: the systematic lean ---
#
# PARAMETER
#   theta_error_series - the same sequence of past angular errors.
# RETURNS
#   the mean (ordinary average) of the series.
#
# If errors were purely random noise this would hover near zero, since positive
# and negative deviations cancel. A mean that settles at, say, 3 degrees means
# the estimate is consistently off in one direction, and consistency implies a
# cause: a wrong gain on one face, a photodiode mounted slightly crooked, a
# stale calibration. Bias is the number that says "go and fix something"
# rather than "average more frames".
def bias(theta_error_series: Sequence[float]) -> float:
    """Formula 13 - bias: mean of the angular-error series (systematic offset)."""
    return float(np.mean(np.asarray(theta_error_series, dtype=float)))


# --- Formula 14: how fast the temperature is changing ---
#
# PARAMETERS
#   T_now  - the current temperature reading, degrees Celsius.
#   T_prev - an earlier reading from the same sensor.
#   dt     - the time between them. THE UNIT OF dt SETS THE UNIT OF THE ANSWER:
#            pass seconds and you get degrees per second, pass minutes and you
#            get degrees per minute. thermal/analysis.py passes minutes, so the
#            result can be compared against DRIFT_THRESHOLD_C_PER_MIN.
# RETURNS
#   the rate of change. Positive means warming, negative means cooling.
#
# WHY TEMPERATURE MATTERS TO A LIGHT SENSOR. A photodiode's sensitivity shifts
# as it heats, so a calibration measured at 20 degrees is progressively less
# valid at 35. A steadily rising temperature therefore means the readings
# themselves are drifting and the estimate is quietly degrading. Detecting that
# lets the system flag its own results as less trustworthy instead of reporting
# a drifting number with unchanged confidence.
def temp_drift_rate(T_now: float, T_prev: float, dt: float) -> float:
    """Formula 14 - temperature drift rate: ``(T_now - T_prev) / dt``."""
    # Division by zero would be undefined, and a dt of zero means two readings
    # carry the same timestamp, which is a bug in the caller rather than a
    # physical condition. ValueError says "you called this wrong".
    if dt == 0:
        raise ValueError("dt must be non-zero")
    # Rate of change: the amount it changed, divided by the time it took.
    return (T_now - T_prev) / dt
