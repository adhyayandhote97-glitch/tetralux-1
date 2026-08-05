"""Tests for the end-to-end processing pipeline (Phases 6-7)."""

import json

import numpy as np
import pytest

from tetralux.constants import FACE_NAMES
from tetralux.estimation.estimator import angles_to_vector
from tetralux.pipeline import PipelineContext, make_streaming_context, process
from tetralux.sim.sensors import frame_from_angles, simulate_sensor_frame


def test_pipeline_produces_complete_record():
    az, el = 30.0, 20.0
    frame = frame_from_angles(az, el)
    true_dir = angles_to_vector(az, el)
    rec = process(frame, PipelineContext(), reference=true_dir)

    # estimate recovered accurately (calibration inverts the virtual gain/dark)
    assert rec.sun_vector is not None
    assert rec.angular_error_deg is not None
    assert rec.angular_error_deg < 1.5  # quantization + gain spread only

    # weights normalized
    assert abs(sum(rec.weights.values()) - 1.0) < 1e-9
    assert set(rec.weights) == set(FACE_NAMES)

    # every display block present
    assert set(rec.photodiodes) == set(FACE_NAMES)
    assert set(rec.lux) == set(FACE_NAMES)
    assert set(rec.corrected) == set(FACE_NAMES)
    assert set(rec.irradiance) == set(FACE_NAMES)
    assert rec.opt["trusted"] is True          # daylight source
    assert rec.confidence > 0.0
    assert rec.checksum_ok is True


def test_pipeline_computes_srp_from_irradiance():
    """SRP (formulas 6-10) must actually run, not sit orphaned in physics/."""
    from tetralux.constants import (
        CUBESAT_FACE_AREA,
        DEFAULT_REFLECTIVITY,
        SPEED_OF_LIGHT,
    )

    rec = process(frame_from_angles(30.0, 20.0, intensity=900.0), PipelineContext())

    # Formula 6 applied to the +x face, checked against the record's own irradiance.
    expected = (rec.irradiance["+x"] * CUBESAT_FACE_AREA / SPEED_OF_LIGHT) * (
        1.0 + DEFAULT_REFLECTIVITY)
    assert rec.srp_forces["+x"] == pytest.approx(expected)

    # Faces turned away from the light contribute no force.
    assert rec.srp_forces["-x"] == pytest.approx(0.0)

    # Net force magnitude is positive and its direction tracks the sun vector,
    # since radiation pressure pushes along the incoming light.
    assert rec.srp_magnitude_n > 0.0
    assert rec.srp_azimuth_deg == pytest.approx(rec.azimuth_deg, abs=1.0)
    assert rec.srp_elevation_deg == pytest.approx(rec.elevation_deg, abs=1.0)


def test_srp_is_zero_for_a_dark_frame():
    rec = process(simulate_sensor_frame(np.array([1.0, 0.0, 0.0]), intensity=0.0),
                  PipelineContext())
    assert rec.srp_magnitude_n == pytest.approx(0.0)
    assert rec.srp_azimuth_deg is None
    assert rec.srp_elevation_deg is None


def test_record_is_json_serializable():
    frame = frame_from_angles(45.0, 10.0)
    rec = process(frame, make_streaming_context())
    # streaming context populates thermal + stream-less monitor(None) gracefully
    json.dumps(rec.to_dict())  # must not raise (NaN -> null handled)


def test_low_signal_frame_yields_no_vector():
    # Point the light straight down -z with only +z... actually use a dark frame:
    frame = simulate_sensor_frame(np.array([1.0, 0.0, 0.0]), intensity=0.0)
    rec = process(frame, PipelineContext())
    assert rec.sun_vector is None
    assert "low_signal" in rec.faults


def test_streaming_context_fills_rolling_metrics():
    ctx = make_streaming_context(reference_vector=angles_to_vector(30.0, 20.0))
    frame = frame_from_angles(30.0, 20.0)
    rec = process(frame, ctx)
    assert rec.bias_deg is not None
    assert rec.repeatability_deg is not None
    assert rec.thermal is not None
