"""Tests for photodiode calibration (Phase 6)."""

import pytest

from tetralux.calibration import (
    Calibration,
    corrected_readings,
    cosine_proxy,
    irradiance,
)
from tetralux.constants import FACE_NAMES, SOLAR_CONSTANT


def test_corrected_reading_dark_subtract_and_gain():
    cal = Calibration()  # +x: dark 5, gain 1.00, max 1000
    pd = {"+x": 905, "-x": 9, "+y": 6, "-y": 5, "+z": 7, "-z": 6}
    corr = corrected_readings(pd, cal)
    assert corr["+x"] == pytest.approx((905 - 5) * 1.00)  # 900


def test_corrected_reading_floored_at_zero():
    cal = Calibration()
    corr = corrected_readings({f: 0 for f in FACE_NAMES}, cal)  # (0 - dark)*g < 0
    assert all(v == 0.0 for v in corr.values())


def test_cosine_proxy_normalizes_and_clamps():
    cal = Calibration()
    corr = {f: 0.0 for f in FACE_NAMES}
    corr["+x"] = 900.0
    cos = cosine_proxy(corr, cal)  # 900 / 1000
    assert cos["+x"] == pytest.approx(0.9)
    assert all(0.0 <= v <= 1.0 for v in cos.values())


def test_irradiance_uses_solar_constant_and_lab_scaling():
    cal = Calibration()  # lab_scaling 0.1
    cos = {f: 0.0 for f in FACE_NAMES}
    cos["+x"] = 0.9
    irr = irradiance(cos, cal)
    assert irr["+x"] == pytest.approx(SOLAR_CONSTANT * 0.1 * 0.9)  # ~122.49 W/m^2
