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

    Example: ``x_cie=0.30, y_cie=0.40 -> (-0.0320)/(0.2142) ~ -0.1494``.

    Raises:
        ValueError: if ``y_cie == 0.1858`` (division by zero).
    """
    denom = y_cie - 0.1858
    if abs(denom) < MIN_EPSILON:
        raise ValueError("y_cie must differ from 0.1858 (McCamy pole)")
    return (x_cie - 0.3320) / denom


def mccamy_cct(x_cie: float, y_cie: float) -> float:
    """Correlated colour temperature (K) via McCamy's 1992 cubic.

    ``CCT = -449 n^3 + 3525 n^2 - 6823.3 n + 5520.33`` with
    ``n = mccamy_n(x, y)``.

    Note on signs: this uses the standard McCamy coefficients
    (``-449, +3525, -6823.3, +5520.33``). The v0 prototype used all-positive
    signs, which returns physically wrong temperatures (e.g. Illuminant A at
    x=0.4476, y=0.4074 must give ~2856 K, which only the signed form produces).
    Formula 16 (the intermediate ``n``) is unchanged.

    Returns:
        CCT in kelvin, or ``nan`` if outside the plausible 0-25000 K range.
    """
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
    """OPT4048 illumination-trust gate.

    Returns ``"PASS"`` when the average CCT is within ``tolerance`` of
    ``reference`` (default daylight 5500 K +/- 500 K), ``"FAIL"`` when outside,
    or ``"ADVISORY"`` when no valid CCT is available (``nan``).
    """
    if cct_avg != cct_avg:  # nan
        return "ADVISORY"
    return "PASS" if abs(cct_avg - reference) <= tolerance else "FAIL"
