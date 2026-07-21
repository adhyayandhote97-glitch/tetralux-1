"""End-to-end integration: simulate a known light direction, run it through the
full estimation pipeline, and check we recover the true direction."""

import numpy as np
import pytest

from tetralux.estimation.estimator import estimate_sun_vector
from tetralux.sim.simulator import generate_sweep, simulate_faces
from tetralux.validation.metrics import angular_error


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def test_pipeline_recovers_known_direction_noise_free():
    """Simulate -> calibrate -> estimate reproduces the true light_dir exactly."""
    true_dir = _unit([1.0, 2.0, 3.0])
    faces = simulate_faces(true_dir, intensity=1000.0)
    s_hat = estimate_sun_vector(faces)
    assert angular_error(s_hat, true_dir) == pytest.approx(0.0, abs=1e-9)


def test_pipeline_inverts_gain_and_dark_offset():
    """With per-face gain and dark offset, calibration still recovers the truth."""
    true_dir = _unit([-1.0, 0.5, 2.0])
    gain = {"+x": 1.05, "-x": 0.95, "+y": 1.1, "-y": 0.9, "+z": 1.02, "-z": 0.98}
    dark = {"+x": 20.0, "-x": 15.0, "+y": 25.0, "-y": 18.0, "+z": 22.0, "-z": 19.0}

    faces = simulate_faces(true_dir, intensity=1000.0, gain=gain, dark_current=dark)
    s_hat = estimate_sun_vector(faces, dark_offset=dark, gain=gain)
    assert angular_error(s_hat, true_dir) == pytest.approx(0.0, abs=1e-9)


def test_pipeline_small_error_under_noise():
    """With modest noise, the estimate stays close to the true direction."""
    true_dir = _unit([0.2, -0.4, 1.0])
    rng = np.random.default_rng(2024)
    faces = simulate_faces(true_dir, intensity=1000.0, noise_std=5.0, rng=rng)
    s_hat = estimate_sun_vector(faces)
    # 5-count noise on a 1000-count peak -> error well under 5 degrees.
    assert np.degrees(angular_error(s_hat, true_dir)) < 5.0


def test_pipeline_over_full_sweep_is_accurate():
    """Every noise-free sweep sample recovers its ground-truth direction."""
    for true_dir, faces in generate_sweep(step_deg=15.0, intensity=1000.0):
        s_hat = estimate_sun_vector(faces)
        assert np.degrees(angular_error(s_hat, true_dir)) < 1e-6
