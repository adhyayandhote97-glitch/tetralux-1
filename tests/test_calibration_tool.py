"""Tests for the guided calibration capture math (Phase 10).

Uses hand-built SensorFrames for the unit-level checks, and the simulated
device feed (`sim.sensors`) for an end-to-end proof that the whole procedure
recovers known calibration values with no real hardware involved.
"""

import pytest

import queue as _queue

from tetralux.calibration import DEFAULT_DARK, DEFAULT_GAIN
from tetralux.calibration_tool import (
    _flush_queue,
    average_photodiodes,
    capture_dark_offsets,
    capture_gain,
    capture_max_illumination,
    run_guided_calibration,
    step_prompt,
)
from tetralux.constants import FACE_NAMES
from tetralux.frames import SensorFrame
from tetralux.sim.sensors import frame_from_angles


def _frame(pd_values: dict) -> SensorFrame:
    return SensorFrame(
        seq=0, timestamp_ms=0, photodiodes=[pd_values[f] for f in FACE_NAMES],
        lux=[0.0] * 6, magnetometer={"x": 0, "y": 0, "z": 0},
        opt=[{"X": 1, "Y": 1, "Z": 1, "lux": 0}] * 4,
        temperatures=[25.0] * 6, flags=1, checksum=0,
    )


def test_step_prompt_handles_every_step_kind():
    """Regression: dict.get()'s default arg is evaluated eagerly, so a naive
    `prompts.get(step, f"...{step.split(':')[1]}...")` raises IndexError for
    'dark'/'max' (no colon) even though those keys exist in the dict — the
    fallback expression is built regardless of which branch actually fires."""
    assert "Cover all sensors" in step_prompt("dark")
    assert "brightest" in step_prompt("max")
    assert "+x" in step_prompt("gain:+x")


def test_flush_queue_discards_stale_backlog():
    """Regression: a real device streams continuously between prompts, so
    frames posted before the operator finished repositioning the light must
    not carry over into the next step's sample (they'd be indistinguishable
    from genuine readings, silently corrupting the recovered calibration)."""
    q = _queue.Queue()
    for i in range(5):
        q.put(f"stale-{i}")
    assert _flush_queue(q) == 5
    assert q.empty()
    assert _flush_queue(q) == 0  # idempotent on an already-empty queue

    q.put("fresh")
    assert _flush_queue(q) == 1  # still just discards, doesn't peek/preserve


def test_average_photodiodes():
    frames = [_frame({f: 10.0 for f in FACE_NAMES}),
              _frame({f: 20.0 for f in FACE_NAMES})]
    avg = average_photodiodes(frames)
    assert all(v == pytest.approx(15.0) for v in avg.values())


def test_average_photodiodes_empty_raises():
    with pytest.raises(ValueError):
        average_photodiodes([])


def test_capture_dark_offsets_is_the_average():
    frames = [_frame({f: 5.0 for f in FACE_NAMES}),
              _frame({f: 7.0 for f in FACE_NAMES})]
    dark = capture_dark_offsets(frames)
    assert dark["+x"] == pytest.approx(6.0)


def test_capture_gain_solves_target_reading():
    dark = {f: 5.0 for f in FACE_NAMES}
    # +x reads 505 when lit -> signal = 500 -> gain = 1000/500 = 2.0
    frames = [_frame({**{f: 5.0 for f in FACE_NAMES}, "+x": 505.0})]
    gain = capture_gain("+x", frames, dark, target_reading=1000.0)
    assert gain == pytest.approx(2.0)


def test_capture_gain_raises_when_not_illuminated():
    dark = {f: 5.0 for f in FACE_NAMES}
    frames = [_frame({f: 5.0 for f in FACE_NAMES})]  # no signal above dark
    with pytest.raises(ValueError):
        capture_gain("+x", frames, dark, target_reading=1000.0)


def test_capture_max_illumination_takes_the_peak():
    frames = [_frame({f: 100.0 for f in FACE_NAMES}),
              _frame({**{f: 100.0 for f in FACE_NAMES}, "+x": 900.0})]
    peak = capture_max_illumination(frames)
    assert peak["+x"] == pytest.approx(900.0)
    assert peak["-x"] == pytest.approx(100.0)


def test_run_guided_calibration_composes_all_steps():
    dark_val, gain_val, max_val = 5.0, 2.0, 900.0

    def collect(step):
        if step == "dark":
            return [_frame({f: dark_val for f in FACE_NAMES})]
        if step == "max":
            return [_frame({f: max_val for f in FACE_NAMES})]
        face = step.split(":")[1]
        # lit reading such that (V - dark) * solved_gain == target(1000)
        lit_reading = dark_val + 1000.0 / gain_val
        return [_frame({**{f: dark_val for f in FACE_NAMES}, face: lit_reading})]

    cal = run_guided_calibration(collect, target_reading=1000.0)
    assert all(cal.dark[f] == pytest.approx(dark_val) for f in FACE_NAMES)
    assert all(cal.gain[f] == pytest.approx(gain_val) for f in FACE_NAMES)
    assert all(cal.max_illumination[f] == pytest.approx(max_val) for f in FACE_NAMES)


def test_guided_calibration_against_simulated_device_feed():
    """End-to-end: run the full procedure against sim.sensors, no hardware."""
    # Canonical direction per face so the reference light is dead-on each time.
    directions = {
        "+x": (0.0, 0.0), "-x": (180.0, 0.0), "+y": (90.0, 0.0),
        "-y": (-90.0, 0.0), "+z": (0.0, 90.0), "-z": (0.0, -90.0),
    }

    # Intensity chosen so V = S/G + D stays comfortably under the 10-bit ADC
    # ceiling (1023) for every face's (gain, dark) pair — at 1000 the lowest-gain
    # face (-z, 0.97) would clip (1000/0.97+6 > 1023), distorting the recovered
    # gain. 700 keeps every face's raw reading under ~730.
    lit_intensity = 700.0

    def collect(step):
        if step == "dark":
            # "lights off" -> zero intensity, still carries the real dark offset.
            return [frame_from_angles(0.0, 0.0, intensity=0.0) for _ in range(5)]
        if step == "max":
            return [frame_from_angles(0.0, 0.0, intensity=lit_intensity) for _ in range(5)]
        face = step.split(":")[1]
        az, el = directions[face]
        return [frame_from_angles(az, el, intensity=lit_intensity) for _ in range(5)]

    cal = run_guided_calibration(collect, target_reading=lit_intensity)
    # The simulator's default gain/dark are calibration.DEFAULT_GAIN/DEFAULT_DARK;
    # with target_reading == the sim intensity, the recovered values should match
    # those defaults closely (noise-free here, modulo 10-bit ADC quantization).
    for f in FACE_NAMES:
        assert cal.dark[f] == pytest.approx(DEFAULT_DARK[f], abs=1e-6)
        assert cal.gain[f] == pytest.approx(DEFAULT_GAIN[f], rel=1e-3)
