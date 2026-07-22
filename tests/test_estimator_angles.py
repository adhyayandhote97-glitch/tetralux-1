"""Tests for azimuth/elevation helpers (Phase 6)."""

import numpy as np
import pytest

from tetralux.estimation.estimator import angles_to_vector, sun_angles


def test_sun_angles_cardinal_directions():
    az, el = sun_angles([1.0, 0.0, 0.0])
    assert az == pytest.approx(0.0) and el == pytest.approx(0.0)
    az, el = sun_angles([0.0, 1.0, 0.0])
    assert az == pytest.approx(90.0) and el == pytest.approx(0.0)
    az, el = sun_angles([0.0, 0.0, 1.0])
    assert el == pytest.approx(90.0)


def test_angles_vector_round_trip():
    for az, el in [(0, 0), (45, 20), (-90, 10), (135, -30), (170, 60)]:
        v = angles_to_vector(az, el)
        assert np.linalg.norm(v) == pytest.approx(1.0)
        az2, el2 = sun_angles(v)
        assert az2 == pytest.approx(az, abs=1e-6)
        assert el2 == pytest.approx(el, abs=1e-6)
