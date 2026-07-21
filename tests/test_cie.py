"""Tests for spectral color validation (formulas 15-16)."""

import pytest

from tetralux.spectral.cie import cie_chromaticity, mccamy_n


def test_cie_chromaticity_worked_example():
    # Formula 15: X=30, Y=40, Z=30 -> x=0.30, y=0.40
    x_cie, y_cie = cie_chromaticity(30.0, 40.0, 30.0)
    assert x_cie == pytest.approx(0.30)
    assert y_cie == pytest.approx(0.40)


def test_cie_chromaticity_zero_raises():
    with pytest.raises(ValueError):
        cie_chromaticity(0.0, 0.0, 0.0)


def test_mccamy_n_worked_example():
    # Formula 16: n = (x - 0.3320) / (y - 0.1858)
    # For x=0.30, y=0.40 the formula gives (-0.032)/(0.2142) = -0.14939.
    # NOTE: the brief's worked example (-0.179) does not match this formula;
    # we assert the mathematically correct value from the locked formula.
    assert mccamy_n(0.30, 0.40) == pytest.approx(-0.14939, abs=1e-4)
