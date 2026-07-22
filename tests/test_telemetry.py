"""Tests for the Phase 4 telemetry codec and generator."""

import numpy as np
import pytest

from tetralux.constants import FACE_NAMES
from tetralux.estimation.estimator import estimate_sun_vector
from tetralux.telemetry.generator import generate_telemetry, pack_stream
from tetralux.telemetry.packet import (
    ADC_MAX,
    PACKET_LEN,
    SYNC_BYTE,
    PacketError,
    decode_packet,
    encode_packet,
    iter_packets,
)
from tetralux.validation.metrics import angular_error


def _frame(readings, saturated=()):
    return {f: {"reading": readings.get(f, 0.0), "saturated": f in saturated}
            for f in FACE_NAMES}


def _to_estimator_frame(decoded):
    return {f: {"reading": decoded["readings"][f]} for f in FACE_NAMES}


def test_packet_is_fixed_length():
    raw = encode_packet(1, _frame({"+x": 1000, "+y": 500}))
    assert len(raw) == PACKET_LEN
    assert raw[0] == SYNC_BYTE


def test_round_trip_readings_and_flags():
    frame = _frame({"+x": 1000, "-x": 5, "+y": 800, "+z": 250}, saturated=("+x", "+z"))
    decoded = decode_packet(encode_packet(7, frame))
    assert decoded["seq"] == 7
    assert decoded["readings"] == {
        "+x": 1000, "-x": 5, "+y": 800, "-y": 0, "+z": 250, "-z": 0
    }
    assert decoded["saturated"]["+x"] is True
    assert decoded["saturated"]["+z"] is True
    assert decoded["saturated"]["-x"] is False


def test_quantization_rounds_and_clamps():
    frame = _frame({"+x": 12.4, "-x": 12.6, "+y": 99999.0})
    decoded = decode_packet(encode_packet(0, frame))
    assert decoded["readings"]["+x"] == 12       # rounds down
    assert decoded["readings"]["-x"] == 13       # rounds up
    assert decoded["readings"]["+y"] == ADC_MAX  # clamped to 16-bit max


def test_seq_wraps_at_16_bits():
    assert decode_packet(encode_packet(65535, _frame({})))["seq"] == 65535
    assert decode_packet(encode_packet(65536, _frame({})))["seq"] == 0


def test_bad_checksum_raises():
    raw = bytearray(encode_packet(1, _frame({"+x": 1000})))
    raw[5] ^= 0xFF  # corrupt a reading byte
    with pytest.raises(PacketError):
        decode_packet(bytes(raw))


def test_truncated_and_oversize_raise():
    raw = encode_packet(1, _frame({"+x": 1000}))
    with pytest.raises(PacketError):
        decode_packet(raw[:-2])
    with pytest.raises(PacketError):
        decode_packet(raw + b"\x00")


def test_bad_sync_raises():
    raw = bytearray(encode_packet(1, _frame({"+x": 1000})))
    raw[0] = 0x00  # not the sync byte
    with pytest.raises(PacketError):
        decode_packet(bytes(raw))


def test_stream_resyncs_past_garbage_and_truncated_tail():
    good1 = encode_packet(11, _frame({"+x": 1000}))
    good2 = encode_packet(12, _frame({"+y": 700}))
    stream = b"\x00\xff" + good1 + b"\xde\xad\xbe\xef" + good2 + b"\xaa\x01"
    seqs = [f["seq"] for f in iter_packets(stream)]
    assert seqs == [11, 12]


def test_stream_skips_corrupted_packet():
    good1 = bytearray(encode_packet(21, _frame({"+x": 1000})))
    good1[5] ^= 0xFF  # corrupt payload -> checksum fails
    good2 = encode_packet(22, _frame({"+y": 700}))
    seqs = [f["seq"] for f in iter_packets(bytes(good1) + good2)]
    assert seqs == [22]


def test_generate_telemetry_timing_and_sequence():
    dirs = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])]
    stream = generate_telemetry(dirs, rate_hz=20.0, seq_start=100, intensity=1000.0)
    assert len(stream) == 3
    timestamps = [t for t, _ in stream]
    assert timestamps == pytest.approx([0.0, 0.05, 0.10])  # 20 Hz -> 0.05 s spacing
    seqs = [decode_packet(pkt)["seq"] for _, pkt in stream]
    assert seqs == [100, 101, 102]


def test_end_to_end_telemetry_recovers_direction():
    true_dir = np.array([0.3, -0.5, 0.8])
    true_dir = true_dir / np.linalg.norm(true_dir)
    # High intensity so 16-bit quantization error is negligible.
    stream = generate_telemetry([true_dir], intensity=60000.0)
    raw = pack_stream(pkt for _, pkt in stream)
    decoded = next(iter_packets(raw))
    s_hat = estimate_sun_vector(_to_estimator_frame(decoded))
    assert np.degrees(angular_error(s_hat, true_dir)) < 0.1
