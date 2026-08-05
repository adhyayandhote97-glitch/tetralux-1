"""Tests that a loaded calibration file actually reaches the processing context
(Phase 10) - both for the headless groundstation runner and the dashboard's
AppState.load_calibration."""

import pytest

from tetralux.calibration import Calibration
from tetralux.constants import FACE_NAMES
from tetralux.pipeline import make_streaming_context, process
from tetralux.sim.sensors import frame_from_angles


def _custom_calibration(tmp_path):
    cal = Calibration(
        dark={f: 50.0 for f in FACE_NAMES},       # far from the v0 defaults (~5)
        gain={f: 3.0 for f in FACE_NAMES},         # far from the v0 defaults (~1.0)
        max_illumination={f: 500.0 for f in FACE_NAMES},
        lab_scaling_factor=0.1,
    )
    path = tmp_path / "calibration.json"
    cal.save(path)
    return path, cal


def test_make_streaming_context_uses_loaded_calibration(tmp_path):
    path, cal = _custom_calibration(tmp_path)
    loaded = Calibration.load(path)

    ctx = make_streaming_context(calibration=loaded)
    assert ctx.calibration.dark == cal.dark
    assert ctx.calibration.gain == cal.gain

    # A frame processed through this context should reflect the custom gain
    # (corrected = (V - 50) * 3, very different from the default calibration).
    frame = frame_from_angles(0.0, 0.0, intensity=1000.0, gain={f: 1.0 for f in FACE_NAMES},
                              dark={f: 0.0 for f in FACE_NAMES})
    rec = process(frame, ctx)
    assert rec.corrected["+x"] == pytest.approx((1000.0 - 50.0) * 3.0)


def test_default_context_uses_placeholder_calibration_when_none_given():
    ctx = make_streaming_context()
    from tetralux.calibration import DEFAULT_DARK, DEFAULT_GAIN

    assert ctx.calibration.dark == DEFAULT_DARK
    assert ctx.calibration.gain == DEFAULT_GAIN


def test_app_state_load_calibration_rebuilds_stream_context(tmp_path):
    from tetralux.dashboard.state import AppState

    path, cal = _custom_calibration(tmp_path)
    st = AppState(base_dir=str(tmp_path))
    st.start_real()  # default calibration context created here
    assert st.stream_ctx.calibration.dark != cal.dark

    loaded = st.load_calibration(str(path))
    assert loaded.dark == cal.dark
    assert st.stream_ctx.calibration.dark == cal.dark
    assert st.calibration_path == str(path)
    st.stop_real()
