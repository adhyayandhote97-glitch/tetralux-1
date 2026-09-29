"""The processing pipeline (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the spine of the project. One SensorFrame goes in, one complete
GroundStationRecord comes out, and in between every phase of the system runs in
order. If you want to understand how Tetralux-1 works end to end, read the
`process` function below from top to bottom; it is the whole system in sequence.

THE ORDER, AND WHY IT IS THAT ORDER
    1. calibration    formulas 1 and 5, plus irradiance. Everything downstream
                      needs corrected readings, so nothing can precede it.
    2. weights        formula 2, needing the total from step 1.
    3. sun vector     formulas 3 and 4, the actual answer.
    4. SRP            formulas 6 to 10, from the irradiance computed in step 1.
                      Reusing that irradiance is why the physics costs almost
                      nothing to run.
    5. faults         which of the three failure conditions apply.
    6. validation     accuracy metrics, only possible once a vector exists.
    7. thermal        drift detection.
    8. colour         is this light actually sunlight?
    9. assemble       everything into one record.

IT NEVER RAISES ON A BAD FRAME. A ground station left running for hours must
survive darkness, dropouts and clipped sensors. So each stage is guarded and
fills its field with None rather than aborting, and the record honestly reports
what could not be computed. `None` here always means "not measurable", never
"zero".

THE TWO CONTEXTS. PipelineContext carries configuration and any streaming state.
Created bare it processes single independent frames, so bias and thermal drift
stay None because they need history. Created by make_streaming_context it also
holds a RollingValidator and a TemperatureAnalyzer that remember previous
frames, which is what fills those fields in during a live session.

WHERE IT SITS IN THE FLOW
    every calculation module    is called from here
    dashboard/state.py          calls process() for both Virtual and Real modes
    groundstation.py            calls process() on each frame off the wire
    record.py                   defines the shape this produces

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# time: used for the perf_counter timing of each frame.
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# `as calib` nicknames the module so calls read as calib.corrected_readings,
# which distinguishes them from the local variable named `calibration`.
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
    # `as _sun_vector` renames it on import, because a local variable below is
    # also called sun_vector. Without the rename the variable would shadow the
    # function and the second use would fail.
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
#
# Note this is far larger than detector.py's default of MIN_EPSILON. That one is
# the bare arithmetic guard; this is a PHYSICAL judgement in ADC counts. A total
# of 150 across six faces is technically computable and practically meaningless,
# so for display purposes it counts as darkness.
LOW_SIGNAL_TOTAL = 150.0
# The scale that turns total signal into a 0-to-1 confidence: six faces at 500
# counts each. Reaching that total means fully confident.
_CONFIDENCE_SCALE = 6 * 500.0


@dataclass
class PipelineContext:
    """Configuration + streaming state for the pipeline."""

    # Every field has a default, so `PipelineContext()` gives a working
    # single-frame configuration. That is what tests and one-off processing use.
    #
    # Bundling all of this into one object rather than passing twelve arguments
    # to process() means adding a new setting later does not change process()'s
    # signature or any existing call site.
    calibration: calib.Calibration = field(default_factory=calib.Calibration)
    reference_vector: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    # Both use default_factory for the mutable-default reason explained in
    # calibration.py: a plain default would be created once and shared by every
    # context ever made.
    #
    # THE THREE Optional FIELDS ARE THE STREAMING STATE. None means "no history
    # kept", which is correct for independent frames. make_streaming_context
    # fills them in, and their presence is what makes bias, repeatability,
    # thermal drift and link statistics computable.
    rolling_validator: Optional[RollingValidator] = None
    thermal_analyzer: Optional[TemperatureAnalyzer] = None
    monitor: Optional[StreamMonitor] = None
    # The rest are tunable thresholds, defaulting to the project constants so
    # the values live in one place while still being overridable per session.
    opt_reference: float = CCT_REFERENCE_DAYLIGHT
    opt_tolerance: float = CCT_TOLERANCE_DEFAULT
    low_signal_total: float = LOW_SIGNAL_TOTAL
    opposition_threshold: float = 0.20
    face_area: float = CUBESAT_FACE_AREA
    reflectivity: float = DEFAULT_REFLECTIVITY


# --- Build a context that remembers ---
#
# PARAMETERS
#   reference_vector - the true sun direction to score estimates against.
#                      Defaults to +x if not given.
#   calibration      - this prototype's measured parameters, or None for the
#                      placeholder defaults.
#   monitor          - a StreamMonitor tracking link health, or None.
# RETURNS
#   a PipelineContext with history-keeping objects attached.
#
# A FACTORY FUNCTION: it exists to build an object in a particular
# configuration. The important detail is that RollingValidator is constructed
# with the SAME `ref` stored in reference_vector, so the validator and the
# context cannot drift apart. Building the context by hand risks setting one and
# forgetting the other, which would silently score estimates against the wrong
# truth.
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


# --- The main function: one frame in, one record out ---
#
# PARAMETERS
#   frame     - the sensor reading to process, from hardware or the simulator.
#   ctx       - configuration and streaming state. None gives a fresh default
#               context, so single frames work with no setup.
#   reference - a true direction for THIS frame only, overriding the context's.
#               Used by Virtual mode, where the sliders can move between frames
#               so the truth changes.
# RETURNS
#   one fully populated GroundStationRecord.
def process(
    frame: SensorFrame,
    ctx: Optional[PipelineContext] = None,
    reference: Optional[np.ndarray] = None,
) -> GroundStationRecord:
    """Process one frame into a full :class:`GroundStationRecord`."""
    ctx = ctx or PipelineContext()
    # perf_counter is a high-resolution timer for measuring durations. It is
    # used rather than the wall clock because it cannot jump backwards when the
    # system clock is adjusted, which would otherwise produce negative timings.
    t0 = time.perf_counter()

    # Convert the wire's positional list into a face-keyed dict (frames.py).
    pd_map = frame.photodiode_map()
    # Detect saturation from the RAW counts, before any calibration. That order
    # matters: saturation is a fact about the ADC hitting its ceiling, and
    # applying gain afterwards would move a clipped 1023 away from the threshold
    # and hide it.
    saturated_faces = [f for f in FACE_NAMES if pd_map[f] >= SATURATION_ADC]
    # Repackage into the nested shape the fault detector expects, so one
    # assess_frame serves both simulator output and real telemetry.
    est_frame = {f: {"reading": pd_map[f], "saturated": f in saturated_faces} for f in FACE_NAMES}

    # --- calibration (formulas 1 & 5) ---
    # Each line feeds the next: corrected -> cosine -> irradiance.
    corrected = calib.corrected_readings(pd_map, ctx.calibration)
    cosine = calib.cosine_proxy(corrected, ctx.calibration)
    irradiance = calib.irradiance(cosine, ctx.calibration)
    total = float(sum(corrected.values()))

    # --- weights + sun vector (formulas 2-4) ---
    # Formula 2 inline rather than calling face_weight, because that function
    # RAISES on a zero total while the pipeline must keep running. All-zero
    # weights honestly represent "no light detected".
    if total >= MIN_EPSILON:
        weights = {f: corrected[f] / total for f in FACE_NAMES}
    else:
        weights = {f: 0.0 for f in FACE_NAMES}

    vector = None
    # Chained assignment: both names are set to None in one statement.
    azimuth = elevation = None
    if total >= MIN_EPSILON:
        # Formula 3. Both lists are built by iterating FACE_NAMES, which
        # guarantees the weights and the normals line up by position.
        d = direction_vector([weights[f] for f in FACE_NAMES],
                             [FACE_NORMALS[f] for f in FACE_NAMES])
        try:
            # Formula 4. The SECOND guard is needed even though total was
            # checked: signal can be healthy while the direction still cancels
            # to nothing, in diffuse light with no clear source.
            vec = _sun_vector(d)
            # Convert the numpy array to a plain list of floats, because the
            # record must be JSON-serializable.
            vector = [float(c) for c in vec]
            azimuth, elevation = sun_angles(vec)
        except LowSignalError:
            vector = None

    # A rough 0-to-1 quality figure. Capped at 1.0 so an extremely bright frame
    # does not report 1.4, which would be meaningless for a confidence.
    confidence = min(1.0, total / _CONFIDENCE_SCALE)

    # --- solar radiation pressure (formulas 6-10) ---
    # Irradiance above is the I_i these need; saturated faces are excluded
    # because a clipped reading understates the true irradiance.
    #
    # Excluding rather than including a wrong value: a saturated face's real
    # irradiance is unknown and higher than measured, so using the clipped
    # number would silently understate the force. Zero at least does not claim
    # to know something it cannot.
    srp_forces = {
        f: (0.0 if f in saturated_faces else srp_force_per_face(
            irradiance[f], ctx.face_area, SPEED_OF_LIGHT, ctx.reflectivity))
        for f in FACE_NAMES
    }
    # Formula 7, then 8.
    srp_net = srp_net_force([srp_forces[f] for f in FACE_NAMES],
                            [FACE_NORMALS[f] for f in FACE_NAMES])
    srp_mag = srp_magnitude(srp_net)
    # Formulas 9 and 10 only make sense when there IS a net force. srp_elevation
    # raises on a zero magnitude, so this check is what keeps that from
    # happening; None correctly says "no direction to report".
    if srp_mag > MIN_EPSILON:
        # srp_net[0], [1], [2] are the x, y and z components. The physics
        # functions return radians; degrees are what gets displayed.
        srp_az = float(np.degrees(srp_azimuth(srp_net[0], srp_net[1])))
        srp_el = float(np.degrees(srp_elevation(srp_net[2], srp_mag)))
    else:
        srp_az = srp_el = None

    # --- fault / health (reuses assess_frame; same floored calibration) ---
    # Thresholds come from the context, so a session can be tuned without
    # editing the detector.
    health = assess_frame(
        est_frame, dark_offset=ctx.calibration.dark, gain=ctx.calibration.gain,
        low_signal_threshold=ctx.low_signal_total,
        opposition_threshold=ctx.opposition_threshold,
    )

    # --- validation metrics ---
    # A per-call reference overrides the context's, which is what lets the
    # Virtual sliders move mid-session.
    reference = ctx.reference_vector if reference is None else reference
    angular_error_deg = bias_deg = repeatability_deg = None
    # No vector means no error to measure, and all three stay None. Recording
    # zero error for a frame that made no measurement would flatter the
    # statistics the darker it got.
    if vector is not None:
        vec_arr = np.asarray(vector, dtype=float)
        # TWO PATHS, and the difference is history. With a rolling validator all
        # three metrics come back, because bias and repeatability need a window
        # of past frames.
        if ctx.rolling_validator is not None:
            rm = ctx.rolling_validator.update(vec_arr)
            angular_error_deg = rm["angular_error_deg"]
            bias_deg = rm["bias_deg"]
            repeatability_deg = rm["repeatability_deg"]
        # Without one, only this frame's own error can be computed, and the
        # other two stay None rather than being faked from a single sample.
        elif reference is not None:
            angular_error_deg = float(np.degrees(angular_error(vec_arr, reference)))

    # --- thermal ---
    # Also needs history, so also None without a streaming context.
    thermal = None
    if ctx.thermal_analyzer is not None:
        status = ctx.thermal_analyzer.update(frame.temperatures, frame.timestamp_ms)
        # Flattened from the ThermalStatus dataclass into a plain dict, because
        # the record must be JSON-serializable and a dataclass is not.
        thermal = {
            "temperatures": status.temperatures,
            "drift_rates": status.drift_rates,
            "rolling_means": status.rolling_means,
            "drift_flags": status.drift_flags,
            "missing": status.missing,
            "any_drift": status.any_drift,
        }

    # --- OPT4048 trust ---
    # No history needed, so this runs unconditionally on every frame.
    opt = analyze_opt(frame.opt, ctx.opt_reference, ctx.opt_tolerance)
    opt_out = {
        "cct_average": opt.cct_average,
        "cct_values": opt.cct_values,
        "gate": opt.gate,
        "trusted": opt.trusted,
        "delta": opt.delta,
        "light_source": opt.light_source,
        # The reference and tolerance are carried into the record so a log line
        # can be interpreted later without knowing how the session was
        # configured at the time.
        "reference": opt.reference,
        "tolerance": opt.tolerance,
    }

    # Link health: packet rate, gaps, drops. None when not streaming, since a
    # single frame has no rate.
    stream = ctx.monitor.stats() if ctx.monitor is not None else None

    # --- assemble ---
    # Every argument passed by name. With around forty fields, positional order
    # would be unmaintainable and a single transposition would silently swap two
    # measurements.
    return GroundStationRecord(
        seq=frame.seq,
        timestamp_ms=frame.timestamp_ms,
        # .isoformat() converts the datetime to the ISO-8601 text the record
        # stores (see record.py).
        received_at=frame.received_at.isoformat(),
        source=frame.source,
        # dict(...) copies, so later edits to the record cannot reach back and
        # mutate the original frame.
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
        # A non-empty list is truthy, so bool() turns "which faces" into
        # "were there any".
        saturation_flag=bool(saturated_faces),
        checksum=frame.checksum,
        # True because a SensorFrame only exists if the checksum already passed
        # during decoding; a failed one becomes a RejectedFrame and never
        # reaches this function (see frames.py).
        checksum_ok=True,
        # .value converts each FaultCode enum member to its string, since the
        # record is written as JSON and an enum is not serializable.
        faults=[c.value for c in health.faults],
        health_ok=health.ok,
        opposition_ratio=health.opposition_ratio,
        thermal=thermal,
        opt=opt_out,
        stream=stream,
        # Elapsed time in milliseconds. The design target is under 10 ms, which
        # is what allows 100 frames per second.
        processing_time_ms=(time.perf_counter() - t0) * 1000.0,
    )
