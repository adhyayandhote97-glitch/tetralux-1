"""Spectral / color validation for the OPT4048 sensors (formulas 15-16)."""

from __future__ import annotations

from tetralux.constants import MIN_EPSILON


def cie_chromaticity(X: float, Y: float, Z: float) -> tuple[float, float]:
    """Formula 15 - CIE chromaticity coordinates."""
    total = X + Y + Z
    if abs(total) < MIN_EPSILON:
        raise ValueError("X + Y + Z must be non-zero to define chromaticity")
    return X / total, Y / total


def mccamy_n(x_cie: float, y_cie: float) -> float:
    """Formula 16 - McCamy intermediate value for CCT estimation."""
    denom = y_cie - 0.1858
    if abs(denom) < MIN_EPSILON:
        raise ValueError("y_cie must differ from 0.1858 (McCamy pole)")
    return (x_cie - 0.3320) / denom


def mccamy_cct(x_cie: float, y_cie: float) -> float:
    """Correlated colour temperature (K) via McCamy's 1992 cubic."""
    n = mccamy_n(x_cie, y_cie)
    cct = -449.0 * n ** 3 + 3525.0 * n ** 2 - 6823.3 * n + 5520.33
    if cct < 0.0 or cct > 25000.0:
        return float("nan")
    return cct


def trust_gate(
    cct_avg: float,
    reference: float = 5500.0,
    tolerance: float = 500.0,
) -> str:
    """OPT4048 illumination-trust gate."""
    if cct_avg != cct_avg:  # nan
        return "ADVISORY"
    return "PASS" if abs(cct_avg - reference) <= tolerance else "FAIL"
