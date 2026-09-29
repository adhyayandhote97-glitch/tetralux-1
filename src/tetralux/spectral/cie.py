"""Spectral / color validation for the OPT4048 sensors (formulas 15-16).

WHAT THIS FILE CONTRIBUTES
--------------------------
This file answers a question the geometry cannot: is the light we are pointing
at actually the sun?

The estimator finds the brightest direction. It has no way to tell sunlight from
a desk lamp, so on a bench it will confidently point at the lamp and report a
perfect measurement. Everything about that answer is correct except the
assumption underneath it.

Colour is the check. Light sources have distinctive colours, and the OPT4048
sensor measures colour rather than brightness. Convert its output to a colour
temperature, compare against daylight, and the system can say "this is not
sunlight" instead of quietly trusting a lamp.

THE FOUR STEPS
    Formula 15  cie_chromaticity  raw X, Y, Z into two colour coordinates
    Formula 16  mccamy_n          an intermediate value in McCamy's method
                mccamy_cct        the cubic that yields a temperature in kelvin
                trust_gate        compare against daylight: PASS, FAIL, ADVISORY

COLOUR TEMPERATURE, BRIEFLY. Heat a piece of metal and it glows: dull red, then
orange, then white, then blue-white. The temperature it would have to reach to
glow a given colour is that colour's "colour temperature", measured in kelvin.
About 2700 K is a warm indoor bulb, roughly 5500 K is daylight, above 6500 K is
the bluish light of fluorescent tubes. Confusingly, higher numbers look "cooler"
to the eye.

CCT is "correlated" colour temperature because real sources are not perfect hot
metal; the value is the closest match on that curve.

WHERE IT SITS IN THE FLOW
    spectral/opt.py  calls these for each of the four OPT4048 sensors
    pipeline.py      puts the resulting gate and trust flag into the record

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from tetralux.constants import MIN_EPSILON


# --- Formula 15: raw colour readings into colour coordinates ---
#
# PARAMETERS
#   X, Y, Z - the three raw channels from the OPT4048. These are CIE tristimulus
#             values, an international standard from 1931 for describing colour
#             numerically: roughly how strongly the light stimulates each of the
#             three kinds of colour receptor in a human eye. Y additionally
#             corresponds to brightness.
# RETURNS
#   a tuple (x, y): the chromaticity coordinates. Note lowercase, and note there
#   are only two of them.
#
# WHY THREE NUMBERS BECOME TWO. X, Y, Z mix together WHAT colour the light is
# and HOW MUCH of it there is. Dividing each by the total strips the brightness
# out, leaving pure colour. A dim red and a bright red then give identical
# coordinates, which is exactly what is wanted: colour temperature must not
# change when you move the sensor closer to the lamp.
#
# The third coordinate z is not returned because it is redundant. Since the
# three divided values sum to 1 by construction, z is always 1 - x - y and
# carries no extra information.
def cie_chromaticity(X: float, Y: float, Z: float) -> tuple[float, float]:
    """Formula 15 - CIE chromaticity coordinates."""
    total = X + Y + Z
    # A total of zero means no light reached the sensor, and darkness has no
    # colour. ValueError rather than returning a fake coordinate, so the caller
    # must decide what to do; opt.py catches this and records NaN for that
    # sensor.
    if abs(total) < MIN_EPSILON:
        raise ValueError("X + Y + Z must be non-zero to define chromaticity")
    # Returning two values makes a tuple (primer 5).
    return X / total, Y / total


# --- Formula 16: McCamy's intermediate value ---
#
# PARAMETERS
#   x_cie, y_cie - the chromaticity coordinates from formula 15.
# RETURNS
#   n, a single dimensionless number fed into the cubic below.
#
# WHAT IS GOING ON. Colour temperature is not a simple function of colour
# coordinates; the exact relationship needs an iterative search. In 1992 Calvin
# McCamy found that measuring the angle from a fixed point at (0.3320, 0.1858)
# gives a value from which a simple cubic recovers the temperature to good
# accuracy. Those two constants are that pivot point, empirically determined.
# This function computes the slope from the pivot to the measured colour.
def mccamy_n(x_cie: float, y_cie: float) -> float:
    """Formula 16 - McCamy intermediate value for CCT estimation."""
    denom = y_cie - 0.1858
    # THE "POLE". When y_cie equals 0.1858 exactly, the measured colour sits
    # level with the pivot point, the slope is vertical, and the division is
    # undefined. In maths a point where a function blows up like this is called
    # a pole, hence the message. Rare in practice but real, so it is guarded.
    if abs(denom) < MIN_EPSILON:
        raise ValueError("y_cie must differ from 0.1858 (McCamy pole)")
    return (x_cie - 0.3320) / denom


# --- McCamy's cubic: n into a temperature ---
#
# PARAMETERS
#   x_cie, y_cie - chromaticity coordinates from formula 15.
# RETURNS
#   the correlated colour temperature in kelvin, or NaN if the result is
#   physically impossible.
#
# WATCH THE SIGNS. The coefficients are -449, +3525, -6823.3, +5520.33: they
# ALTERNATE. An earlier version of this project had them all positive, which
# looks like a harmless transcription slip and is not: with every sign positive
# the polynomial only ever grows, so it returns temperatures of tens of
# thousands of kelvin for ordinary light and the trust gate rejects genuine
# daylight. Verify against the published formula before touching this line.
#
# `**` is exponentiation, so `n ** 3` is n cubed.
def mccamy_cct(x_cie: float, y_cie: float) -> float:
    """Correlated colour temperature (K) via McCamy's 1992 cubic."""
    n = mccamy_n(x_cie, y_cie)
    cct = -449.0 * n ** 3 + 3525.0 * n ** 2 - 6823.3 * n + 5520.33
    # SANITY BOUNDS. McCamy's approximation is only valid over the range of
    # colours it was fitted to. Feed it something outside that, a badly
    # miscalibrated sensor or a monochromatic laser, and the cubic still
    # produces a number, but a meaningless one: negative kelvin is
    # thermodynamically impossible, and above 25000 K is beyond any light source
    # this satellite will meet.
    #
    # NaN says "no valid answer" instead of passing a nonsense temperature
    # downstream where it would look like a measurement. opt.py filters NaNs out
    # of the average rather than letting one poison it.
    if cct < 0.0 or cct > 25000.0:
        return float("nan")
    return cct


