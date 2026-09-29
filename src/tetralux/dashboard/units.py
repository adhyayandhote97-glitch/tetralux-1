"""Units registry + formatters (Phase 9, Decision 7).

WHAT THIS FILE CONTRIBUTES
--------------------------
Every number shown on the dashboard carries its unit, or is explicitly labelled
"dimensionless". This file is what enforces that.

WHY IT IS A HARD RULE. "Temperature: 25" is ambiguous, and "0.342" is worse: it
could be a weight, a cosine, a vector component or a confidence, and each of
those means something different. A displayed number without a unit is not a
measurement, it is a decimal.

"Dimensionless" is a real answer, not a cop-out. A weight is ADC counts divided
by ADC counts, so the units genuinely cancel and it is a pure ratio. Saying so
is different from forgetting the unit, and the difference is exactly what a
reader needs to know.

HOW IT WORKS. UNITS maps a quantity NAME to its unit STRING, so the unit is
declared once and every display site looks it up. If irradiance were ever
reported in kW/m² instead, one line changes here and the whole dashboard
follows. Typing units into each label would guarantee inconsistency.

The formatters also handle the awkward values uniformly: None, NaN and infinity
all become a dash, so a missing measurement looks obviously missing rather than
appearing as a suspicious 0.000.

WHERE IT SITS IN THE FLOW
    dashboard/app.py      calls q() for essentially every displayed value
    dashboard/figures.py  uses unit_of() for axis labels
    record.py             supplies the values, already NaN-scrubbed

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import math
from typing import Optional

# Canonical unit strings by quantity.
#
# The single source of truth for every unit in the user interface. Note the
# entries that spell out "dimensionless": those quantities have no unit, and
# saying so explicitly is the whole policy.
UNITS = {
    # Raw and calibrated sensor readings. "ADC counts" because these are what
    # the converter reported, not a physical quantity.
    "photodiode": "ADC counts",
    "corrected": "ADC counts",
    "lux": "lx",
    # W/m² is watts per square metre, real physical light power.
    "irradiance": "W/m²",
    # Ratios: counts over counts, so the units cancel.
    "weight": "dimensionless",
    "cosine": "dimensionless",
    # A unit vector's component. Dimensionless, and the parenthetical says why.
    "sun_component": "dimensionless (unit vector)",
    "angle": "°",
    "temperature": "°C",
    "drift": "°C/min",
    "cct": "K",
    # NANOnewtons, a billionth of a newton. SRP forces are around 1e-8 N, so
    # displaying them in newtons would be a wall of zeros; the dashboard scales
    # them into nN for readability.
    "force": "nN",
    "rate": "Hz",
    "timestamp_ms": "ms",
    # A sequence number counts packets and measures nothing physical, so it is
    # labelled as an index rather than left bare.
    "seq": "index (dimensionless)",
    "checksum": "8-bit",
    "flags": "bitfield",
    # The ranges are included because they tell the reader how to interpret the
    # value: 0.8 means little unless you know the scale runs 0 to 1.
    "confidence": "dimensionless (0-1)",
    "opposition": "dimensionless (0-1)",
    # The magnetometer is uncalibrated, so "raw" is the honest label. Claiming
    # microtesla would imply a calibration that was never performed.
    "mag": "raw",
    "bytes": "B",
    "count": "count",
    "duration": "s",
}


# --- The core formatter ---
#
# PARAMETERS
#   value - anything to display: a number, a bool, a string, or None.
#   unit  - the unit string to append, or None for a bare value.
#   nd    - how many decimal places for floats. 3 by default; callers pass 0 for
#           whole numbers such as a colour temperature.
# RETURNS
#   a display-ready string.
#
# NOTE: the docstring below says "em dash", but the code returns an ordinary
# hyphen "-". The docstring is stale; the behaviour is the hyphen, and
# test_dashboard_v2.py asserts exactly that.
def fmt(value, unit: Optional[str] = None, nd: int = 3) -> str:
    """Format a value with its unit; None/NaN render as an em dash."""
    # None means "not measured" (see record.py). A dash shows that plainly. It
    # returns EARLY, before any unit is appended, because "- °C" would imply a
    # temperature reading that does not exist.
    if value is None:
        return "-"
    if isinstance(value, float):
        # NaN and infinity get the same treatment as None: all three mean no
        # usable value. Printing "nan" would be meaningless to a reader.
        if math.isnan(value) or math.isinf(value):
            return "-"
        # A NESTED FORMAT SPEC. The inner {nd} is substituted first, so with
        # nd=3 this becomes "{value:.3f}", and the value is then formatted to 3
        # decimal places. That is how the precision becomes a parameter.
        text = f"{value:.{nd}f}"
    # bool is checked AFTER float. "yes"/"no" reads better in a status panel
    # than "True"/"False".
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        # Strings, ints and everything else.
        text = str(value)
    # Append the unit only if there is one, so a unitless caller does not get a
    # trailing space.
    return f"{text} {unit}" if unit else text


# PARAMETER
#   quantity - a key from UNITS, e.g. "irradiance".
# RETURNS
#   the unit string, or "" if the quantity is not registered.
#
# .get with a default of "" rather than raising: an unregistered quantity
# renders without a unit instead of crashing a whole dashboard page. Used mainly
# for figure axis labels, where the unit is needed on its own.
def unit_of(quantity: str) -> str:
    """Look up the unit string for a named quantity."""
    return UNITS.get(quantity, "")


# --- The function actually used everywhere ---
#
# PARAMETERS
#   value    - what to display.
#   quantity - which registered quantity it is, which determines the unit.
#   nd       - decimal places.
# RETURNS
#   the formatted string with its unit attached.
#
# `q(0.25, "weight")` gives "0.250 dimensionless".
#
# Deliberately short, one letter, because it wraps nearly every value in
# app.py. A longer name there would bury the actual content in boilerplate. The
# combination of lookup and formatting in one call is what makes the units rule
# easy enough to follow that it is actually followed.
def q(value, quantity: str, nd: int = 3) -> str:
    """Format ``value`` with the unit registered for ``quantity``."""
    return fmt(value, UNITS.get(quantity), nd)


# PARAMETER
#   n - a size in bytes.
# RETURNS
#   readable text such as "2.0 KiB".
#
# The same repeated-division trick as SessionSummary.size_human in
# store/query.py, kept here so the dashboard does not have to import from the
# storage layer just to format a number.
def human_bytes(n: int) -> str:
    """Human-readable byte size."""
    b = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TiB"
