"""Units registry + formatters (Phase 9, Decision 7)."""

from __future__ import annotations

import math
from typing import Optional

# Canonical unit strings by quantity.
UNITS = {
    "photodiode": "ADC counts",
    "corrected": "ADC counts",
    "lux": "lx",
    "irradiance": "W/m²",
    "weight": "dimensionless",
    "cosine": "dimensionless",
    "sun_component": "dimensionless (unit vector)",
    "angle": "°",
    "temperature": "°C",
    "drift": "°C/min",
    "cct": "K",
    "force": "nN",
    "rate": "Hz",
    "timestamp_ms": "ms",
    "seq": "index (dimensionless)",
    "checksum": "8-bit",
    "flags": "bitfield",
    "confidence": "dimensionless (0-1)",
    "opposition": "dimensionless (0-1)",
    "mag": "raw",
    "bytes": "B",
    "count": "count",
    "duration": "s",
}


def fmt(value, unit: Optional[str] = None, nd: int = 3) -> str:
    """Format a value with its unit; None/NaN render as an em dash."""
    if value is None:
        return "-"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "-"
        text = f"{value:.{nd}f}"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    return f"{text} {unit}" if unit else text


def unit_of(quantity: str) -> str:
    """Look up the unit string for a named quantity."""
    return UNITS.get(quantity, "")


def q(value, quantity: str, nd: int = 3) -> str:
    """Format ``value`` with the unit registered for ``quantity``."""
    return fmt(value, UNITS.get(quantity), nd)


def human_bytes(n: int) -> str:
    """Human-readable byte size."""
    b = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TiB"
