"""Thermal monitoring (DS18B20 x6): drift, rolling stats, status.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `thermal/` as a package and re-exports everything in analysis.py.

WHY A SUN SENSOR MONITORS TEMPERATURE. A photodiode's sensitivity shifts as it
warms, so a calibration measured at 20 degrees becomes progressively less true
at 35. The estimate then drifts silently: the numbers stay plausible while
getting steadily worse, and nothing in the estimate itself reveals it.

Watching temperature is what makes that visible, so the system can flag its own
output as less trustworthy rather than reporting a drifting answer with
unchanged confidence.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.thermal.analysis import (
    SENSOR_FACE,
    SENSOR_IDS,
    TemperatureAnalyzer,
    ThermalStatus,
)

__all__ = [
    "TemperatureAnalyzer",  # stateful: drift needs a previous reading
    "ThermalStatus",        # one snapshot of all six sensors
    "SENSOR_IDS",           # canonical order, T1 to T6
    "SENSOR_FACE",          # which cube face each sensor is mounted on
]
