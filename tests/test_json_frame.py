"""Tests for the real-hardware JSON telemetry codec (Phase 6)."""

import pytest

from tetralux.frames import RejectedFrame, SensorFrame
from tetralux.telemetry.json_frame import (
    decode_json_frame,
    encode_json_frame,
    xor_checksum,
)


def _sample_frame():
    return SensorFrame(
        seq=42, timestamp_ms=1000,
        photodiodes=[900, 10, 500, 20, 300, 15],
        lux=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        magnetometer={"x": 100, "y": -50, "z": 10},
        opt=[{"X": 30.0, "Y": 40.0, "Z": 30.0, "lux": 100.0}] * 4,
        temperatures=[25.0, 25.3, None, 25.1, 24.9, 25.2],
        flags=1, checksum=0,
    )


def test_xor_checksum_matches_manual():
    assert xor_checksum("ABC") == (0x41 ^ 0x42 ^ 0x43)
    assert xor_checksum(b"") == 0


def test_encode_checksum_is_over_bytes_before_chk():
    wire = encode_json_frame(_sample_frame())
    region = wire[: wire.rfind(',"chk"')]
    transmitted = int(wire.rsplit('"chk":', 1)[1].rstrip("}"))
    assert xor_checksum(region) == transmitted


def test_round_trip_preserves_fields_including_null_temp():
    frame = _sample_frame()
    decoded = decode_json_frame(encode_json_frame(frame))
    assert isinstance(decoded, SensorFrame)
    assert decoded.seq == 42
    assert decoded.timestamp_ms == 1000
    assert decoded.photodiodes == [900, 10, 500, 20, 300, 15]
    assert decoded.magnetometer == {"x": 100, "y": -50, "z": 10}
    assert decoded.temperatures[2] is None
    assert decoded.temperatures[0] == pytest.approx(25.0)
    assert len(decoded.opt) == 4


def test_corrupted_byte_rejected_as_checksum():
    wire = encode_json_frame(_sample_frame())
    # Flip a digit in the pd array without touching chk.
    corrupt = wire.replace('"pd":[900', '"pd":[901', 1)
    result = decode_json_frame(corrupt)
    assert isinstance(result, RejectedFrame)
    assert "checksum" in result.reason.lower()


def test_missing_chk_and_bad_json_rejected():
    assert isinstance(decode_json_frame('{"seq":1}'), RejectedFrame)
    assert isinstance(decode_json_frame('not json,"chk":0'), RejectedFrame)


def test_out_of_range_pd_rejected():
    frame = _sample_frame()
    frame.photodiodes[0] = 5000  # > 10-bit ADC max
    result = decode_json_frame(encode_json_frame(frame))
    assert isinstance(result, RejectedFrame)
    assert "pd" in result.reason.lower()
