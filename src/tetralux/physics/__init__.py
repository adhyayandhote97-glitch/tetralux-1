"""Solar radiation pressure physics (formulas 6-10).

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `physics/` as a package and re-exports the five SRP functions from srp.py.

This subpackage answers a different question from the estimator. That one asks
where the sun is; this one asks how hard its light is pushing on the satellite,
and in which direction. Both work from the same six photodiode readings, which
is why the physics needs no extra hardware.

Expect forces around 1e-8 newtons. See srp.py for why that tiny number matters
in orbit.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.physics.srp import (
    srp_azimuth,
    srp_elevation,
    srp_force_per_face,
    srp_magnitude,
    srp_net_force,
)

# Ordered by formula number, which is also the order pipeline.py calls them:
# per-face force, sum as vectors, take the magnitude, then the two angles.
__all__ = [
    "srp_force_per_face",   # formula 6
    "srp_net_force",        # formula 7
    "srp_magnitude",        # formula 8
    "srp_azimuth",          # formula 9
    "srp_elevation",        # formula 10
]
