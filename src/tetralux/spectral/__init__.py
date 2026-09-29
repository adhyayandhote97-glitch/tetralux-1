"""Spectral colour validation for OPT4048 (formulas 15-16 + CCT trust gate).

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `spectral/` as a package and re-exports both of its modules.

This subpackage asks the question the geometry cannot: is the light we are
pointing at actually the sun? The estimator will confidently point at a desk
lamp, and only colour can reveal that. Two modules:

    cie.py  the colour maths for one sensor: chromaticity, McCamy CCT, trust gate
    opt.py  applying that to all four OPT4048 sensors and producing one verdict

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.spectral.cie import cie_chromaticity, mccamy_cct, mccamy_n, trust_gate
from tetralux.spectral.opt import OPTResult, analyze_opt

# In processing order: raw X/Y/Z to chromaticity, chromaticity to n, n to a
# colour temperature, temperature to a verdict; then the four-sensor wrapper and
# its result type.
__all__ = [
    "cie_chromaticity",   # formula 15
    "mccamy_n",           # formula 16
    "mccamy_cct",         # formula 17, the cubic (watch the signs)
    "trust_gate",         # formula 18
    "analyze_opt",        # all four sensors, with failures tolerated
    "OPTResult",
]
