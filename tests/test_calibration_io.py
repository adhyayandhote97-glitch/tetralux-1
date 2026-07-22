"""Tests for Calibration save/load and JSON round-trip (Phase 10)."""

import pytest

from tetralux.calibration import Calibration
from tetralux.constants import FACE_NAMES


def test_to_json_from_json_round_trip():
    cal = Calibration()
    cal.gain["+x"] = 1.234
    restored = Calibration.from_json(cal.to_json())
    assert restored.dark == cal.dark
    assert restored.gain == cal.gain
    assert restored.max_illumination == cal.max_illumination
    assert restored.lab_scaling_factor == pytest.approx(cal.lab_scaling_factor)


def test_save_load_round_trip(tmp_path):
    cal = Calibration(
        dark={f: 3.0 for f in FACE_NAMES},
        gain={f: 1.1 for f in FACE_NAMES},
        max_illumination={f: 900.0 for f in FACE_NAMES},
        lab_scaling_factor=0.2,
    )
    path = tmp_path / "calibration.json"
    cal.save(path)
    loaded = Calibration.load(path)
    assert loaded.dark == cal.dark
    assert loaded.gain == cal.gain
    assert loaded.max_illumination == cal.max_illumination
    assert loaded.lab_scaling_factor == pytest.approx(0.2)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Calibration.load(tmp_path / "nope.json")


def test_load_malformed_file_raises_value_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"dark": {}}', encoding="utf-8")  # missing gain, max, lab_scaling
    with pytest.raises(ValueError):
        Calibration.load(path)
