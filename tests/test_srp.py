"""Tests for SRP physics (formulas 6-10) using the brief's worked examples."""

import numpy as np
import pytest

from tetralux.physics.srp import (
    srp_azimuth,
    srp_elevation,
    srp_force_per_face,
    srp_magnitude,
    srp_net_force,
)


def test_srp_force_per_face_worked_example():
    # Formula 6: (1361 * 0.01 / 3e8) * 1.30 ~ 5.9e-8 N
    f = srp_force_per_face(I_i=1361.0, A=0.01, c=3e8, rho=0.30)
    assert f == pytest.approx(5.9e-8, rel=1e-2)


def test_srp_net_force_sums_components():
    # Formula 7: forces on +x, +y, +z -> vector of those magnitudes
    normals = [
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
    ]
    f_net = srp_net_force([59.0, 59.0, 40.0], normals)
    assert np.allclose(f_net, [59.0, 59.0, 40.0])


def test_srp_magnitude_worked_example():
    # Formula 8: |(59, 59, 40)| = sqrt(8562) ~ 92.53 (brief rounds to ~93)
    assert srp_magnitude([59.0, 59.0, 40.0]) == pytest.approx(92.53, abs=0.1)


def test_srp_azimuth_worked_example():
    # Formula 9: arctan2(59, 59) = 45 deg
    assert np.degrees(srp_azimuth(59.0, 59.0)) == pytest.approx(45.0)


def test_srp_elevation_worked_example():
    # Formula 10: arcsin(40 / 93) ~ 25.5 deg
    assert np.degrees(srp_elevation(40.0, 93.0)) == pytest.approx(25.48, abs=0.1)
