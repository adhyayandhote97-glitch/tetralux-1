"""The ground-station frame contract (Phase 6).

`SensorFrame` mirrors, field-for-field, the JSON the real prototype firmware
transmits (see docs/architecture.md §8). It is the single currency flowing
through the pipeline, produced two ways:

- **Real:** decoded from hardware JSON by ``telemetry.json_frame.decode_json_frame``.
- **Virtual:** synthesized by ``sim.sensors.simulate_sensor_frame``.

`RejectedFrame` is returned instead when a raw payload fails to decode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from tetralux.constants import FACE_NAMES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SensorFrame:
    """One fully-populated sensor sample from all instruments.

    Sensor arrays are in canonical face order (``FACE_NAMES``) where applicable.
    """

    seq: int                              # sequence counter (dimensionless index)
    timestamp_ms: int                     # device time since boot (ms)
    photodiodes: list                     # 6x S1223 raw ADC counts (0-1023)
    lux: list                             # 6x BH1750 illuminance (lx)
    magnetometer: dict                    # QMC5883L {"x","y","z"} raw int
    opt: list                             # 4x OPT4048 {"X","Y","Z","lux"}
    temperatures: list                    # 6x DS18B20 degC (None if missing)
    flags: int                            # uint8 status bitfield
    checksum: int                         # transmitted 8-bit checksum (0-255)
    received_at: datetime = field(default_factory=_utcnow)
    source: str = "real"                  # "real" | "virtual"

    def photodiode_map(self) -> dict:
        """Photodiode readings keyed by face name."""
        return {f: self.photodiodes[i] for i, f in enumerate(FACE_NAMES)}

    def lux_map(self) -> dict:
        """Lux readings keyed by face name."""
        return {f: self.lux[i] for i, f in enumerate(FACE_NAMES)}


@dataclass
class RejectedFrame:
    """A raw payload that failed to decode (bad JSON, structure, or checksum)."""

    seq: Optional[int]
    reason: str
    raw: str
    received_at: datetime = field(default_factory=_utcnow)
