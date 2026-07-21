"""Spectral / color validation for the OPT4048 sensors (formulas 15-16).

Not used by direction estimation. Turns tristimulus (X, Y, Z) into CIE
chromaticity coordinates and the McCamy intermediate value used to estimate
correlated color temperature (CCT).
"""

from __future__ import annotations

from tetralux.constants import MIN_EPSILON


def cie_chromaticity(X: float, Y: float, Z: float) -> tuple[float, float]:
    """Formula 15 — CIE chromaticity coordinates.

    ``x_cie = X / (X + Y + Z)``, ``y_cie = Y / (X + Y + Z)``.

    Example: ``X=30, Y=40, Z=30 -> (0.30, 0.40)``.

    Raises:
        ValueError: if ``X + Y + Z`` is ~0 (undefined chromaticity).
    """
    total = X + Y + Z
    if abs(total) < MIN_EPSILON:
        raise ValueError("X + Y + Z must be non-zero to define chromaticity")
    return X / total, Y / total


def mccamy_n(x_cie: float, y_cie: float) -> float:
    """Formula 16 — McCamy intermediate value for CCT estimation.

    ``n = (x_cie - 0.3320) / (y_cie - 0.1858)``.

    Note: for ``x_cie=0.30, y_cie=0.40`` this evaluates to ``-0.1494`` (the
    project brief's worked example of ``-0.179`` does not match this formula;
    see the summary/notes for that phase).

    Raises:
        ValueError: if ``y_cie == 0.1858`` (division by zero).
    """
    denom = y_cie - 0.1858
    if abs(denom) < MIN_EPSILON:
        raise ValueError("y_cie must differ from 0.1858 (McCamy pole)")
    return (x_cie - 0.3320) / denom
