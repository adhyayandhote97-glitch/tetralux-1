"""The processing pipeline (Phase 6).

`process(frame, ctx)` turns one `SensorFrame` (real or virtual) into a complete
`GroundStationRecord`, chaining the earlier phases:

    calibrate -> estimate (+ az/el) -> validate -> faults -> thermal -> OPT trust

It is pure w.r.t. the frame; the only state lives in `PipelineContext`
(rolling validator, thermal analyzer, stream monitor) for streaming Real mode.
Virtual mode passes a context without those and supplies the true direction as
the angular-error reference.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from tetralux import calibration as calib
from tetralux.constants import (
    CCT_REFERENCE_DAYLIGHT,
    CCT_TOLERANCE_DEFAULT,
    FACE_NAMES,
    FACE_NORMALS,
    MIN_EPSILON,
    SATURATION_ADC,
)
from tetralux.estimation.estimator import (
    LowSignalError,
    direction_vector,
    sun_angles,
    sun_vector as _sun_vector,
)
from tetralux.faults.detector import assess_frame
from tetralux.frames import SensorFrame
from tetralux.ingest.monitor import StreamMonitor
from tetralux.record import GroundStationRecord
from tetralux.spectral.opt import analyze_opt
from tetralux.thermal.analysis import TemperatureAnalyzer
from tetralux.validation.metrics import angular_error
from tetralux.validation.rolling import RollingValidator

# Total corrected signal below this flags LOW_SIGNAL for display (v0 used the
# equivalent confidence < 0.05, i.e. total < 0.05 * 6 * 500).
LOW_SIGNAL_TOTAL = 150.0
_CONFIDENCE_SCALE = 6 * 500.0


@dataclass
class PipelineContext:
    """Configuration + streaming state for the pipeline."""

    calibration: calib.Calibration = field(default_factory=calib.Calibration)
    reference_vector: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    rolling_validator: Optional[RollingValidator] = None
    thermal_analyzer: Optional[TemperatureAnalyzer] = None
    monitor: Optional[StreamMonitor] = None
    opt_reference: float = CCT_REFERENCE_DAYLIGHT
    opt_tolerance: float = CCT_TOLERANCE_DEFAULT
    low_signal_total: float = LOW_SIGNAL_TOTAL
    opposition_threshold: float = 0.20


def make_streaming_context(
    reference_vector: Optional[np.ndarray] = None,
    calibration: Optional[calib.Calibration] = None,
    monitor: Optional[StreamMonitor] = None,
) -> PipelineContext:
    """Context for Real (streaming) mode: rolling validator + thermal analyzer."""
    ref = np.array([1.0, 0.0, 0.0]) if reference_vector is None else np.asarray(reference_vector, float)
    return PipelineContext(
        calibration=calibration or calib.Calibration(),
        reference_vector=ref,
        rolling_validator=RollingValidator(ref),
        thermal_analyzer=TemperatureAnalyzer(),
        monitor=monitor,
    )


def process(
    frame: SensorFrame,
    ctx: Optional[PipelineContext] = None,
    reference: Optional[np.ndarray] = None,
) -> GroundStationRecord:
    """Process one frame into a full :class:`GroundStationRecord`.

    Args:
        frame: The decoded/synthesized sensor frame.
        ctx: Pipeline context (defaults to a fresh stateless one).
        reference: Ground-truth direction for angular error (Virtual mode passes
            the true light direction). Falls back to ``ctx.reference_vector``.
    """
    ctx = ctx or PipelineContext()
    t0 = time.perf_counter()

    pd_map = frame.photodiode_map()
    saturated_faces = [f for f in FACE_NAMES if pd_map[f] >= SATURATION_ADC]
    est_frame = {f: {"reading": pd_map[f], "saturated": f in saturated_faces} for f in FACE_NAMES}

    # --- calibration (formulas 1 & 5) ---
    corrected = calib.corrected_readings(pd_map, ctx.calibration)
    cosine = calib.cosine_proxy(corrected, ctx.calibration)
    irradiance = calib.irradiance(cosine, ctx.calibration)
    total = float(sum(corrected.values()))

    # --- weights + sun vector (formulas 2-4) ---
    if total >= MIN_EPSILON:
        weights = {f: corrected[f] / total for f in FACE_NAMES}
    else:
        weights = {f: 0.0 for f in FACE_NAMES}

    vector = None
    azimuth = elevation = None
    if total >= MIN_EPSILON:
        d = direction_vector([weights[f] for f in FACE_NAMES],
                             [FACE_NORMALS[f] for f in FACE_NAMES])
        try:
            vec = _sun_vector(d)
            vector = [float(c) for c in vec]
            azimuth, elevation = sun_angles(vec)
        except LowSignalError:
            vector = None

    confidence = min(1.0, total / _CONFIDENCE_SCALE)

    # --- fault / health (reuses assess_frame; same floored calibration) ---
    health = assess_frame(
        est_frame, dark_offset=ctx.calibration.dark, gain=ctx.calibration.gain,
        low_signal_threshold=ctx.low_signal_total,
        opposition_threshold=ctx.opposition_threshold,
    )

    # --- validation metrics ---
    reference = ctx.reference_vector if reference is None else reference
    angular_error_deg = bias_deg = repeatability_deg = None
    if vector is not None:
        vec_arr = np.asarray(vector, dtype=float)
        if ctx.rolling_validator is not None:
            rm = ctx.rolling_validator.update(vec_arr)
            angular_error_deg = rm["angular_error_deg"]
            bias_deg = rm["bias_deg"]
            repeatability_deg = rm["repeatability_deg"]
        elif reference is not None:
            angular_error_deg = float(np.degrees(angular_error(vec_arr, reference)))

    # --- thermal ---
    thermal = None
    if ctx.thermal_analyzer is not None:
        status = ctx.thermal_analyzer.update(frame.temperatures, frame.timestamp_ms)
        thermal = {
            "temperatures": status.temperatures,
            "drift_rates": status.drift_rates,
            "rolling_means": status.rolling_means,
            "drift_flags": status.drift_flags,
            "missing": status.missing,
            "any_drift": status.any_drift,
        }

    # --- OPT4048 trust ---
    opt = analyze_opt(frame.opt, ctx.opt_reference, ctx.opt_tolerance)
    opt_out = {
        "cct_average": opt.cct_average,
        "cct_values": opt.cct_values,
        "gate": opt.gate,
        "trusted": opt.trusted,
        "delta": opt.delta,
        "light_source": opt.light_source,
        "reference": opt.reference,
        "tolerance": opt.tolerance,
    }

    stream = ctx.monitor.stats() if ctx.monitor is not None else None

    return GroundStationRecord(
        seq=frame.seq,
        timestamp_ms=frame.timestamp_ms,
        received_at=frame.received_at.isoformat(),
        source=frame.source,
        photodiodes=dict(pd_map),
        lux=frame.lux_map(),
        magnetometer=dict(frame.magnetometer),
        corrected=corrected,
        cosine_proxy=cosine,
        irradiance=irradiance,
        weights=weights,
        sun_vector=vector,
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        confidence=confidence,
        angular_error_deg=angular_error_deg,
        bias_deg=bias_deg,
        repeatability_deg=repeatability_deg,
        saturated_faces=saturated_faces,
        saturation_flag=bool(saturated_faces),
        checksum=frame.checksum,
        checksum_ok=True,
        faults=[c.value for c in health.faults],
        health_ok=health.ok,
        opposition_ratio=health.opposition_ratio,
        thermal=thermal,
        opt=opt_out,
        stream=stream,
        processing_time_ms=(time.perf_counter() - t0) * 1000.0,
    )
