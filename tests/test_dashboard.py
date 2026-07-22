"""Tests for the Phase 5 dashboard.

The replay data layer is pure and always tested. The Plotly figure builders and
the Dash app are tested only when the ``dashboard`` extra is installed.
"""

import numpy as np
import pytest

from tetralux.constants import FACE_NAMES
from tetralux.dashboard.replay import build_replay
from tetralux.faults.detector import FaultCode
from tetralux.telemetry.generator import generate_telemetry, pack_stream
from tetralux.telemetry.packet import encode_packet


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


# --- replay layer (pure, no UI deps) ---------------------------------------

def test_build_replay_one_frame_per_packet():
    dirs = [_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])]
    raw = pack_stream(p for _, p in generate_telemetry(
        dirs, rate_hz=20.0, seq_start=5, intensity=1000.0))
    frames = build_replay(raw, references=dirs, rate_hz=20.0)

    assert [f.seq for f in frames] == [5, 6, 7]
    assert [f.time_s for f in frames] == pytest.approx([0.0, 0.05, 0.10])
    assert all(set(f.readings.keys()) == set(FACE_NAMES) for f in frames)


def test_build_replay_scores_healthy_frames():
    dirs = [_unit([0.3, -0.5, 0.8]), _unit([1, 1, 0])]
    raw = pack_stream(p for _, p in generate_telemetry(dirs, intensity=60000.0))
    frames = build_replay(raw, references=dirs)

    for f in frames:
        assert f.health.ok
        assert f.sun_vector is not None
        assert f.angular_error_deg is not None
        assert f.angular_error_deg < 0.1  # quantization only


def test_build_replay_flags_low_signal_frame():
    dark = {f: {"reading": 0.0, "saturated": False} for f in FACE_NAMES}
    raw = pack_stream([encode_packet(0, dark)])
    frame = build_replay(raw)[0]

    assert frame.sun_vector is None
    assert frame.health.has(FaultCode.LOW_SIGNAL)
    assert frame.angular_error_deg is None


# --- figure builders (need plotly) -----------------------------------------

def test_figures_build_without_error():
    pytest.importorskip("plotly")
    import plotly.graph_objects as go

    from tetralux.dashboard.figures import (
        angular_error_figure,
        face_readings_figure,
        sun_vector_figure,
    )

    vec = sun_vector_figure(_unit([1, 0, 0]), reference=_unit([1, 0, 0]))
    assert isinstance(vec, go.Figure) and len(vec.data) > 0

    bars = face_readings_figure({f: 100 for f in FACE_NAMES}, {"+x": True})
    assert isinstance(bars, go.Figure)
    assert list(bars.data[0].y) == [100] * len(FACE_NAMES)

    err = angular_error_figure([0.0, 0.1, 0.2], [1.0, None, 0.5], current_index=2)
    assert isinstance(err, go.Figure)


# --- Dash app (needs dash) -------------------------------------------------

def test_create_app_builds_layout_and_demo():
    pytest.importorskip("dash")
    from dash import Dash

    from tetralux.dashboard.app import build_demo_frames, create_app

    frames = build_demo_frames()
    assert len(frames) > 0

    app = create_app(frames)
    assert isinstance(app, Dash)
    assert app.layout is not None


def test_create_app_rejects_empty_frames():
    pytest.importorskip("dash")
    from tetralux.dashboard.app import create_app

    with pytest.raises(ValueError):
        create_app([])
