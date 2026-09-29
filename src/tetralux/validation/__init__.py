"""Validation metrics for estimation quality (formulas 11-14).

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `validation/` as a package and re-exports both of its modules.

This subpackage answers "how good is the estimate?", which is what separates a
measurement from a guess. Two modules with a clear division:

    metrics.py  the formulas themselves, stateless: numbers in, number out
    rolling.py  the history keeping, because bias and repeatability are
                meaningless from a single frame and need a window of past ones

Note the re-exports pull from BOTH modules, so a caller sees one flat namespace
and does not need to know which file a given name lives in.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.validation.metrics import (
    angular_error,
    bias,
    repeatability,
    temp_drift_rate,
)
from tetralux.validation.rolling import RollingValidator, burst_metrics

# Formulas in numeric order first, then the two history-keeping tools.
__all__ = [
    "angular_error",      # formula 11
    "repeatability",      # formula 12
    "bias",               # formula 13
    "temp_drift_rate",    # formula 14
    "RollingValidator",   # a live stream's sliding window
    "burst_metrics",      # a deliberate bench measurement
]
