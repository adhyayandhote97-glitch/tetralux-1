"""Tests for the v2 ground-station dashboard (Phase 9)."""

import time

import pytest

from tetralux.constants import FACE_NAMES
from tetralux.dashboard import units as U


def test_units_never_bare():
    assert U.q(3.14159, "angle").endswith("°")
    assert U.q(0.25, "weight") == "0.250 dimensionless"
    assert U.q(5500.0, "cct", 0) == "5500 K"
    assert U.fmt(None) == "-"
    assert U.fmt(float("nan")) == "-"
    assert U.fmt(True) == "yes"
    assert U.human_bytes(2048) == "2.0 KiB"


def test_figures_build():
    pytest.importorskip("plotly")
    import plotly.graph_objects as go

    from tetralux.dashboard.figures import (
        cube_figure,
        face_readings_figure,
        srp_figure,
        timeseries_figure,
        weights_figure,
    )

    assert isinstance(cube_figure([1, 0, 0], [1, 0, 0]), go.Figure)
    assert isinstance(weights_figure({f: 1 / 6 for f in FACE_NAMES}), go.Figure)
    assert isinstance(srp_figure({f: 1e-8 for f in FACE_NAMES}), go.Figure)
    assert isinstance(face_readings_figure({f: 100 for f in FACE_NAMES}), go.Figure)
    assert isinstance(timeseries_figure([0, 1, 2], {"a": [1, None, 3]}, "t", "y"), go.Figure)
    assert isinstance(cube_figure(), go.Figure)  # no-data variant


def test_state_virtual_compute_populates_everything(tmp_path):
    from tetralux.dashboard.state import AppState

    st = AppState(base_dir=str(tmp_path))
    rec = st.compute_virtual(30.0, 20.0)
    assert rec.sun_vector is not None
    assert rec.angular_error_deg is not None and rec.angular_error_deg < 1.5
    assert rec.bias_deg is not None
    assert rec.repeatability_deg is not None
    assert rec.thermal is not None          # virtual context has a thermal analyzer
    assert rec.opt["trusted"] is True       # daylight source


def test_state_real_sim_feed_streams(tmp_path):
    from tetralux.dashboard.state import AppState

    st = AppState(base_dir=str(tmp_path))
    st.mode = "real"
    st.start_sim_device(rate_hz=25.0)
    try:
        deadline = time.time() + 4.0
        while time.time() < deadline and st.latest() is None:
            time.sleep(0.05)
    finally:
        st.stop_real()
    assert st.latest() is not None
    assert st.connection()["total_accepted"] > 0


def test_create_app_v2_smoke(tmp_path):
    pytest.importorskip("dash")
    from dash import Dash

    from tetralux.dashboard.app import create_app
    from tetralux.dashboard.state import AppState

    app = create_app(AppState(base_dir=str(tmp_path)))
    assert isinstance(app, Dash)
    assert app.layout is not None
