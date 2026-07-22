"""Tests for temperature analysis (Phase 6)."""

import math

import pytest

from tetralux.thermal.analysis import SENSOR_IDS, TemperatureAnalyzer


def test_first_update_has_no_drift():
    an = TemperatureAnalyzer()
    status = an.update([25.0] * 6, 0)
    assert all(math.isnan(status.drift_rates[s]) for s in SENSOR_IDS)
    assert not status.any_drift


def test_drift_rate_and_flag():
    an = TemperatureAnalyzer()
    an.update([25.0] * 6, 0)
    status = an.update([26.0] * 6, 60000)  # +1.0 degC over 1 min
    assert status.drift_rates["T1"] == pytest.approx(1.0)
    assert status.drift_flags["T1"] is True  # 1.0 > 0.5 threshold
    assert status.any_drift
    assert status.rolling_means["T1"] == pytest.approx(25.5)


def test_small_drift_not_flagged():
    an = TemperatureAnalyzer()
    an.update([25.0] * 6, 0)
    status = an.update([25.2] * 6, 60000)  # 0.2 degC/min < 0.5
    assert not status.drift_flags["T1"]


def test_missing_sensor_handled():
    an = TemperatureAnalyzer()
    status = an.update([None] * 6, 0)
    assert status.missing == SENSOR_IDS
    assert all(v is None for v in status.temperatures.values())
