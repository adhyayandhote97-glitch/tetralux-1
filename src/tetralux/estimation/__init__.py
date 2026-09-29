"""Phase 2: estimation engine - recover the sun vector from face readings.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `estimation/` as a package and re-exports everything in estimator.py, so
callers can write `from tetralux.estimation import sun_vector` instead of the
longer path through the module name.

This subpackage holds the mathematical core of the project: formulas 1 to 5,
which turn six brightness readings into a direction. See estimator.py for the
formulas themselves and the derivation.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is and why these re-exports exist.
"""

# Importing these names here makes them available directly on the package.
# Alphabetical, which is the convention linters enforce and which makes a long
# list easy to scan for a particular name.
from tetralux.estimation.estimator import (
    LowSignalError,
    angles_to_vector,
    corrected_reading,
    cosine_proxy,
    direction_vector,
    estimate_sun_vector,
    face_weight,
    sun_angles,
    sun_vector,
)

# __all__ declares the public API. Ordered by the PIPELINE here rather than
# alphabetically, so reading it top to bottom follows the calculation: the error
# type, then formulas 1 to 5 in order, then the full pipeline function, then the
# two angle conversions.
__all__ = [
    "LowSignalError",
    "corrected_reading",      # formula 1
    "face_weight",            # formula 2
    "direction_vector",       # formula 3
    "sun_vector",             # formula 4 (LOCKED)
    "cosine_proxy",           # formula 5
    "estimate_sun_vector",    # formulas 1-4 chained
    "sun_angles",             # vector -> azimuth/elevation
    "angles_to_vector",       # azimuth/elevation -> vector
]
