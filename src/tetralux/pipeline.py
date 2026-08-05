"""The processing pipeline (Phase 6)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from tetralux import calibration as calib
from tetralux.constants import (
    CCT_REFERENCE_DAYLIGHT,
    CCT_TOLERANCE_DEFAULT,
    CUBESAT_FACE_AREA,
    DEFAULT_REFLECTIVITY,
    FACE_NAMES,
    FACE_NORMALS,
    MIN_EPSILON,
    SATURATION_ADC,
    SPEED_OF_LIGHT,
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
from tetralux.physics.srp import (
    srp_azimuth,
    srp_elevation,
    srp_force_per_face,
    srp_magnitude,
    srp_net_force,
)
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
    face_area: float = CUBESAT_FACE_AREA
    reflectivity: float = DEFAULT_REFLECTIVITY


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
    """Process one frame into a full :class:`GroundStationRecord`."""
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

    # --- solar radiation pressure (formulas 6-10) ---
    # Irradiance above is the I_i these need; saturated faces are excluded
    # because a clipped reading understates the true irradiance.
    srp_forces = {
        f: (0.0 if f in saturated_faces else srp_force_per_face(
            irradiance[f], ctx.face_area, SPEED_OF_LIGHT, ctx.reflectivity))
        for f in FACE_NAMES
    }
    srp_net = srp_net_force([srp_forces[f] for f in FACE_NAMES],
                            [FACE_NORMALS[f] for f in FACE_NAMES])
    srp_mag = srp_magnitude(srp_net)
    if srp_mag > MIN_EPSILON:
        srp_az = float(np.degrees(srp_azimuth(srp_net[0], srp_net[1])))
        srp_el = float(np.degrees(srp_elevation(srp_net[2], srp_mag)))
    else:
        srp_az = srp_el = None

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
        srp_forces=srp_forces,
        srp_net=[float(c) for c in srp_net],
        srp_magnitude_n=srp_mag,
        srp_azimuth_deg=srp_az,
        srp_elevation_deg=srp_el,
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
