"""Cross-phase constants for Tetralux-1.

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the single place where every fixed number and fixed name in the project
is written down. Nothing here calculates anything; it only declares facts. Face
names, the six face directions, physical constants like the speed of light, and
the thresholds that decide "too dark" or "sensor saturated" all live here.

Almost every other file imports from this one, and this file imports from no
other Tetralux file. That is deliberate, and it is the reason the project holds
together: if the saturation threshold were typed directly into the fault
detector, the simulator, and the dashboard separately, changing it would mean
finding three copies and one of them would eventually be missed. Defined once
here, a change is a one-line change everywhere at once.

A value written here is called a CONSTANT: set when the program starts, never
changed while it runs. Python does not actually stop you from changing it, so
the convention is CAPITAL_LETTERS as a signal to any reader: do not assign to
this.

New to Python? Read docs/python-primer.md first; it explains def, parameters,
return, classes and so on once, so the comments here can stay about the physics.
"""

# See the primer, section 6. This lets the modern hint syntax `list[str]` below
# work on Python 3.9, where it would otherwise be an error.
from __future__ import annotations

# Loads the numerical library and nicknames it `np`, so `np.array(...)` below
# means "the array function from numpy". Needed here because the face normals
# are 3D vectors, not single numbers.
import numpy as np

# Canonical face ordering. Used everywhere so per-face iteration and any future
# fixed-length telemetry packing stay consistent.
#
# The CubeSat is a cube, so it has six faces. Each is named by the axis it
# points along: "+x" faces one way down the x axis, "-x" the opposite way.
#
# This ORDER is the important part, not just the names. The firmware sends six
# photodiode readings as a plain list, [812, 0, 455, 0, 210, 0], with no labels
# attached. The only thing that turns position 2 in that list back into "the +y
# face" is this list. Reorder it and the hardware readings silently attach to
# the wrong faces, producing a wrong sun direction with no error anywhere.
FACE_NAMES: list[str] = ["+x", "-x", "+y", "-y", "+z", "-z"]

# Outward unit normal for each face, in the CubeSat body frame.
#
# A "normal" is a vector pointing straight out of a surface, perpendicular to
# it. "Unit" means its length is exactly 1, so it carries a direction and no
# magnitude. "Body frame" means these are measured relative to the satellite
# itself, not the Earth or the sun: +x is always the same physical face of the
# cube however the satellite is tumbling.
#
# These vectors are what turn six brightness numbers into a direction. The
# estimator multiplies each face's normal by how brightly that face is lit and
# adds them up; faces pointing at the light contribute more, so the sum leans
# toward the light. That is formula 3 of the locked math spec.
FACE_NORMALS: dict[str, np.ndarray] = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}

# Low-signal / divide-by-zero guard threshold (see docs/architecture.md §3).
#
# 1e-9 is scientific notation for 0.000000001, one billionth.
#
# WHY THIS EXISTS: several formulas divide by a total. In darkness every reading
# is zero, so the total is zero, and dividing by zero is undefined. Worse, real
# sensors never read exactly 0.0 - they read 0.0000001 from electrical noise, so
# a plain `if total == 0` check would not catch it and the division would return
# a huge meaningless number that looks like a real measurement.
#
# So instead of testing "is it zero", the code tests "is it smaller than
# MIN_EPSILON", meaning "so close to zero that it is noise, not signal".
MIN_EPSILON: float = 1e-9

# Photodiode ADC (Arduino Nano 33 IoT is 10-bit). Saturation trips just below
# the hard rail (see docs/architecture.md §2).
#
# An ADC (analog-to-digital converter) turns a photodiode's voltage into a
# number. "10-bit" means 2^10 = 1024 possible values, numbered 0 to 1023. So
# 1023 is not a tuning choice; it is the physical ceiling of the hardware.
#
# SATURATION_ADC sits at 1020, slightly BELOW the ceiling, on purpose. A face
# reading exactly 1023 has hit the rail: the true brightness might be 1023 or
# ten times that, and the sensor cannot tell you which. Such a reading
# understates the real light and would drag the estimate off. Catching it a few
# counts early flags a nearly-railed face before its reading starts lying.
ADC_MAX: int = 1023
SATURATION_ADC: int = 1020

# Physical constants (SI). SI is the standard metric system, so every
# calculation here can be combined without converting anything.
SOLAR_CONSTANT: float = 1361.0   # W/m^2, mean solar irradiance at 1 AU
CUBESAT_FACE_AREA: float = 0.01  # m^2, one 1U face (0.1 m x 0.1 m)
SPEED_OF_LIGHT: float = 3.0e8    # m/s
# "1 AU" is one astronomical unit, the average Earth-sun distance. "1U" is the
# CubeSat size standard: a 10 cm cube, so 0.1 x 0.1 = 0.01 m^2 per face.
# These three feed the solar radiation pressure formulas.

# Surface reflectivity used for solar radiation pressure (0 absorbs, 1 reflects).
# 0.30 corresponds to anodised aluminium.
#
# Reflectivity matters for force because absorbed light transfers its momentum
# once, while reflected light bounces back and transfers roughly twice as much.
# That is why formula 6 multiplies by (1 + reflectivity): at 0.0 the factor is
# 1, at 1.0 it is 2.
DEFAULT_REFLECTIVITY: float = 0.30

# OPT4048 colour-trust reference (correlated colour temperature).
#
# CCT, in kelvin, describes the colour of a light source: roughly 5500 K is
# daylight, about 2700 K a warm indoor bulb, fluorescent tubes higher again.
#
# This is a sanity check on the whole measurement. The satellite is supposed to
# be tracking the sun. If the light reaching it is the colour of a desk lamp,
# the sun vector may be geometrically valid but pointing at the wrong source, so
# the spectral code compares measured CCT against these two numbers and marks
# the reading trusted only when it falls within tolerance of daylight.
CCT_REFERENCE_DAYLIGHT: float = 5500.0  # K
CCT_TOLERANCE_DEFAULT: float = 500.0    # K

# Rolling-window size (frames) for validation and thermal statistics.
#
# Some numbers are meaningless from a single reading. "Repeatability" asks how
# much the estimate jitters, which needs a run of readings to compare. So the
# code keeps the most recent 60 frames and computes statistics over those,
# discarding older ones. That is a "rolling window": it slides forward as new
# frames arrive. At roughly 10 frames per second, 60 frames is about 6 seconds.
ROLLING_WINDOW_SIZE: int = 60
# Temperature drift flag threshold.
#
# Photodiodes change their response as they heat up, so a steadily rising
# temperature means the readings themselves are drifting and the estimate is
# quietly degrading. Warming faster than 0.5 degrees Celsius per minute raises
# a flag.
DRIFT_THRESHOLD_C_PER_MIN: float = 0.5
