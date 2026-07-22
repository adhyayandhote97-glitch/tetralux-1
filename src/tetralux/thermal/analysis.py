"""Temperature analysis for the six DS18B20 sensors (Phase 6).

Tracks a rolling history per sensor and, on each update, reports drift rate
(°C/min, reusing formula 14), rolling mean, and a drift flag (>0.5 °C/min).
Missing sensors (firmware sends JSON ``null``) are handled explicitly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from tetralux.constants import DRIFT_THRESHOLD_C_PER_MIN, ROLLING_WINDOW_SIZE
from tetralux.validation.metrics import temp_drift_rate

SENSOR_IDS = ["T1", "T2", "T3", "T4", "T5", "T6"]

# Each DS18B20 is mounted on a cube-face frame.
SENSOR_FACE = {
    "T1": "+x frame", "T2": "-x frame", "T3": "+y frame",
    "T4": "-y frame", "T5": "+z frame", "T6": "-z frame",
}


@dataclass
class ThermalStatus:
    """Per-update thermal report (all dicts keyed by sensor id)."""

    temperatures: dict     # T1..T6 -> degC or None
    drift_rates: dict      # degC/min (nan if unknown)
    rolling_means: dict    # degC (nan if empty)
    drift_flags: dict      # bool, |drift| > threshold
    missing: list          # sensor ids reporting None
    any_drift: bool        # any drift flag set


class TemperatureAnalyzer:
    """Stateful analyzer keeping a rolling window of readings per sensor."""

    def __init__(self, window: int = ROLLING_WINDOW_SIZE,
                 drift_threshold: float = DRIFT_THRESHOLD_C_PER_MIN) -> None:
        self._window = window
        self._threshold = drift_threshold
        self._history = {sid: deque(maxlen=window) for sid in SENSOR_IDS}
        self._last: dict = {sid: None for sid in SENSOR_IDS}  # (temp, timestamp_ms)

    def update(self, temperatures: list, timestamp_ms: int) -> ThermalStatus:
        """Ingest one reading per sensor and return the current status.

        Args:
            temperatures: 6 values (degC) in ``SENSOR_IDS`` order; ``None`` if the
                sensor is missing.
            timestamp_ms: Device timestamp for this sample.
        """
        temps, drifts, means, flags, missing = {}, {}, {}, {}, []

        for i, sid in enumerate(SENSOR_IDS):
            t = temperatures[i] if i < len(temperatures) else None
            if t is None or (isinstance(t, float) and t != t):
                temps[sid] = None
                drifts[sid] = float("nan")
                means[sid] = self._mean(sid)
                flags[sid] = False
                missing.append(sid)
                continue

            t = float(t)
            temps[sid] = t

            drift = float("nan")
            prev = self._last[sid]
            if prev is not None:
                prev_t, prev_ts = prev
                dt_min = (timestamp_ms - prev_ts) / 60000.0
                if dt_min > 1e-9:
                    drift = temp_drift_rate(t, prev_t, dt_min)
            drifts[sid] = drift
            flags[sid] = drift == drift and abs(drift) > self._threshold

            self._history[sid].append(t)
            means[sid] = self._mean(sid)
            self._last[sid] = (t, timestamp_ms)

        return ThermalStatus(
            temperatures=temps, drift_rates=drifts, rolling_means=means,
            drift_flags=flags, missing=missing,
            any_drift=any(flags.values()),
        )

    def _mean(self, sid: str) -> float:
        hist = self._history[sid]
        return float(np.mean(hist)) if hist else float("nan")

    def reset(self) -> None:
        for sid in SENSOR_IDS:
            self._history[sid].clear()
            self._last[sid] = None
