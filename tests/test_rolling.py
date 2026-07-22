"""Tests for rolling + burst validation metrics (Phase 6)."""

import numpy as np
import pytest

from tetralux.estimation.estimator import angles_to_vector
from tetralux.validation.rolling import RollingValidator, burst_metrics


def test_rolling_validator_tracks_error_bias_repeatability():
    rv = RollingValidator([1.0, 0.0, 0.0])
    r0 = rv.update(np.array([1.0, 0.0, 0.0]))
    assert r0["angular_error_deg"] == pytest.approx(0.0, abs=1e-9)

    r1 = rv.update(angles_to_vector(10.0, 0.0))
    assert r1["angular_error_deg"] == pytest.approx(10.0, abs=1e-6)
    assert r1["bias_deg"] == pytest.approx(5.0, abs=1e-6)      # mean of [0, 10]
    assert r1["repeatability_deg"] == pytest.approx(5.0, abs=1e-6)  # std of [0, 10]


def test_rolling_validator_handles_none():
    rv = RollingValidator([1.0, 0.0, 0.0])
    r = rv.update(None)
    assert r["angular_error_deg"] is None
    assert r["bias_deg"] is None


def test_burst_metrics_small_under_noise():
    true = angles_to_vector(30.0, 20.0)
    rng = np.random.default_rng(0)

    def sample():
        # jitter the true direction slightly
        v = true + rng.normal(0.0, 0.01, size=3)
        return v / np.linalg.norm(v)

    m = burst_metrics(sample, true, n=50)
    assert m["n"] == 50
    assert m["repeatability_deg"] >= 0.0
    assert m["bias_deg"] < 2.0
