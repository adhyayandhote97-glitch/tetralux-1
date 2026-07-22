"""Spectral colour validation for OPT4048 (formulas 15-16 + CCT trust gate)."""

from tetralux.spectral.cie import cie_chromaticity, mccamy_cct, mccamy_n, trust_gate
from tetralux.spectral.opt import OPTResult, analyze_opt

__all__ = [
    "cie_chromaticity",
    "mccamy_n",
    "mccamy_cct",
    "trust_gate",
    "analyze_opt",
    "OPTResult",
]
