"""Tests for the Phase 1 sun-vector simulator."""

import numpy as np
import pytest

from tetralux.constants import FACE_NAMES
from tetralux.sim.simulator import generate_sweep, simulate_faces


def test_light_on_plus_x_maximizes_that_face():
    """Light straight at +x -> +x is the max reading; -x is ~zero."""
    faces = simulate_faces(np.array([1.0, 0.0, 0.0]), intensity=1000.0)
    readings = {name: faces[name]["reading"] for name in FACE_NAMES}

    assert readings["+x"] == max(readings.values())
    assert readings["+x"] == pytest.approx(1000.0)
    assert readings["-x"] == pytest.approx(0.0, abs=1e-12)
    # Faces orthogonal to the light see nothing either.
    for name in ("+y", "-y", "+z", "-z"):
        assert readings[name] == pytest.approx(0.0, abs=1e-12)


def test_45_degrees_between_x_and_y_balances_faces():
    """Light 45 deg between +x and +y -> +x and +y read roughly equal."""
    faces = simulate_faces(np.array([1.0, 1.0, 0.0]), intensity=1000.0)
    rx = faces["+x"]["reading"]
    ry = faces["+y"]["reading"]

    assert rx > 0.0 and ry > 0.0
    assert rx == pytest.approx(ry, rel=1e-9)
    # Each should be ~cos(45 deg) * intensity.
    assert rx == pytest.approx(1000.0 * np.cos(np.radians(45.0)), rel=1e-9)
    # The opposite faces are dark.
    assert faces["-x"]["reading"] == pytest.approx(0.0, abs=1e-12)
    assert faces["-y"]["reading"] == pytest.approx(0.0, abs=1e-12)


def test_saturation_clips_and_flags():
    """Readings at/above the limit clip to it and flag; below do not."""
    faces = simulate_faces(
        np.array([1.0, 0.0, 0.0]), intensity=1000.0, saturation_limit=800.0
    )
    # +x would read 1000 -> clipped to 800, flagged.
    assert faces["+x"]["reading"] == pytest.approx(800.0)
    assert faces["+x"]["saturated"] is True
    # A face pointing away stays at 0 -> below the limit, not flagged.
    assert faces["-x"]["reading"] < 800.0
    assert faces["-x"]["saturated"] is False


def test_noise_is_reproducible_with_fixed_seed():
    """Same seed -> identical readings; a different seed differs somewhere."""
    d = np.array([0.3, 0.5, 0.8])
    a = simulate_faces(d, intensity=500.0, noise_std=5.0, rng=np.random.default_rng(42))
    b = simulate_faces(d, intensity=500.0, noise_std=5.0, rng=np.random.default_rng(42))
    c = simulate_faces(d, intensity=500.0, noise_std=5.0, rng=np.random.default_rng(7))

    for name in FACE_NAMES:
        assert a[name]["reading"] == b[name]["reading"]
    assert any(a[name]["reading"] != c[name]["reading"] for name in FACE_NAMES)


def test_zero_light_direction_raises():
    """A zero-length light_dir has no direction and must error, not divide by 0."""
    with pytest.raises(ValueError):
        simulate_faces(np.array([0.0, 0.0, 0.0]))


def test_generate_sweep_shape_and_unit_vectors():
    """Sweep has the expected count and every light_dir is unit length."""
    pairs = generate_sweep(step_deg=15.0, intensity=1000.0)

    # 6 elevations (0..75) x 24 azimuths + 1 pole (elevation 90) = 145.
    assert len(pairs) == 145
    for light_dir, readings in pairs:
        assert np.linalg.norm(light_dir) == pytest.approx(1.0, rel=1e-9)
        assert set(readings.keys()) == set(FACE_NAMES)
