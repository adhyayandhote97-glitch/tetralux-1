"""Tests for virtual sensor synthesis (Phase 7)."""

import numpy as np

from tetralux.constants import ADC_MAX
from tetralux.frames import SensorFrame
from tetralux.sim.sensors import frame_from_angles, simulate_sensor_frame


def test_frame_is_wire_valid_and_complete():
    frame = simulate_sensor_frame(np.array([1.0, 0.0, 0.0]), seq=5, timestamp_ms=100)
    assert isinstance(frame, SensorFrame)
    assert frame.source == "virtual"
    assert frame.seq == 5
    assert len(frame.photodiodes) == 6
    assert all(0 <= v <= ADC_MAX for v in frame.photodiodes)
    assert len(frame.lux) == 6
    assert len(frame.temperatures) == 6
    assert len(frame.opt) == 4
    assert set(frame.magnetometer) == {"x", "y", "z"}


def test_plus_x_light_maximizes_plus_x_photodiode():
    frame = simulate_sensor_frame(np.array([1.0, 0.0, 0.0]))
    pd = frame.photodiode_map()
    assert pd["+x"] == max(pd.values())
    assert pd["-x"] <= pd["+x"]


def test_frame_from_angles_matches_direction():
    # Light straight along +x is azimuth 0, elevation 0.
    frame = frame_from_angles(0.0, 0.0)
    pd = frame.photodiode_map()
    assert pd["+x"] == max(pd.values())
