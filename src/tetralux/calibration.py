"""Photodiode calibration (Phase 6)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Union

from tetralux.constants import FACE_NAMES, MIN_EPSILON, SOLAR_CONSTANT
from tetralux.estimation.estimator import corrected_reading

# v0 lab-calibration defaults (per face, canonical order).
DEFAULT_DARK = {"+x": 5.0, "-x": 4.0, "+y": 6.0, "-y": 5.0, "+z": 7.0, "-z": 6.0}
DEFAULT_GAIN = {"+x": 1.00, "-x": 0.98, "+y": 1.02, "-y": 0.99, "+z": 1.01, "-z": 0.97}
DEFAULT_MAX = {"+x": 1000.0, "-x": 980.0, "+y": 1005.0, "-y": 995.0, "+z": 1010.0, "-z": 970.0}
DEFAULT_LAB_SCALING = 0.1  # I_lamp / I_sun (see docs/architecture.md calibration notes)


@dataclass
class Calibration:
    """Per-face calibration parameters."""

    dark: dict = field(default_factory=lambda: dict(DEFAULT_DARK))
    gain: dict = field(default_factory=lambda: dict(DEFAULT_GAIN))
    max_illumination: dict = field(default_factory=lambda: dict(DEFAULT_MAX))
    lab_scaling_factor: float = DEFAULT_LAB_SCALING

    def to_json(self) -> str:
        """Serialize to a JSON string (one key per parameter, per-face dicts)."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Calibration":
        """Reconstruct from a JSON string produced by :meth:`to_json`."""
        data = json.loads(text)
        return cls(
            dark=dict(data["dark"]),
            gain=dict(data["gain"]),
            max_illumination=dict(data["max_illumination"]),
            lab_scaling_factor=float(data["lab_scaling_factor"]),
        )

    def save(self, path: Union[str, Path]) -> None:
        """Write this calibration to a JSON file."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Calibration":
        """Load a calibration previously written by :meth:`save`."""
        text = Path(path).read_text(encoding="utf-8")
        try:
            return cls.from_json(text)
        except KeyError as exc:
            raise ValueError(f"calibration file {path} missing field: {exc}") from exc


def corrected_readings(photodiodes: dict, cal: Calibration) -> dict:
    """Formula 1 per face, floored at 0: ``R_i = max(0, (V_i - D_i) * G_i)``."""
    return {
        f: max(0.0, corrected_reading(float(photodiodes[f]), cal.dark[f], cal.gain[f]))
        for f in FACE_NAMES
    }


def cosine_proxy(corrected: dict, cal: Calibration) -> dict:
    """Formula 5 per face, clamped to [0, 1]: ``cos(theta_i) = R_i / V_max_i``."""
    out = {}
    for f in FACE_NAMES:
        v_max = max(cal.max_illumination[f], MIN_EPSILON)
        out[f] = min(1.0, max(0.0, corrected[f] / v_max))
    return out


def irradiance(cosine: dict, cal: Calibration) -> dict:
    """Per-face irradiance (W/m^2): ``I_i = SOLAR_CONSTANT * f_lab * cos(theta_i)``."""
    return {f: SOLAR_CONSTANT * cal.lab_scaling_factor * cosine[f] for f in FACE_NAMES}