# --- The verdict ---
#
# PARAMETERS
#   cct_avg   - the average colour temperature across the OPT4048 sensors.
#   reference - what daylight should be, default 5500 K.
#   tolerance - how far from that still counts as daylight, default 500 K.
#               So the accepted band is 5000 K to 6000 K.
# RETURNS
#   one of three strings: "PASS", "FAIL", or "ADVISORY".
#
# WHY THREE OUTCOMES RATHER THAN A BOOLEAN. There is a real difference between
# "measured, and it is not daylight" and "could not measure at all". The first
# means the light source is wrong; the second means the colour sensor failed
# while the photodiodes may be perfectly fine. Collapsing both into False would
# tell an operator to investigate the wrong thing.
def trust_gate(
    cct_avg: float,
    reference: float = 5500.0,
    tolerance: float = 500.0,
) -> str:
    """OPT4048 illumination-trust gate."""
    # `cct_avg != cct_avg` is the standard test for NaN, and it looks wrong at
    # first glance. NaN is defined to be unequal to everything INCLUDING itself,
    # so this comparison is true only for NaN. It is used here instead of
    # math.isnan to keep this module free of imports; opt.py uses the same
    # idiom, with the `# nan` comment as the signpost.
    if cct_avg != cct_avg:  # nan
        return "ADVISORY"
    # A conditional expression: value_if_true if condition else value_if_false.
    # abs() makes the comparison symmetric, so 4900 K and 6100 K are equally far
    # from daylight and both fail.
    return "PASS" if abs(cct_avg - reference) <= tolerance else "FAIL"
