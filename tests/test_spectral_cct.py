"""Tests for OPT4048 CCT + trust gate (Phase 6)."""

import math


from tetralux.spectral.cie import mccamy_cct, trust_gate
from tetralux.spectral.opt import analyze_opt


def _opt_from_xyY(x, y, Y=100.0):
    X = x * Y / y
    Z = (1.0 - x - y) * Y / y
    return {"X": X, "Y": Y, "Z": Z, "lux": 100.0}


def test_mccamy_cct_daylight_and_incandescent():
    # CIE daylight ~5500 K (signed McCamy).
    assert 5000.0 < mccamy_cct(0.3324, 0.3474) < 6000.0
    # Illuminant A must be ~2856 K (only the correctly-signed form gives this).
    assert 2700.0 < mccamy_cct(0.4476, 0.4074) < 3000.0


def test_trust_gate():
    assert trust_gate(5500.0) == "PASS"
    assert trust_gate(5900.0) == "PASS"     # within 500 K
    assert trust_gate(3000.0) == "FAIL"     # outside
    assert trust_gate(float("nan")) == "ADVISORY"


def test_analyze_opt_daylight_passes():
    opt = [_opt_from_xyY(0.3324, 0.3474)] * 4
    result = analyze_opt(opt)
    assert 5000.0 < result.cct_average < 6000.0
    assert result.gate == "PASS"
    assert result.trusted is True


def test_analyze_opt_warm_source_fails():
    opt = [_opt_from_xyY(0.4476, 0.4074)] * 4  # Illuminant A ~2856 K
    result = analyze_opt(opt)
    assert result.gate == "FAIL"
    assert result.trusted is False


def test_analyze_opt_invalid_is_advisory():
    opt = [{"X": 0.0, "Y": 0.0, "Z": 0.0, "lux": 0.0}] * 4
    result = analyze_opt(opt)
    assert result.gate == "ADVISORY"
    assert math.isnan(result.cct_average)
