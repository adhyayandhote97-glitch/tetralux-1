"""Tests for validation metrics (formulas 11-14) using the brief's examples."""

import numpy as np
import pytest

from tetralux.validation.metrics import (
    angular_error,
    bias,
    repeatability,
    temp_drift_rate,
)


def test_angular_error_worked_example():
    # Formula 11: dot ~ 0.98 -> ~11.5 deg
    s_hat = np.array([1.0, 0.0, 0.0])
    s_ref = np.array([0.98, np.sqrt(1 - 0.98**2), 0.0])  # dot == 0.98
    theta = angular_error(s_hat, s_ref)
    assert theta == pytest.approx(np.arccos(0.98))
    assert np.degrees(theta) == pytest.approx(11.48, abs=0.1)


def test_angular_error_clamps_and_is_zero_for_identical():
    v = np.array([0.3, 0.5, 0.8])
    v = v / np.linalg.norm(v)
    assert angular_error(v, v) == pytest.approx(0.0, abs=1e-9)


def test_repeatability_worked_example():
    # Formula 12: std([10,11,12,11,10]) ~ 0.748 (population std)
    assert repeatability([10, 11, 12, 11, 10]) == pytest.approx(0.748, abs=0.01)


def test_bias_worked_example():
    # Formula 13: mean([10,11,12]) == 11
    assert bias([10, 11, 12]) == pytest.approx(11.0)


def test_temp_drift_rate_worked_example():
    # Formula 14: (24.5 - 24.0) / 1.0 = 0.5 deg/min
    assert temp_drift_rate(24.5, 24.0, 1.0) == pytest.approx(0.5)
