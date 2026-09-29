"""Photodiode calibration (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
Calibration is what makes six separate photodiodes comparable to each other.

Buy six nominally identical photodiodes, wire them to the six faces, put them
under identical light, and they will give you six different numbers. Each has a
slightly different sensitivity, a slightly different leakage current in the
dark, and a slightly different ceiling. The estimator works by comparing faces,
so those differences would masquerade as a real difference in lighting and lean
the estimated sun direction permanently off.

This file holds the three per-face numbers that cancel those differences out:

    dark              what the face reads with no light at all, subtracted away
    gain              a scale factor near 1.0 correcting its sensitivity
    max_illumination  what it reads with light straight on, its ceiling

It also provides the per-face wrappers around formulas 1 and 5. estimator.py
implements those formulas for a single face with parameters passed in; the
functions here apply them across all six faces using stored calibration, and add
the physical clamping that real hardware needs.

The Calibration class can save itself to a JSON file and load itself back,
because these numbers are properties of one physical prototype. Measure them
once with calibration_tool.py, save the file, and every later run reuses them.

WHERE IT SITS IN THE FLOW
    calibration_tool.py  measures these values and writes the JSON file
    pipeline.py          loads a Calibration and calls all three functions
    dashboard/state.py   can load a new calibration file live, no restart

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# json: converts between Python data and JSON text, the standard format for
# config files. Human-readable and readable by any other language.
import json
from dataclasses import asdict, dataclass, field
# Path: the modern way to handle file paths, working on Mac, Linux and Windows
# without worrying about slash direction.
from pathlib import Path
# Union[A, B] is a type hint meaning "either an A or a B".
from typing import Union

from tetralux.constants import FACE_NAMES, MIN_EPSILON, SOLAR_CONSTANT
from tetralux.estimation.estimator import corrected_reading

# v0 lab-calibration defaults (per face, canonical order).
#
# These are PLACEHOLDERS, measured from an earlier prototype. They are
# plausible, which makes the software runnable and testable before any hardware
# exists, but they do not describe the current board.
#
# Notice the pattern they encode, because it is what genuine per-face variation
# looks like: dark offsets of 4 to 7 counts (real leakage in darkness), gains
# within 3% of 1.0 (real sensitivity spread), maxima near but not at the 1023
# ADC ceiling. Replace all three with calibration_tool.py output before trusting
# any measurement from real hardware.
DEFAULT_DARK = {"+x": 5.0, "-x": 4.0, "+y": 6.0, "-y": 5.0, "+z": 7.0, "-z": 6.0}
DEFAULT_GAIN = {"+x": 1.00, "-x": 0.98, "+y": 1.02, "-y": 0.99, "+z": 1.01, "-z": 0.97}
DEFAULT_MAX = {"+x": 1000.0, "-x": 980.0, "+y": 1005.0, "-y": 995.0, "+z": 1010.0, "-z": 970.0}
# The bench lamp used for testing is about a tenth as bright as real sunlight.
# This factor scales lab measurements to what the satellite would see in orbit,
# so the irradiance figures stay physically meaningful indoors.
DEFAULT_LAB_SCALING = 0.1  # I_lamp / I_sun (see docs/architecture.md calibration notes)


@dataclass
class Calibration:
    """Per-face calibration parameters."""

    # Every field has a default, so `Calibration()` with no arguments gives a
    # working placeholder set. That is what lets tests and Virtual mode run
    # without a calibration file.
    #
    # WHY default_factory AND lambda. Two separate problems are being solved.
    #
    # First, a mutable default is a classic Python trap. If this said
    # `dark: dict = DEFAULT_DARK`, every Calibration ever created would share
    # the SAME dict object, so editing one object's dark offsets would silently
    # change every other one, including the module-level defaults above.
    # default_factory calls a function fresh for each new object instead.
    #
    # Second, `lambda: dict(DEFAULT_DARK)` is a small unnamed function that
    # makes a COPY of the defaults. `dict(x)` copies x. So each Calibration gets
    # its own independent copy that it is safe to modify.
    dark: dict = field(default_factory=lambda: dict(DEFAULT_DARK))
    gain: dict = field(default_factory=lambda: dict(DEFAULT_GAIN))
    max_illumination: dict = field(default_factory=lambda: dict(DEFAULT_MAX))
    # A float is immutable, so it cannot be shared and mutated by accident, and
    # a plain default is safe here.
    lab_scaling_factor: float = DEFAULT_LAB_SCALING

    # RETURNS: this calibration as JSON text.
    #
    # asdict turns the dataclass into a plain dict. indent=2 pretty-prints it
    # over multiple lines and sort_keys=True puts the keys in a fixed order,
    # both so a person can read the file and so two files can be diffed
    # sensibly rather than showing spurious reordering.
    def to_json(self) -> str:
        """Serialize to a JSON string (one key per parameter, per-face dicts)."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    # @classmethod marks a method that belongs to the CLASS rather than to one
    # object. Its first parameter is `cls` (the class itself) instead of `self`,
    # and you call it as Calibration.from_json(text) with no object in hand.
    #
    # That is exactly right here: this method CREATES a Calibration, so there is
    # no existing one to call it on. `cls(...)` at the end is what builds it.
    #
    # PARAMETER
    #   text - JSON produced by to_json above.
    # RETURNS
    #   a new Calibration.
    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        """Reconstruct from a JSON string produced by :meth:`to_json`."""
        # json.loads parses text into Python data (loads = "load string").
        data = json.loads(text)
        # Square brackets rather than .get, deliberately: a missing field must
        # be an error, not a silent fallback to placeholder values. Silently
        # substituting defaults for real measurements would produce plausible
        # readings that are quietly wrong, which is the worst failure mode
        # available. The KeyError this raises is caught in load() below and
        # turned into a clearer message.
        #
        # dict(...) copies again, and float(...) converts even if the file
        # stored the value as a string.
        return cls(
            dark=dict(data["dark"]),
            gain=dict(data["gain"]),
            max_illumination=dict(data["max_illumination"]),
            lab_scaling_factor=float(data["lab_scaling_factor"]),
        )

    # PARAMETER
    #   path - where to write, as text or a Path object. Union[str, Path]
    #          documents that either is accepted.
    # RETURNS
    #   None. `-> None` is the hint for a function that does something rather
    #   than computing something. Writing a file IS the point here.
    #
    # encoding="utf-8" states the text encoding explicitly instead of relying on
    # whatever the machine defaults to, so a file written on one computer reads
    # identically on another.
    def save(self, path: Union[str, Path]) -> None:
        """Write this calibration to a JSON file."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    # The counterpart to save. A classmethod for the same reason as from_json:
    # it produces a Calibration rather than acting on one.
    @classmethod
    def load(cls, path: Union[str, Path]) -> "Calibration":
        """Load a calibration previously written by :meth:`save`."""
        text = Path(path).read_text(encoding="utf-8")
        # try/except (primer 11). from_json raises KeyError when a field is
        # missing, but a bare KeyError says only `'gain'`, which tells the
        # operator nothing about which file or why.
        try:
            return cls.from_json(text)
        except KeyError as exc:
            # `as exc` names the caught error so it can be quoted in the new
            # message. This still fails, deliberately, just more usefully.
            #
            # `from exc` chains the two errors so the traceback shows both the
            # clear message and the original cause. Without it, the underlying
            # KeyError is hidden and debugging gets harder.
            raise ValueError(f"calibration file {path} missing field: {exc}") from exc


# --- Formula 1 across all six faces ---
#
# PARAMETERS
#   photodiodes - raw ADC counts keyed by face, from SensorFrame.photodiode_map.
#   cal         - the Calibration holding this prototype's dark and gain values.
# RETURNS
#   a dict of corrected readings, one per face.
#
# THE max(0.0, ...) IS THE ADDITION HERE, and it is a physical statement.
# Formula 1 subtracts the dark offset, so a face sitting in shadow that happens
# to read slightly below its measured dark value comes out negative. Negative
# light does not exist; it is measurement noise around zero.
#
# It cannot be left in place, because a negative reading would subtract from the
# total in formula 2 and give the other faces weights above 1, and it would pull
# the direction sum backwards along that face's axis. Flooring at zero says "no
# detectable light here", which is the truth.
def corrected_readings(photodiodes: dict, cal: Calibration) -> dict:
    """Formula 1 per face, floored at 0: ``R_i = max(0, (V_i - D_i) * G_i)``."""
    # A dict comprehension over the canonical face order, calling the
    # single-face formula from estimator.py once per face.
    return {
        f: max(0.0, corrected_reading(float(photodiodes[f]), cal.dark[f], cal.gain[f]))
        for f in FACE_NAMES
    }


# --- Formula 5 across all six faces ---
#
# PARAMETERS
#   corrected - the output of corrected_readings above.
#   cal       - supplies max_illumination, each face's dead-on ceiling.
# RETURNS
#   cos(theta) per face, clamped to the range 0 to 1, dimensionless.
#
# Written as an explicit loop rather than a comprehension because each face
# needs two steps, and forcing that onto one line would hurt readability.
def cosine_proxy(corrected: dict, cal: Calibration) -> dict:
    """Formula 5 per face, clamped to [0, 1]: ``cos(theta_i) = R_i / V_max_i``."""
    out = {}
    for f in FACE_NAMES:
        # Guard the divisor. A zero or missing maximum would divide by zero, so
        # this floors it at MIN_EPSILON. estimator.cosine_proxy raises in that
        # situation; here the pipeline must keep running on live telemetry, so
        # it degrades instead of stopping.
        v_max = max(cal.max_illumination[f], MIN_EPSILON)
        # Clamp into [0, 1]. Reading outward: divide, then max(0.0, ...) catches
        # any residual negative, then min(1.0, ...) caps the top.
        #
        # The upper cap matters physically. A cosine cannot exceed 1: that would
        # mean light striking a surface more than head-on, which is meaningless.
        # A reading above the calibrated maximum means either the calibration is
        # stale or the light is brighter than the reference lamp. Either way the
        # honest answer is "fully lit", not an impossible 1.07.
        out[f] = min(1.0, max(0.0, corrected[f] / v_max))
    return out


# --- Converting cosines into real physical light power ---
#
# PARAMETERS
#   cosine - the output of cosine_proxy above.
#   cal    - supplies lab_scaling_factor, the bench-lamp to sunlight ratio.
# RETURNS
#   irradiance per face in watts per square metre.
#
# Everything up to this point has been in arbitrary sensor counts. This is where
# the numbers become physics: SOLAR_CONSTANT is 1361 W/m^2, the actual power
# sunlight delivers at Earth's distance, and the cosine says what fraction of it
# a tilted face collects.
#
# This is what the solar radiation pressure calculation consumes, and it is the
# reason formula 5 exists at all: without a real irradiance figure, formulas 6
# to 10 would have nothing to work from.
def irradiance(cosine: dict, cal: Calibration) -> dict:
    """Per-face irradiance (W/m^2): ``I_i = SOLAR_CONSTANT * f_lab * cos(theta_i)``."""
    return {f: SOLAR_CONSTANT * cal.lab_scaling_factor * cosine[f] for f in FACE_NAMES}
