"""Cross-phase constants for Tetralux-1."""

from __future__ import annotations

import numpy as np

# Canonical face ordering. Used everywhere so per-face iteration and any future
# fixed-length telemetry packing stay consistent.
FACE_NAMES: list[str] = ["+x", "-x", "+y", "-y", "+z", "-z"]

# Outward unit normal for each face, in the CubeSat body frame.
FACE_NORMALS: dict[str, np.ndarray] = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}

# Low-signal / divide-by-zero guard threshold (see docs/architecture.md §3).
MIN_EPSILON: float = 1e-9

# Photodiode ADC (Arduino Nano 33 IoT is 10-bit). Saturation trips just below
# the hard rail (see docs/architecture.md §2).
ADC_MAX: int = 1023
SATURATION_ADC: int = 1020

# Physical constants (SI).
SOLAR_CONSTANT: float = 1361.0   # W/m^2, mean solar irradiance at 1 AU
CUBESAT_FACE_AREA: float = 0.01  # m^2, one 1U face (0.1 m x 0.1 m)
SPEED_OF_LIGHT: float = 3.0e8    # m/s

# Surface reflectivity used for solar radiation pressure (0 absorbs, 1 reflects).
# 0.30 corresponds to anodised aluminium.
DEFAULT_REFLECTIVITY: float = 0.30

# OPT4048 colour-trust reference (correlated colour temperature).
CCT_REFERENCE_DAYLIGHT: float = 5500.0  # K
CCT_TOLERANCE_DEFAULT: float = 500.0    # K

# Rolling-window size (frames) for validation and thermal statistics.
ROLLING_WINDOW_SIZE: int = 60
# Temperature drift flag threshold.
DRIFT_THRESHOLD_C_PER_MIN: float = 0.5
