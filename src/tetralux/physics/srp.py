"""Solar radiation pressure (SRP) physics (formulas 6-10 from docs/architecture.md).

WHAT THIS FILE CONTRIBUTES
--------------------------
Sunlight pushes. Light carries momentum, so when it strikes a surface it exerts
a real mechanical force. On Earth the effect is swamped by air and gravity, but
in orbit there is nothing to damp it, and over weeks solar radiation pressure
measurably shifts a spacecraft's position and attitude. Real satellites must
model it to stay where they are meant to be.

Tetralux-1 already measures per-face irradiance in order to estimate the sun
direction. That irradiance is exactly the input the SRP formulas need, so the
same six photodiodes that answer "where is the sun" also answer "how hard is it
pushing, and in which direction". No extra hardware.

THE FIVE FORMULAS, in order:
     6  srp_force_per_face  force on one lit face, from its irradiance
     7  srp_net_force       add the six face forces as vectors
     8  srp_magnitude       how strong the net push is
     9  srp_azimuth         which way it points, horizontally
    10  srp_elevation       and vertically

Expect numbers around 1e-8 newtons: roughly the weight of a grain of dust. That
is not an error, it is the correct scale.

A NOTE ON THIS FILE'S HISTORY. These formulas were implemented and tested but
nothing called them, while the dashboard's About page listed them as if they
were running. They are now wired into pipeline.py, which computes them from the
irradiance it already has. A test asserts the SRP direction tracks the estimated
sun direction, which makes the two independent calculations verify each other.

WHERE IT SITS IN THE FLOW
    calibration.irradiance  supplies the per-face W/m^2 these consume
    pipeline.py             calls all five and fills the srp_* record fields
    constants.py            supplies face area, speed of light, reflectivity

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


# --- Formula 6: force on one face ---
#
# PARAMETERS
#   I_i - irradiance on face i, in watts per square metre. From
#         calibration.irradiance, which derived it from that face's cosine.
#   A   - the face's area in square metres. CUBESAT_FACE_AREA, 0.01 m^2 for a
#         10 cm square face.
#   c   - the speed of light, 3.0e8 m/s. SPEED_OF_LIGHT.
#   rho - reflectivity, 0 to 1. DEFAULT_REFLECTIVITY is 0.30 for anodised
#         aluminium.
# RETURNS
#   the force on that face in newtons.
#
# THE PHYSICS, IN TWO PARTS.
#
# I * A / c converts light power into force. Power divided by the speed of light
# gives momentum per second, and momentum per second is force. Multiplying by
# area first turns power per square metre into total power on that face.
#
# (1 + rho) accounts for what happens on impact. Light that is absorbed delivers
# its momentum once and stops. Light that is reflected delivers its momentum,
# then leaves in the opposite direction, delivering as much again, so a mirror
# feels roughly twice the push of a black surface. At rho = 0 the factor is 1,
# at rho = 1 it is 2, and 0.30 sits between.
#
# All parameters are passed in rather than read from constants.py, which keeps
# this function pure physics: it can be tested with any values, including the
# hand-worked example in the test suite, without touching project configuration.
def srp_force_per_face(I_i: float, A: float, c: float, rho: float) -> float:
    """Formula 6 - SRP force on one illuminated face."""
    return (I_i * A / c) * (1.0 + rho)


# --- Formula 7: add the six face forces ---
#
# PARAMETERS
#   forces       - the six per-face forces from formula 6, in FACE_NAMES order.
#   face_normals - the matching six directions from FACE_NORMALS, same order.
#                  Matched by position, so entry 2 of each must be the same
#                  face.
# RETURNS
#   F_net, a 3-element vector: the total force in newtons, with direction.
#
# Each face is pushed along its own outward normal, so the forces must be added
# as VECTORS, not as plain numbers. Adding the magnitudes would claim a large
# force on a cube lit from all sides, when in fact opposite pushes cancel and
# the true net force is near zero.
#
# This is structurally identical to estimator.direction_vector, and deliberately
# not shared with it. That one combines dimensionless weights into a pure
# direction; this one combines newtons into a physical force whose magnitude
# means something. Merging them would obscure that difference and invite a
# future change made for one purpose to quietly break the other.
def srp_net_force(
    forces: Sequence[float], face_normals: Sequence[np.ndarray]
) -> np.ndarray:
    """Formula 7 - net SRP force vector: ``F_net = sum(F_i * n_hat_i)``."""
    # Accumulator starting at zero (primer 10).
    f_net = np.zeros(3)
    for f, n in zip(forces, face_normals):
        f_net = f_net + float(f) * np.asarray(n, dtype=float)
    return f_net


# --- Formula 8: how strong the net push is ---
#
# PARAMETER
#   F_net - the net force vector from formula 7.
# RETURNS
#   its length in newtons, always positive: the magnitude with direction
#   discarded.
#
# np.linalg.norm is 3D Pythagoras, sqrt(Fx^2 + Fy^2 + Fz^2), the same function
# used to normalize the sun vector. Here the length is the answer rather than
# something to divide away.
def srp_magnitude(F_net: np.ndarray) -> float:
    """Formula 8 - SRP force magnitude: ``|F_net| = sqrt(Fx^2 + Fy^2 + Fz^2)``."""
    return float(np.linalg.norm(np.asarray(F_net, dtype=float)))


# --- Formula 9: which way the push points, horizontally ---
#
# PARAMETERS
#   Fx, Fy - the x and y components of the net force. Fz is not needed, since
#            azimuth is the angle in the horizontal plane only.
# RETURNS
#   the azimuth in RADIANS. pipeline.py converts to degrees for display.
#
# arctan2 rather than arctan(Fy/Fx), for the same reason as in
# estimator.sun_angles: the two-argument form knows which quadrant the point is
# in and so distinguishes a push toward +x from one toward -x. The one-argument
# form cannot, and would fold half the possible directions onto the other half.
def srp_azimuth(Fx: float, Fy: float) -> float:
    """Formula 9 - SRP azimuth (radians): ``arctan2(Fy, Fx)``."""
    return float(np.arctan2(Fy, Fx))


# --- Formula 10: and vertically ---
#
# PARAMETERS
#   Fz        - the vertical component of the net force.
#   F_net_mag - the total magnitude from formula 8.
# RETURNS
#   the elevation in radians, between -90 and +90 degrees.
#
# Fz / F_net_mag is the fraction of the total push that acts vertically, which
# for a right triangle is the sine of the elevation angle. arcsin recovers the
# angle from it.
def srp_elevation(Fz: float, F_net_mag: float) -> float:
    """Formula 10 - SRP elevation (radians): ``arcsin(Fz / |F_net|)``."""
    # A zero magnitude means no net force, in darkness or with perfectly
    # balanced illumination, so there is no direction to report and the division
    # is undefined. pipeline.py checks for this beforehand and stores None for
    # both SRP angles rather than calling this.
    if F_net_mag == 0:
        raise ValueError("F_net_mag must be non-zero")
    # Clamp into [-1, 1] before arcsin. Mathematically the ratio cannot exceed 1
    # because a component is never longer than the whole vector, but
    # floating-point rounding can produce 1.0000000000000002, and arcsin past 1
    # is NaN. The same guard appears in estimator.sun_angles for the same
    # reason.
    ratio = max(-1.0, min(1.0, Fz / F_net_mag))
    return float(np.arcsin(ratio))
