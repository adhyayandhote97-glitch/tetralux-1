"""Tests for the telemetry StreamMonitor (Phase 6)."""

from tetralux.frames import RejectedFrame, SensorFrame
from tetralux.ingest.monitor import StreamMonitor


def _frame(seq):
    return SensorFrame(seq=seq, timestamp_ms=seq * 10, photodiodes=[0] * 6,
                       lux=[0.0] * 6, magnetometer={"x": 0, "y": 0, "z": 0},
                       opt=[{"X": 1, "Y": 1, "Z": 1, "lux": 0}] * 4,
                       temperatures=[25.0] * 6, flags=1, checksum=0)


def test_sequence_gap_counts_dropped_frames():
    m = StreamMonitor(timeout_s=0.5)
    m.record_accepted(_frame(1), now=0.0)
    m.record_accepted(_frame(3), now=0.01)   # skipped seq 2
    stats = m.stats(now=0.02)
    assert stats["seq_gaps"] == 1
    assert stats["dropped"] == 1
    assert stats["total_accepted"] == 2


def test_checksum_rejection_counts_corrupt():
    m = StreamMonitor()
    m.record_rejected(RejectedFrame(4, "checksum mismatch: ...", ""))
    m.record_rejected(RejectedFrame(None, "JSON decode error", ""))
    stats = m.stats()
    assert stats["corrupt"] == 1
    assert stats["total_rejected"] == 2


def test_connection_and_rate():
    m = StreamMonitor(timeout_s=0.5)
    m.record_accepted(_frame(1), now=0.0)
    m.record_accepted(_frame(2), now=0.1)
    assert m.connected(now=0.2) is True
    assert m.connected(now=1.0) is False       # older than timeout
    assert m.rate_hz(now=0.5) == 2.0           # both within last second
