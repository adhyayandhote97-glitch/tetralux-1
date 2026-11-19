"""Sanity tests for the overnight-test maths, on tiny synthetic CSVs.

TEMPORARY (delete with overnight_test/). Run:
  /usr/bin/python3 -m pytest overnight_test/test_endurance_maths.py -q
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_endurance as A  # noqa: E402
from endurance_common import (  # noqa: E402
    DEFAULT_ESTIMATOR, EVENT_COLUMNS, MARKER_COLUMNS, PACKET_COLUMNS, TAGS,
    angle_between_deg, angles_to_vector, parse_marker, pose_stats,
)

DT = 0.381  # seconds between frames, like the real board


def packet(seq, mono, ts=None, ok=1, vec=None, temp=24.0):
    r = {c: "" for c in PACKET_COLUMNS}
    r.update(host_iso=f"t{mono:.3f}", host_mono=f"{mono:.6f}", parse_ok=ok)
    if ok:
        r.update(seq=seq, ts_ms=int(ts if ts is not None else mono * 1000))
        for t in TAGS:
            r[f"pd_{t}"] = 10
            r[f"temp_{t}"] = temp
        if vec is not None:
            r.update(est_x=vec[0], est_y=vec[1], est_z=vec[2])
    else:
        r.update(reject_reason="checksum mismatch: x", raw="{garbage")
    return r


def write(path, columns, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def run(tmp_path, seqs, extra=None, markers=None, events=None, dt=DT):
    rows = [packet(s, i * dt) for i, s in enumerate(seqs)]
    if extra:
        rows += extra
    csv_path = write(tmp_path / "endurance_test.csv", PACKET_COLUMNS, rows)
    if markers is not None:
        write(tmp_path / "endurance_test_markers.csv", MARKER_COLUMNS, markers)
    if events is not None:
        write(tmp_path / "endurance_test_events.csv", EVENT_COLUMNS, events)
    return A.analyse(csv_path, charts=False)


def test_perfect_run_is_100_percent(tmp_path):
    r = run(tmp_path, range(100))
    assert r["full"] == {"received": 100, "missing": 0, "expected": 100, "pct": 100.0}
    assert r["seq"].gaps == []
    assert (tmp_path / "endurance_test_summary.md").exists()


def test_gap_counts_missing_frames(tmp_path):
    r = run(tmp_path, list(range(10)) + list(range(13, 20)))   # 10, 11, 12 lost
    assert r["full"]["received"] == 17
    assert r["full"]["missing"] == 3
    assert r["full"]["pct"] == pytest.approx(100 * 17 / 20)
    assert len(r["seq"].gaps) == 1 and r["seq"].gaps[0].missing == 3


def test_board_restart_is_not_counted_as_loss(tmp_path):
    r = run(tmp_path, list(range(10)) + list(range(10)))
    assert len(r["seq"].resets) == 1
    assert r["full"]["missing"] == 0
    assert r["full"]["received"] == 20


def test_duplicates_are_not_double_counted(tmp_path):
    r = run(tmp_path, [0, 1, 2, 2, 3, 4])
    assert r["seq"].duplicates == 1
    assert r["full"]["received"] == 5 and r["full"]["missing"] == 0


def test_bad_lines_lower_parse_rate_not_reception(tmp_path):
    bad = [packet(None, 5.0, ok=0), packet(None, 6.0, ok=0)]
    r = run(tmp_path, range(8), extra=bad)
    assert r["lines"] == 10 and r["ok_lines"] == 8
    assert r["parse_pct"] == pytest.approx(80.0)
    assert r["full"]["received"] == 8


def test_first_30_min_window_excludes_later_loss(tmp_path):
    # 40 min of frames at 1 s, losing 5 frames after minute 35
    seqs = list(range(2100)) + list(range(2105, 2400))
    r = run(tmp_path, seqs, dt=1.0)
    assert r["first30"]["pct"] == 100.0
    assert r["full"]["missing"] == 5
    assert r["reached30"] and not r["reached2h"]


def test_loss_goes_into_the_right_5_min_bucket(tmp_path):
    seqs = list(range(400)) + list(range(410, 700))   # 1 s apart: gap lands at t=400 s
    r = run(tmp_path, seqs, dt=1.0)
    b = r["buckets"]
    assert b[0]["missing"] == 0 and b[1]["missing"] == 10
    assert sum(x["received"] for x in b) == 690


def test_intervals_skip_gaps_and_use_both_clocks(tmp_path):
    rows = [packet(s, s * 0.381, ts=s * 381) for s in range(50)]
    rows += [packet(60, 60 * 0.381, ts=60 * 381)]            # gap: not an interval
    p = write(tmp_path / "endurance_iv.csv", PACKET_COLUMNS, rows)
    iv = A.analyse(p, charts=False)["intervals"]
    assert iv["arduino"]["n"] == 49
    assert iv["arduino"]["median"] == pytest.approx(381.0)
    assert iv["arduino"]["max"] == pytest.approx(381.0)
    assert iv["host"]["median"] == pytest.approx(381.0, abs=1e-3)


def test_percentile_is_linear():
    d = A.describe(list(range(1, 101)))
    assert d["p95"] == pytest.approx(95.05)
    assert d["median"] == 50.5


def test_status_text_is_not_a_failed_frame(tmp_path):
    def text(m, raw):
        r = {c: "" for c in PACKET_COLUMNS}
        r.update(host_iso="x", host_mono=m, parse_ok=0, reject_reason="not a JSON frame", raw=raw)
        return r
    extra = [text(1.0, "[BH1750] Device is not configured!"),
             text(2.0, '"lux":[1,2],"chk":7}')]          # tail of a broken frame
    r = run(tmp_path, range(9), extra=extra)
    assert r["frame_lines"] == 10                       # 9 good + 1 broken
    assert r["parse_pct"] == pytest.approx(90.0)
    assert r["text_lines"] == {"[BH1750] Device is not configured!": 1}


def test_marker_parsing():
    assert parse_marker("P3 az=45 el=0") == ("P3", 45.0, 0.0)
    assert parse_marker("  p12  el=-30  az=180.5 ") == ("p12", 180.5, -30.0)
    assert parse_marker("P4, az=90, el=10") == ("P4", 90.0, 10.0)
    assert parse_marker("lamp moved") is None
    assert parse_marker("az=45 el=0") is None


def test_pose_error_maths():
    ref = angles_to_vector(45, 0)
    s = pose_stats([ref, ref, ref], 45, 0)
    assert s["error_deg"] == pytest.approx(0.0, abs=1e-6)
    assert s["std_deg"] == pytest.approx(0.0, abs=1e-6)
    s = pose_stats([(0, 0, 1)], 0, 0)
    assert s["error_deg"] == pytest.approx(90.0)
    # two frames 10 deg either side of the reference: mean is exact, std is 0
    s = pose_stats([angles_to_vector(10, 0), angles_to_vector(-10, 0)], 0, 0)
    assert s["error_deg"] == pytest.approx(0.0, abs=1e-6)
    assert s["std_deg"] == pytest.approx(0.0, abs=1e-6)
    # errors of 0 and 20 deg: std = 10
    s = pose_stats([angles_to_vector(0, 0), angles_to_vector(20, 0)], 0, 0)
    assert s["std_deg"] == pytest.approx(10.0)


def test_pose_window_uses_only_the_5_s_after_the_marker(tmp_path):
    ref = angles_to_vector(90, 0)
    wrong = (1.0, 0.0, 0.0)
    rows = [packet(i, i * 1.0, vec=(ref if 10 <= i < 15 else wrong)) for i in range(30)]
    p = write(tmp_path / "endurance_pose.csv", PACKET_COLUMNS, rows)
    write(tmp_path / "endurance_pose_markers.csv", MARKER_COLUMNS,
          [{"host_iso": "x", "host_mono": "10.0", "pose_id": "P1", "az_ref_deg": 90,
            "el_ref_deg": 0, "parse_ok": 1, "last_seq": 9, "text": "P1 az=90 el=0"}])
    poses = A.analyse(p, charts=False)["poses"]
    assert len(poses) == 1
    assert poses[0]["frames_with_estimate"] == 5
    assert poses[0]["error_deg"] == pytest.approx(0.0, abs=1e-6)


def test_downtime_from_events():
    ev = [{"host_mono": "100", "event": "disconnect", "host_iso": "a"},
          {"host_mono": "112.5", "event": "reconnect", "host_iso": "b"},
          {"host_mono": "200", "event": "no_data", "host_iso": "c"},
          {"host_mono": "206", "event": "data_resumed", "host_iso": "d"},
          {"host_mono": "300", "event": "disconnect", "host_iso": "e"},
          {"host_mono": "310", "event": "stop", "host_iso": "f"}]
    o = A.outages(ev, None)
    assert len(o["disconnects"]) == 1
    assert o["downtime_s"] == pytest.approx(12.5 + 10.0)   # last one never came back
    assert o["stall_s"] == pytest.approx(6.0)


@pytest.mark.skipif(not DEFAULT_ESTIMATOR.exists(), reason="single-file ground station not found")
def test_angle_maths_match_the_project_code():
    import numpy as np
    from endurance_common import load_estimator
    est = load_estimator()
    for az, el in [(0, 0), (45, 10), (-120, -40), (179, 80)]:
        assert np.allclose(est.angles_to_vector(az, el), angles_to_vector(az, el))
        a, b = angles_to_vector(az, el), angles_to_vector(az + 7, el - 3)
        assert math.degrees(est.angular_error(np.array(a), np.array(b))) == pytest.approx(
            angle_between_deg(a, b), abs=1e-9)
