"""Tests for the logging store: local JSONL, session control, RTDB, query (Phase 8)."""

import pytest

from tetralux.pipeline import PipelineContext, process
from tetralux.sim.sensors import frame_from_angles
from tetralux.store import query
from tetralux.store.local_log import LocalLog
from tetralux.store.rtdb_store import FakeStore
from tetralux.store.session import SessionController


def _record(seq, ts):
    frame = frame_from_angles(30.0, 20.0, seq=seq, timestamp_ms=ts)
    return process(frame, PipelineContext())


def test_local_log_round_trip_and_time_range(tmp_path):
    log = LocalLog("S1", base_dir=str(tmp_path))
    for i in range(3):
        assert log.append(_record(i, i * 10).to_dict()) > 0
    assert len(log.read()) == 3
    assert len(log.time_range(start_ms=10)) == 2   # ts 10, 20
    assert len(log.time_range(end_ms=10)) == 2      # ts 0, 10


def test_session_gates_recording_and_tracks_size(tmp_path):
    fake = FakeStore()
    ctl = SessionController(base_dir=str(tmp_path), online_store=fake)

    ctl.record(_record(0, 0))          # before start -> no-op
    assert ctl.info is None

    ctl.start("S_TEST")
    assert ctl.active
    for i in range(5):
        ctl.record(_record(i, i * 10))
    assert ctl.info.packet_count == 5
    assert ctl.info.local_bytes > 0
    assert ctl.info.rtdb_bytes_est > 0
    assert len(fake.read_session("S_TEST")) == 5

    stopped = ctl.stop()
    assert not ctl.active
    assert stopped.stopped_at is not None
    assert stopped.duration_s() >= 0.0


def test_query_lists_sessions_with_size(tmp_path):
    ctl = SessionController(base_dir=str(tmp_path))
    ctl.start("S_A")
    for i in range(4):
        ctl.record(_record(i, i * 10))
    ctl.stop()

    sessions = query.list_sessions(base_dir=str(tmp_path))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_id == "S_A"
    assert s.packet_count == 4
    assert s.size_bytes > 0
    assert s.first_ts_ms == 0 and s.last_ts_ms == 30
    assert s.size_human().endswith(("B", "KiB", "MiB"))


def test_export_csv(tmp_path):
    ctl = SessionController(base_dir=str(tmp_path))
    ctl.start("S_B")
    for i in range(3):
        ctl.record(_record(i, i * 10))
    ctl.stop()

    out = tmp_path / "out.csv"
    n = query.export_session_csv("S_B", str(out), base_dir=str(tmp_path))
    assert n == 3
    header = out.read_text().splitlines()[0]
    assert "seq" in header and "azimuth_deg" in header


def test_fake_store_per_packet_shape(tmp_path):
    fake = FakeStore()
    ctl = SessionController(base_dir=str(tmp_path), online_store=fake)
    ctl.start("S_C")
    ctl.record(_record(7, 700))
    ctl.stop()

    assert "S_C" in fake.list_sessions()
    recs = fake.read_session("S_C")
    assert recs[0]["seq"] == 7
