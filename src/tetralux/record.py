"""The fully-processed ground-station record (Phase 6).

`GroundStationRecord` is the single object the dashboard renders and the store
logs. It carries everything the UI shows: raw sensors, calibrated values,
weights, the sun vector + angles, validation metrics, fault/health, thermal, OPT
trust, and a stream-stats snapshot. `to_dict()` yields a JSON-safe mapping
(NaN -> null, numpy -> python) for logging.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np


def _clean(value):
    """Recursively make a value JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    return value


@dataclass
class GroundStationRecord:
    """One processed frame — the complete state for one sample."""

    seq: int
    timestamp_ms: int
    received_at: str            # ISO-8601
    source: str                 # "real" | "virtual"

    # Raw sensors
    photodiodes: dict           # face -> ADC counts
    lux: dict                   # face -> lx
    magnetometer: dict          # {"x","y","z"} raw int

    # Calibrated
    corrected: dict             # face -> R_i (calibrated counts)
    cosine_proxy: dict          # face -> cos(theta_i), dimensionless
    irradiance: dict            # face -> W/m^2
    weights: dict               # face -> w_i, dimensionless (sum = 1)

    # Estimate
    sun_vector: Optional[list]  # [x, y, z] unit, or None (low signal)
    azimuth_deg: Optional[float]
    elevation_deg: Optional[float]
    confidence: float           # dimensionless 0-1

    # Validation
    angular_error_deg: Optional[float]
    bias_deg: Optional[float]
    repeatability_deg: Optional[float]

    # Faults / integrity
    saturated_faces: list
    saturation_flag: bool
    checksum: int               # transmitted 8-bit checksum
    checksum_ok: bool
    faults: list                # fault-code strings
    health_ok: bool
    opposition_ratio: float     # multi-source indicator, dimensionless

    # Context sensors
    thermal: Optional[dict]     # temps/drift/flags
    opt: dict                   # cct_avg (K), gate, trusted, light_source
    stream: Optional[dict]      # StreamMonitor snapshot

    processing_time_ms: float

    def to_dict(self) -> dict:
        """JSON-safe dict for logging (NaN -> null, numpy -> python)."""
        return _clean(asdict(self))
