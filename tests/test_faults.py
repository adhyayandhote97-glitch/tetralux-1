"""Tests for the Phase 3 sensor/estimation fault detector."""

import numpy as np
import pytest

from tetralux.faults.detector import (
    FaultCode,
    assess_frame,
    opposition_ratio,
    safe_estimate,
)
from tetralux.sim.simulator import simulate_faces


def _frame(readings, saturated=()):
    """Build a simulate_faces-style frame from a {face: reading} dict."""
    return {
        f: {"reading": r, "saturated": f in saturated}
        for f, r in readings.items()
    }


def test_clean_single_source_is_healthy():
    faces = simulate_faces(np.array([1.0, 0.0, 0.0]), intensity=1000.0)
    health = assess_frame(faces)
    assert health.ok
    assert health.faults == ()
    assert health.dominant_face == "+x"
    assert health.opposition_ratio == pytest.approx(0.0, abs=1e-12)


def test_low_signal_frame_flags_and_yields_no_vector():
    dark = _frame({f: 0.0 for f in ["+x", "-x", "+y", "-y", "+z", "-z"]})
    health = assess_frame(dark)
    assert not health.ok
    assert health.has(FaultCode.LOW_SIGNAL)
    assert health.dominant_face is None

    vector, health2 = safe_estimate(dark)
    assert vector is None
    assert health2.has(FaultCode.LOW_SIGNAL)


def test_low_signal_threshold_is_configurable():
    faces = simulate_faces(np.array([1.0, 0.0, 0.0]), intensity=100.0)  # total ~100
    assert assess_frame(faces).ok  # default threshold: healthy
    assert assess_frame(faces, low_signal_threshold=500.0).has(FaultCode.LOW_SIGNAL)


def test_saturation_is_flagged_with_dominant_face():
    faces = simulate_faces(
        np.array([1.0, 0.0, 0.0]), intensity=1000.0, saturation_limit=800.0
    )
    health = assess_frame(faces)
    assert health.has(FaultCode.SATURATION)
    assert health.saturated_faces == ("+x",)
    assert health.details["dominant_saturated"] is True
    assert not health.ok


def test_multi_source_ambiguity_detected():
    # Light arriving on opposite faces -> ambiguous "average" direction.
    both = _frame({"+x": 800.0, "-x": 800.0, "+y": 0.0, "-y": 0.0, "+z": 0.0, "-z": 0.0})
    assert opposition_ratio(
        {"+x": 800.0, "-x": 800.0, "+y": 0.0, "-y": 0.0, "+z": 0.0, "-z": 0.0}
    ) == pytest.approx(1.0)
    health = assess_frame(both)
    assert health.has(FaultCode.MULTI_SOURCE)
    assert not health.ok


def test_safe_estimate_returns_vector_but_reports_faults():
    # Saturated frame still yields a direction; the fault is surfaced, not hidden.
    faces = simulate_faces(
        np.array([1.0, 0.0, 0.0]), intensity=1000.0, saturation_limit=800.0
    )
    vector, health = safe_estimate(faces)
    assert vector is not None
    assert np.allclose(vector, [1.0, 0.0, 0.0])
    assert health.has(FaultCode.SATURATION)
