"""The fully-processed ground-station record (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
If frames.py defines what goes IN, this file defines what comes OUT. A
GroundStationRecord is everything the system knows about one instant: the raw
sensor numbers, the calibrated versions, the estimated sun direction, the
radiation-pressure forces, the accuracy metrics, the fault flags, temperatures
and colour. Roughly forty fields, one snapshot.

Every consumer reads this same object. The dashboard displays it, the local log
writes it to disk, Firebase uploads it, the CSV export flattens it. That is the
point of having one record type: adding a new measurement means adding a field
here, and every one of those consumers can see it without being rewritten.

The other job of this file is `to_dict`, which converts a record into something
that can be safely written as JSON. That conversion is less trivial than it
sounds, and the `_clean` function below explains why.

WHERE IT SITS IN THE FLOW
    pipeline.py         builds one of these per frame
    dashboard/state.py  holds the latest one and a rolling buffer of past ones
    store/local_log.py  writes record.to_dict() as one line of JSON per packet

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# math: standard library maths. Used here only for isnan / isinf.
import math
# asdict: turns a dataclass into a plain dict of its fields.
# dataclass: the decorator that writes the constructor (primer section 12).
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np


# Internal helper (leading underscore, primer 12). "Recursively" means this
# function calls ITSELF: a record contains dicts which contain lists which
# contain numbers, so it walks down through that nesting one layer at a time.
#
# PARAMETER
#   value - anything at all: a dict, a list, a number, a numpy array, a string.
#           It starts as the whole record and, through the recursion, ends up
#           being called on every individual value buried inside it.
# RETURNS
#   the same data with two problems removed, described below.
#
# WHY THIS EXISTS. JSON is the text format used to write logs and send data to
# Firebase, and two kinds of value in a record cannot be written as JSON:
#
#   1. NaN and infinity. NaN is "not a number", what you get from 0/0 or the
#      average of an empty list. Python is happy to hold it, but JSON has no way
#      to spell it. Writing it produces a file that other tools refuse to read.
#      Converting it to None (which becomes JSON `null`) keeps the file valid
#      and, more importantly, is honest: null says "no value here", which is
#      exactly what NaN meant.
#   2. NumPy numbers. The estimator works in numpy, so a value that looks like a
#      plain number may really be np.float64. The JSON writer does not recognise
#      those types and raises TypeError. So they are converted to ordinary
#      Python int and float first.
#
# Getting this wrong does not fail loudly at the calculation; it fails much
# later when a log line will not save. Hence one function that scrubs
# everything, in one place, applied to the whole record before it is written.
def _clean(value):
    """Recursively make a value JSON-safe: NaN/inf -> None, numpy -> python."""
    # isinstance(x, T) asks "is x of type T?". Each check below handles one
    # container or one number type. Order matters: containers first, because
    # their CONTENTS still need cleaning.

    # A dict: clean every value inside it, keeping the keys. This is the
    # recursion, _clean calling _clean, and it is what reaches nested data.
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    # A list or tuple: clean every element. Tuples come back as lists because
    # JSON has only one kind of sequence.
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    # A numpy whole number, such as np.int64: convert to a plain Python int.
    if isinstance(value, (np.integer,)):
        return int(value)
    # A numpy decimal: convert to a plain float. Note this does NOT return yet.
    # It reassigns `value` and falls through to the next check, so a numpy NaN
    # gets both fixes: first the type, then the NaN test below.
    if isinstance(value, (np.floating,)):
        value = float(value)
    # Now an ordinary float, possibly one that just arrived from numpy above.
    # If it is NaN or infinite it becomes None; otherwise it passes through.
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    # A numpy array, such as the 3-element sun vector. .tolist() turns it into
    # a plain Python list, which is then cleaned element by element.
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    # Anything else (str, int, bool, None) is already JSON-safe. This is the
    # BASE CASE: the point where the recursion stops instead of calling itself
    # again. Without a base case a recursive function never ends.
    return value


@dataclass
class GroundStationRecord:
    """One processed frame - the complete state for one sample."""

    # None of these fields has a default, so every one must be supplied when a
    # record is built. pipeline.py is the only place that builds them.
    #
    # The blank-line groups below are the processing stages in order: raw in,
    # calibrated, estimated, physics, validation, faults, context. Reading the
    # field list top to bottom is a summary of what the pipeline does.

    seq: int
    timestamp_ms: int
    received_at: str            # ISO-8601
    source: str                 # "real" | "virtual"
    # received_at is a string here, not a datetime as it was on SensorFrame,
    # because a record is built to be written out. ISO-8601 is the standard
    # text form, "2026-09-05T14:30:00+00:00": sorts correctly as plain text and
    # is unambiguous across time zones.

    # Raw sensors: straight off the hardware, uncalibrated, kept so any later
    # number can always be traced back to what was actually measured.
    photodiodes: dict           # face -> ADC counts
    lux: dict                   # face -> lx
    magnetometer: dict          # {"x","y","z"} raw int

    # Calibrated: raw readings converted into usable quantities. Each of these
    # is one formula from the locked math spec.
    corrected: dict             # face -> R_i (calibrated counts)
    cosine_proxy: dict          # face -> cos(theta_i), dimensionless
    irradiance: dict            # face -> W/m^2
    weights: dict               # face -> w_i, dimensionless (sum = 1)
    # corrected     = formula 1, raw minus dark offset, times gain. Removes each
    #                 photodiode's individual quirks so six sensors compare
    #                 fairly.
    # cosine_proxy  = formula 5, how directly light hits that face. 1.0 means
    #                 straight on, 0.0 means edge-on.
    # irradiance    = physical light power per square metre, the input to the
    #                 radiation-pressure calculation.
    # weights       = formula 2, each face's share of the total. They sum to
    #                 exactly 1, which is what "normalized" means and what
    #                 "dimensionless" refers to: a ratio, so no unit.

    # Estimate: the actual answer this whole project exists to produce.
    sun_vector: Optional[list]  # [x, y, z] unit, or None (low signal)
    azimuth_deg: Optional[float]
    elevation_deg: Optional[float]
    confidence: float           # dimensionless 0-1
    # The three Optional fields are None together, in darkness, when no
    # direction can be resolved. None here is a real statement: "not measured",
    # which is different from [0,0,0], a vector that would falsely claim one.
    # azimuth is the compass-style angle around the horizontal, elevation is
    # the angle up from horizontal: the same vector expressed as two angles,
    # which is easier for a person to read.

    # Solar radiation pressure (formulas 6-10).
    #
    # Sunlight carries momentum, so it pushes on the satellite. The push is
    # tiny, around a hundred-millionth of a newton, but in orbit there is
    # nothing to damp it and over months it measurably moves the spacecraft.
    srp_forces: dict            # face -> force (N)
    srp_net: list               # [Fx, Fy, Fz] (N)
    srp_magnitude_n: float      # |F_net| (N)
    srp_azimuth_deg: Optional[float]
    srp_elevation_deg: Optional[float]
    # Per-face forces, then their vector sum, then that sum's length, then its
    # direction as angles. The SRP angles should closely track the sun angles
    # above, since light pushes along the direction it travels; a test asserts
    # exactly that, which makes the two independent calculations check
    # each other.

    # Validation: how much to believe the estimate. Optional because they need a
    # known truth direction or a history of frames, neither of which exists for
    # a single real-hardware frame with nothing to compare against.
    angular_error_deg: Optional[float]
    bias_deg: Optional[float]
    repeatability_deg: Optional[float]
    # angular_error  - degrees between the estimate and the known truth. Only
    #                  computable when the truth is known, so in Virtual mode.
    # bias           - the average error over the window. A consistent lean in
    #                  one direction means a systematic problem, such as a
    #                  miscalibrated face, not random noise.
    # repeatability  - how much the estimate jitters frame to frame. Small
    #                  bias with large repeatability means noise; the reverse
    #                  means a steady offset. Different problems, different
    #                  fixes, so both are reported.

    # Faults / integrity: reasons not to trust this frame.
    saturated_faces: list
    saturation_flag: bool
    checksum: int               # transmitted 8-bit checksum
    checksum_ok: bool
    faults: list                # fault-code strings
    health_ok: bool
    opposition_ratio: float     # multi-source indicator, dimensionless
    # checksum_ok is False when the recomputed checksum disagrees with the one
    # transmitted, meaning the data was corrupted in flight.
    # faults holds short text codes such as "low_signal" or "saturation";
    # health_ok is the single summary a person can glance at.
    # opposition_ratio detects a second light source. Genuinely opposite faces
    # cannot both be brightly lit by one sun, so when they are, something else
    # is illuminating the satellite, an Earth albedo reflection for instance,
    # and the single-source assumption behind the estimate has broken.

    # Context sensors: not part of the estimate, but they say whether conditions
    # were sane while it was made.
    thermal: Optional[dict]     # temps/drift/flags
    opt: dict                   # cct_avg (K), gate, trusted, light_source
    stream: Optional[dict]      # StreamMonitor snapshot
    # thermal is None for a one-off frame, since drift needs a history.
    # opt carries the colour check: is this light actually daylight?
    # stream carries link health (packet rate, drops), None when not streaming.

    # How long the pipeline took on this frame, in milliseconds. The design
    # target is 10 ms so the system can keep up with 100 frames per second.
    processing_time_ms: float

    # METHOD (primer 12). `self` is this particular record.
    #
    # PARAMETERS: none besides self.
    # RETURNS: a plain dict, safe to hand to a JSON writer.
    #
    # asdict(self) converts the dataclass into a nested dict of all the fields
    # above. _clean then walks that dict and fixes the NaN and numpy problems.
    # Every path that writes a record out, local JSONL, Firebase, CSV export,
    # goes through this one method, so the scrubbing can never be forgotten in
    # one of them.
    def to_dict(self) -> dict:
        """JSON-safe dict for logging (NaN -> null, numpy -> python)."""
        return _clean(asdict(self))
