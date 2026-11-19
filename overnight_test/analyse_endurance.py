#!/usr/bin/env python3
"""Analyse an overnight endurance log from endurance_log.py.

TEMPORARY (delete overnight_test/ when done). Every number comes from the
logged rows; nothing is interpolated or filled in. Anything the log cannot
show is reported as "not measured".

Usage:
  /usr/bin/python3 overnight_test/analyse_endurance.py overnight_test/test_logs/endurance_<stamp>.csv

Writes into the same folder: <stem>_summary.md, <stem>_gaps.csv,
<stem>_buckets.csv, <stem>_poses.csv and (if matplotlib is installed)
<stem>_loss.png, <stem>_intervals.png, <stem>_temperature.png.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from endurance_common import FACES, TAGS, pose_stats  # noqa: E402

BUCKET_S = 300.0                 # 5-minute loss buckets
TELEMETRY_WINDOW_S = 30 * 60.0   # criterion: >= 95 % over 30 min
STRUCTURAL_WINDOW_S = 2 * 3600.0 # structural spec: >= 2 h of operation
TELEMETRY_TARGET = 95.0
ACCURACY_TARGET_DEG = 10.0
REPEAT_TARGET_DEG = 5.0
INTERVAL_SPEC_MS = 10.0


# ---- loading ----------------------------------------------------------------

def _f(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return None if math.isnan(x) else x


def _i(v) -> Optional[int]:
    x = _f(v)
    return None if x is None else int(x)


def is_text_line(row: dict) -> bool:
    """A status message from the firmware/libraries (e.g. '[BH1750] Device is not
    configured!'), not a telemetry frame. Anything with a brace or a frame key in
    it is treated as a (broken) frame, so a damaged packet is never excused."""
    if row.get("parse_ok") == "1":
        return False
    if (row.get("reject_reason") or "") != "not a JSON frame":
        return False
    raw = row.get("raw") or ""
    return not any(tok in raw for tok in ("{", "}", '"seq"', '"chk"', '"pd"'))


def read_csv(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass
class Frame:
    mono: float
    iso: str
    seq: int
    ts_ms: int
    temps: list
    pd: list
    vec: Optional[tuple]
    saturated: bool
    missing_before: int = 0       # frames lost between the previous frame and this one
    after_reset: bool = False


def load_frames(rows: list) -> list:
    out = []
    for r in rows:
        if r.get("parse_ok") != "1":
            continue
        vec = None
        x, y, z = _f(r.get("est_x")), _f(r.get("est_y")), _f(r.get("est_z"))
        if x is not None and y is not None and z is not None:
            vec = (x, y, z)
        out.append(Frame(
            mono=float(r["host_mono"]), iso=r["host_iso"], seq=int(r["seq"]),
            ts_ms=int(r["ts_ms"]), temps=[_f(r.get(f"temp_{t}")) for t in TAGS],
            pd=[_i(r.get(f"pd_{t}")) for t in TAGS], vec=vec,
            saturated=bool((r.get("saturated_faces") or "").strip())))
    return out


# ---- sequence maths -----------------------------------------------------------

@dataclass
class Gap:
    after_seq: int
    before_seq: int
    missing: int
    seconds: float      # host time between the two frames either side
    at_iso: str
    at_mono: float


@dataclass
class SeqResult:
    frames: list                       # unique frames, file order
    gaps: list = field(default_factory=list)
    resets: list = field(default_factory=list)   # (iso, prev_seq, new_seq)
    duplicates: int = 0


def walk_sequence(frames: list) -> SeqResult:
    """Mark each frame with how many frames were lost just before it.

    A seq that goes backwards is a board restart: it starts a new segment and
    no loss is counted across it (the frames lost at a restart are unknowable).
    A repeated seq is a duplicate and is not counted twice.
    """
    res = SeqResult(frames=[])
    prev = None
    for fr in frames:
        if prev is not None:
            d = fr.seq - prev.seq
            if d == 0:
                res.duplicates += 1
                continue
            if d < 0:
                fr.after_reset = True
                res.resets.append((fr.iso, prev.seq, fr.seq))
            elif d > 1:
                fr.missing_before = d - 1
                res.gaps.append(Gap(prev.seq, fr.seq, d - 1, fr.mono - prev.mono,
                                    fr.iso, fr.mono))
        res.frames.append(fr)
        prev = fr
    return res


def reliability(frames: list, t0: float, t1: float) -> dict:
    """received / expected for frames whose host time is in [t0, t1)."""
    sel = [f for f in frames if t0 <= f.mono < t1]
    received = len(sel)
    missing = sum(f.missing_before for f in sel)
    expected = received + missing
    pct = 100.0 * received / expected if expected else None
    return {"received": received, "missing": missing, "expected": expected, "pct": pct}


def buckets(frames: list, all_rows: list, t0: float, width: float = BUCKET_S) -> list:
    if not frames:
        return []
    n = int((frames[-1].mono - t0) // width) + 1
    out = [{"i": i, "start_min": i * width / 60.0, "received": 0, "missing": 0,
            "bad_lines": 0, "_t": [], "_pd": []} for i in range(n)]
    for f in frames:
        b = out[int((f.mono - t0) // width)]
        b["received"] += 1
        b["missing"] += f.missing_before
        ts = [t for t in f.temps if t is not None]
        if ts:
            b["_t"].append(sum(ts) / len(ts))
        if all(p is not None for p in f.pd):
            b["_pd"].append(sum(f.pd))
    for r in all_rows:
        if r.get("parse_ok") == "1" or is_text_line(r):
            continue
        m = _f(r.get("host_mono"))
        if m is None or m < t0:
            continue
        i = int((m - t0) // width)
        if 0 <= i < n:
            out[i]["bad_lines"] += 1
    for b in out:
        exp = b["received"] + b["missing"]
        b["loss_pct"] = 100.0 * b["missing"] / exp if exp else None
        b["mean_temp_c"] = statistics.fmean(b["_t"]) if b["_t"] else None
        b["mean_pd_sum"] = statistics.fmean(b["_pd"]) if b["_pd"] else None
        del b["_t"], b["_pd"]
    return out


def describe(values: list) -> Optional[dict]:
    if not values:
        return None
    s = sorted(values)
    k = 0.95 * (len(s) - 1)               # linear-interpolated 95th percentile
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    p95 = s[lo] + (s[hi] - s[lo]) * (k - lo)
    return {"n": len(s), "mean": statistics.fmean(s), "median": statistics.median(s),
            "min": s[0], "max": s[-1], "p95": p95}


def intervals(frames: list) -> dict:
    """Interval between consecutive frames with no loss and no restart between them."""
    host, ard = [], []
    for a, b in zip(frames, frames[1:]):
        if b.after_reset or b.missing_before or b.seq != a.seq + 1:
            continue
        host.append((b.mono - a.mono) * 1000.0)
        ard.append(float(b.ts_ms - a.ts_ms))
    return {"host_ms": host, "arduino_ms": ard,
            "host": describe(host), "arduino": describe(ard)}


def clock_drift_ppm(frames: list) -> Optional[float]:
    """Arduino millis() vs host clock over the longest restart-free stretch."""
    segs, cur = [], []
    for f in frames:
        if f.after_reset and cur:
            segs.append(cur)
            cur = []
        cur.append(f)
    if cur:
        segs.append(cur)
    seg = max(segs, key=lambda s: s[-1].mono - s[0].mono) if segs else []
    if len(seg) < 2:
        return None
    host_s = seg[-1].mono - seg[0].mono
    ard_s = (seg[-1].ts_ms - seg[0].ts_ms) / 1000.0
    if host_s < 60:
        return None
    return (ard_s - host_s) / host_s * 1e6


def pearson(xs: list, ys: list) -> Optional[float]:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = statistics.fmean(p[0] for p in pairs)
    my = statistics.fmean(p[1] for p in pairs)
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pairs) / math.sqrt(sxx * syy)


# ---- events -------------------------------------------------------------------

def outages(events: list, end_mono: Optional[float]) -> dict:
    """Pair disconnect->reconnect and no_data->data_resumed from the events CSV."""
    disc, stalls = [], []
    open_disc = open_stall = None
    for e in events:
        m = _f(e.get("host_mono"))
        name = e.get("event")
        if name == "disconnect" and open_disc is None:
            open_disc = (m, e.get("host_iso"))
        elif name == "reconnect" and open_disc is not None:
            disc.append((open_disc[1], m - open_disc[0]))
            open_disc = None
        elif name == "no_data" and open_stall is None:
            open_stall = (m, e.get("host_iso"))
        elif name == "data_resumed" and open_stall is not None:
            stalls.append((open_stall[1], m - open_stall[0]))
            open_stall = None
        elif name == "stop":
            end_mono = m if m is not None else end_mono
    unresolved = []
    if open_disc is not None and end_mono is not None:
        unresolved.append(("disconnect", open_disc[1], end_mono - open_disc[0]))
    if open_stall is not None and end_mono is not None:
        unresolved.append(("no_data", open_stall[1], end_mono - open_stall[0]))
    return {
        "disconnects": disc, "stalls": stalls, "unresolved": unresolved,
        "downtime_s": sum(d for _, d in disc) + sum(u[2] for u in unresolved if u[0] == "disconnect"),
        "stall_s": sum(d for _, d in stalls) + sum(u[2] for u in unresolved if u[0] == "no_data"),
        "open_failed": sum(1 for e in events if e.get("event") == "open_failed"),
    }


# ---- poses ----------------------------------------------------------------------

def analyse_poses(frames: list, markers: list, window_s: float = 5.0) -> list:
    out = []
    for mk in markers:
        if mk.get("parse_ok") != "1":
            continue
        m = float(mk["host_mono"])
        az, el = float(mk["az_ref_deg"]), float(mk["el_ref_deg"])
        win = [f for f in frames if m <= f.mono < m + window_s]
        vecs = [f.vec for f in win if f.vec is not None]
        s = pose_stats(vecs, az, el)
        out.append({"pose_id": mk["pose_id"], "marked_at": mk["host_iso"],
                    "az_ref_deg": az, "el_ref_deg": el, "frames_in_window": len(win),
                    "frames_with_estimate": s["n"],
                    "saturated_frames": sum(1 for f in win if f.saturated),
                    "error_deg": s["error_deg"], "std_deg": s["std_deg"],
                    "max_scatter_deg": s["spread_deg"],
                    "mean_vector": s["mean_vector"]})
    return out


# ---- report ---------------------------------------------------------------------

def _p(v, nd=2, unit=""):
    return "not measured" if v is None else f"{v:.{nd}f}{unit}"


def _verdict(value, target, higher_is_better):
    if value is None:
        return "not measured"
    ok = value >= target if higher_is_better else value <= target
    return "PASS" if ok else "FAIL"


def analyse(csv_path: Path, window_s: float = 5.0, charts: bool = True) -> dict:
    rows = read_csv(csv_path)
    stem = Path(str(csv_path)[:-4]) if str(csv_path).endswith(".csv") else Path(csv_path)
    events = read_csv(f"{stem}_events.csv")
    markers = read_csv(f"{stem}_markers.csv")

    seq = walk_sequence(load_frames(rows))
    frames = seq.frames
    total_lines = len(rows)
    ok_lines = sum(1 for r in rows if r.get("parse_ok") == "1")
    text_rows = [r for r in rows if is_text_line(r)]
    frame_lines = total_lines - len(text_rows)
    texts = {}
    for r in text_rows:
        texts[r["raw"]] = texts.get(r["raw"], 0) + 1
    res = {"csv": str(csv_path), "stem": stem, "lines": total_lines, "ok_lines": ok_lines,
           "frame_lines": frame_lines, "text_lines": texts,
           "parse_pct": 100.0 * ok_lines / frame_lines if frame_lines else None,
           "seq": seq, "events": events, "markers": markers, "window_s": window_s}
    reasons = {}
    for r in rows:
        if r.get("parse_ok") != "1" and not is_text_line(r):
            key = (r.get("reject_reason") or "unknown").split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    res["reject_reasons"] = reasons
    if not frames:
        res["empty"] = True
        write_summary(res)
        return res

    t0, t_end = frames[0].mono, frames[-1].mono
    res["t0"], res["duration_s"] = t0, t_end - t0
    res["start_iso"], res["end_iso"] = frames[0].iso, frames[-1].iso
    res["first30"] = reliability(frames, t0, t0 + TELEMETRY_WINDOW_S)
    res["first2h"] = reliability(frames, t0, t0 + STRUCTURAL_WINDOW_S)
    res["full"] = reliability(frames, t0, math.inf)
    res["reached30"] = res["duration_s"] >= TELEMETRY_WINDOW_S
    res["reached2h"] = res["duration_s"] >= STRUCTURAL_WINDOW_S
    res["buckets"] = buckets(frames, rows, t0)
    res["intervals"] = intervals(frames)
    res["drift_ppm"] = clock_drift_ppm(frames)
    end_m = _f(rows[-1].get("host_mono")) if rows else t_end
    res["outages"] = outages(events, end_m)
    res["poses"] = analyse_poses(frames, markers, window_s)

    # worst 30-min stretch (6 consecutive 5-min buckets)
    b = res["buckets"]
    worst = None
    for i in range(0, max(0, len(b) - 5)):
        rec = sum(x["received"] for x in b[i:i + 6])
        mis = sum(x["missing"] for x in b[i:i + 6])
        pct = 100.0 * rec / (rec + mis) if rec + mis else None
        if pct is not None and (worst is None or pct < worst[1]):
            worst = (b[i]["start_min"], pct)
    res["worst30"] = worst

    # temperature per sensor
    temps = {}
    for k, face in enumerate(FACES):
        vals = [f.temps[k] for f in frames if f.temps[k] is not None]
        temps[face] = {"n": len(vals), "missing": len(frames) - len(vals),
                       "first": vals[0] if vals else None, "last": vals[-1] if vals else None,
                       "min": min(vals) if vals else None, "max": max(vals) if vals else None,
                       "mean": statistics.fmean(vals) if vals else None}
    res["temps"] = temps
    bt = [x["mean_temp_c"] for x in b]
    res["r_temp_loss"] = pearson(bt, [x["loss_pct"] for x in b])
    res["r_temp_pd"] = pearson(bt, [x["mean_pd_sum"] for x in b])
    host_by_bucket = [[] for _ in b]
    for a_, b_ in zip(frames, frames[1:]):
        if not b_.missing_before and not b_.after_reset and b_.seq == a_.seq + 1:
            host_by_bucket[int((b_.mono - t0) // BUCKET_S)].append((b_.mono - a_.mono) * 1000)
    res["r_temp_interval"] = pearson(
        bt, [statistics.fmean(h) if h else None for h in host_by_bucket])

    write_tables(res)
    res["charts"] = make_charts(res) if charts else "skipped"
    write_summary(res)
    return res


def write_tables(res: dict) -> None:
    stem = res["stem"]
    with open(f"{stem}_gaps.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["at_iso", "after_seq", "before_seq", "missing_frames", "seconds_between"])
        for g in res["seq"].gaps:
            w.writerow([g.at_iso, g.after_seq, g.before_seq, g.missing, f"{g.seconds:.3f}"])
    with open(f"{stem}_buckets.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["start_min", "received", "missing", "loss_pct", "bad_lines",
                    "mean_temp_c", "mean_pd_sum"])
        for x in res["buckets"]:
            w.writerow([f"{x['start_min']:.0f}", x["received"], x["missing"],
                        "" if x["loss_pct"] is None else f"{x['loss_pct']:.3f}", x["bad_lines"],
                        "" if x["mean_temp_c"] is None else f"{x['mean_temp_c']:.3f}",
                        "" if x["mean_pd_sum"] is None else f"{x['mean_pd_sum']:.1f}"])
    with open(f"{stem}_poses.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pose_id", "marked_at", "az_ref_deg", "el_ref_deg", "frames_in_window",
                    "frames_with_estimate", "saturated_frames", "error_deg", "std_deg",
                    "max_scatter_deg"])
        for p in res["poses"]:
            w.writerow([p["pose_id"], p["marked_at"], p["az_ref_deg"], p["el_ref_deg"],
                        p["frames_in_window"], p["frames_with_estimate"], p["saturated_frames"],
                        "" if p["error_deg"] is None else f"{p['error_deg']:.3f}",
                        "" if p["std_deg"] is None else f"{p['std_deg']:.3f}",
                        "" if p["max_scatter_deg"] is None else f"{p['max_scatter_deg']:.3f}"])


def make_charts(res: dict):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "skipped: matplotlib is not installed"
    stem, made = res["stem"], []
    font = {"family": "sans-serif", "sans-serif": ["Arial", "Helvetica", "DejaVu Sans"]}
    matplotlib.rc("font", **font)

    b = res["buckets"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    xs = [x["start_min"] / 60.0 for x in b]
    ys = [x["loss_pct"] if x["loss_pct"] is not None else 0.0 for x in b]
    ax.bar(xs, ys, width=BUCKET_S / 3600.0 * 0.9, align="edge", color="#3b5b92")
    ax.axhline(100 - TELEMETRY_TARGET, color="#b33", ls="--", lw=1,
               label=f"{100 - TELEMETRY_TARGET:.0f}% loss = 95% reliability limit")
    ax.set_xlabel("hours since first packet")
    ax.set_ylabel("packet loss per 5 min (%)")
    ax.set_title("Tetralux-1 telemetry loss over time")
    ax.set_ylim(0, max(6.0, max(ys) * 1.15 if ys else 6.0))
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{stem}_loss.png", dpi=160)
    plt.close(fig)
    made.append(f"{stem.name}_loss.png")

    iv = res["intervals"]
    if iv["arduino_ms"]:
        fig, axs = plt.subplots(1, 2, figsize=(9, 3.6))
        for ax, key, title in ((axs[0], "arduino_ms", "Arduino side (millis)"),
                               (axs[1], "host_ms", "laptop side (arrival)")):
            data = iv[key]
            ax.hist(data, bins=60, color="#3b5b92")
            ax.set_title(title)
            ax.set_xlabel("interval between packets (ms)")
            ax.set_ylabel("count")
            ax.axvline(statistics.median(data), color="#b33", lw=1,
                       label=f"median {statistics.median(data):.1f} ms")
            ax.legend(fontsize=8)
        fig.suptitle("Tetralux-1 update interval")
        fig.tight_layout()
        fig.savefig(f"{stem}_intervals.png", dpi=160)
        plt.close(fig)
        made.append(f"{stem.name}_intervals.png")

    frames = res["seq"].frames
    if any(t["n"] for t in res["temps"].values()):
        fig, ax = plt.subplots(figsize=(9, 3.8))
        step = max(1, len(frames) // 4000)      # thin for plotting only
        for k, face in enumerate(FACES):
            pts = [((f.mono - res["t0"]) / 3600.0, f.temps[k]) for f in frames[::step]
                   if f.temps[k] is not None]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], lw=1, label=face)
        ax.set_xlabel("hours since first packet")
        ax.set_ylabel("DS18B20 temperature (°C)")
        ax.set_title("Tetralux-1 face temperatures")
        ax.legend(ncol=6, fontsize=8, loc="upper center")
        fig.tight_layout()
        fig.savefig(f"{stem}_temperature.png", dpi=160)
        plt.close(fig)
        made.append(f"{stem.name}_temperature.png")
    return made


def write_summary(res: dict) -> None:
    L = []
    w = L.append
    s = res["seq"]
    w("# Tetralux-1 overnight endurance test - results\n")
    w(f"Log: `{Path(res['csv']).name}`  ")
    if res.get("empty"):
        w("\n**No valid packets in this log.** Nothing can be measured.\n")
        Path(f"{res['stem']}_summary.md").write_text("\n".join(L))
        return
    dur_h = res["duration_s"] / 3600.0
    w(f"First packet {res['start_iso']}, last packet {res['end_iso']} "
      f"({dur_h:.2f} h, {res['duration_s'] / 60:.1f} min).  ")
    w("All figures are computed from logged rows only; nothing is interpolated.\n")

    f30, f2h, full = res["first30"], res["first2h"], res["full"]
    out = res["outages"]
    w("## Success criteria\n")
    w("| Criterion | Target | Measured | Result |")
    w("|---|---|---|---|")
    t30 = f30["pct"] if res["reached30"] else None
    w(f"| Telemetry reliability, first 30 min | >= 95 % | "
      f"{_p(f30['pct'], 3, ' %')} ({f30['received']}/{f30['expected']})"
      f"{'' if res['reached30'] else ' - run shorter than 30 min'} | "
      f"{_verdict(t30, TELEMETRY_TARGET, True)} |")
    ran2h = res["reached2h"]
    w(f"| Structural integrity: continuous operation | >= 2 h | {dur_h:.2f} h logged, "
      f"{len(out['disconnects']) + len(out['unresolved'])} disconnect(s), "
      f"{len(s.resets)} board restart(s) | "
      f"{'PASS' if ran2h and not s.resets and not out['disconnects'] and not out['unresolved'] else ('FAIL' if ran2h else 'not measured (run < 2 h)')} |")
    w(f"| Telemetry reliability, first 2 h | (structural spec) | "
      f"{_p(f2h['pct'], 3, ' %')} ({f2h['received']}/{f2h['expected']}) | "
      f"{_verdict(f2h['pct'] if ran2h else None, TELEMETRY_TARGET, True)} |")
    w(f"| Telemetry reliability, full run | (for reference) | "
      f"{_p(full['pct'], 3, ' %')} ({full['received']}/{full['expected']}) | "
      f"{_verdict(full['pct'], TELEMETRY_TARGET, True)} |")
    poses = [p for p in res["poses"] if p["error_deg"] is not None]
    if poses:
        mean_err = statistics.fmean(p["error_deg"] for p in poses)
        max_std = max(p["std_deg"] for p in poses)
        n_std_ok = sum(1 for p in poses if p["std_deg"] <= REPEAT_TARGET_DEG)
        w(f"| Sun-direction accuracy, mean over {len(poses)} pose(s) | <= 10 deg | "
          f"{mean_err:.2f} deg | {_verdict(mean_err, ACCURACY_TARGET_DEG, False)} |")
        w(f"| Repeatability, std per pose | <= 5 deg | {n_std_ok}/{len(poses)} poses within, "
          f"worst {max_std:.2f} deg | {_verdict(max_std, REPEAT_TARGET_DEG, False)} |")
    else:
        w("| Sun-direction accuracy | <= 10 deg | no pose markers with estimates | not measured |")
        w("| Repeatability | <= 5 deg | no pose markers with estimates | not measured |")
    w("")

    w("## Packets\n")
    w(f"- Lines received: {res['lines']}, of which {res['frame_lines']} were telemetry "
      f"frames; parsed and checksum-valid: {res['ok_lines']} "
      f"(**parse success {_p(res['parse_pct'], 3, ' %')}** of frames).")
    if res["text_lines"]:
        w("- Non-frame status text from the board (logged, not counted as frames): " + "; ".join(
            f"`{t}` x{n}" for t, n in sorted(res["text_lines"].items(), key=lambda kv: -kv[1])[:5]))
    if res["reject_reasons"]:
        w("- Broken / rejected frames by reason: " + ", ".join(
            f"{k} x{v}" for k, v in sorted(res["reject_reasons"].items())))
    w(f"- Unique valid frames: {len(s.frames)}; duplicates ignored: {s.duplicates}.")
    w(f"- Board restarts (seq went backwards): {len(s.resets)}"
      + ("" if not s.resets else " - " + "; ".join(f"{a} ({b} -> {c})" for a, b, c in s.resets))
      + ". Frames lost exactly at a restart cannot be counted from seq numbers.")
    w("")

    w("## Gaps in the sequence numbers\n")
    if not s.gaps:
        w("No gaps: every sequence number between the first and last frame arrived.\n")
    else:
        longest = max(s.gaps, key=lambda g: g.missing)
        w(f"- {len(s.gaps)} gap(s), {sum(g.missing for g in s.gaps)} frames missing in total.")
        w(f"- Longest gap: {longest.missing} frame(s) ({longest.seconds:.2f} s), after seq "
          f"{longest.after_seq}, at {longest.at_iso}.")
        sizes = {}
        for g in s.gaps:
            sizes[g.missing] = sizes.get(g.missing, 0) + 1
        w("- Gap sizes (frames: count): " + ", ".join(f"{k}: {v}" for k, v in sorted(sizes.items())))
        w(f"- Full list: `{Path(str(res['stem'])).name}_gaps.csv`.")
        w("")
    b = res["buckets"]
    lossy = [x for x in b if x["missing"]]
    total_missing = sum(x["missing"] for x in b)
    w(f"**Loss per 5-minute bucket** ({len(b)} buckets, `{Path(str(res['stem'])).name}_buckets.csv`): "
      f"{len(lossy)} bucket(s) had any loss.")
    if total_missing:
        top = max(b, key=lambda x: x["missing"])
        share = 100.0 * top["missing"] / total_missing
        pattern = ("concentrated in bursts" if len(lossy) <= max(1, 0.1 * len(b)) or share >= 50
                   else "spread across the run")
        w(f" The worst bucket (starting {top['start_min']:.0f} min) holds {share:.0f}% of all "
          f"lost frames - losses are **{pattern}**.")
    if res["worst30"]:
        w(f" Worst 30-minute stretch: {res['worst30'][1]:.3f} % (starting "
          f"{res['worst30'][0]:.0f} min).")
    w("")

    w("## Update interval\n")
    iv = res["intervals"]
    w("Only consecutive frames (no loss, no restart between them) are used.\n")
    w("| Side | n | mean | median | min | max | 95th pct |")
    w("|---|---|---|---|---|---|---|")
    for name, key in (("Arduino millis()", "arduino"), ("Laptop arrival", "host")):
        d = iv[key]
        if d:
            w(f"| {name} | {d['n']} | {d['mean']:.2f} ms | {d['median']:.2f} ms | "
              f"{d['min']:.2f} ms | {d['max']:.2f} ms | {d['p95']:.2f} ms |")
    a = iv["arduino"]
    if a:
        w(f"\nSpec: {INTERVAL_SPEC_MS:.0f} ms. Measured median: **{a['median']:.1f} ms** "
          f"(~{1000.0 / a['median']:.2f} packets/s) - "
          + ("meets the spec." if a["median"] <= INTERVAL_SPEC_MS else
             f"does **not** meet the 10 ms spec; the real interval is "
             f"{a['median'] / INTERVAL_SPEC_MS:.0f}x longer."))
    if res["drift_ppm"] is not None:
        w(f"\nArduino clock vs laptop clock: {res['drift_ppm']:+.0f} ppm "
          f"({res['drift_ppm'] * 3600 / 1e6:+.2f} s per hour).")
    w("")

    w("## DS18B20 temperatures\n")
    w("| Face | readings | missing | first | last | min | max | mean |")
    w("|---|---|---|---|---|---|---|---|")
    for face, t in res["temps"].items():
        w(f"| {face} | {t['n']} | {t['missing']} | {_p(t['first'])} | {_p(t['last'])} | "
          f"{_p(t['min'])} | {_p(t['max'])} | {_p(t['mean'])} |")
    w("\nCorrelation across 5-minute buckets (Pearson r; |r| < 0.3 is weak):")
    w(f"- mean temperature vs packet loss: {_p(res['r_temp_loss'], 2)}")
    w(f"- mean temperature vs update interval: {_p(res['r_temp_interval'], 2)}")
    w(f"- mean temperature vs summed photodiode counts: {_p(res['r_temp_pd'], 2)}")
    w("(Correlation is not cause - room temperature and light also change overnight.)\n")

    w("## Disconnects and downtime\n")
    w(f"- USB disconnects with reconnect: {len(out['disconnects'])}"
      + ("" if not out["disconnects"] else " - " + "; ".join(
          f"{a} ({d:.1f} s)" for a, d in out["disconnects"])))
    for kind, at, d in out["unresolved"]:
        w(f"- {kind} at {at} never recovered before the log ended ({d:.1f} s).")
    w(f"- Total port downtime: {out['downtime_s']:.1f} s.")
    w(f"- Silent periods (port open, no data for >= 5 s): {len(out['stalls'])}, "
      f"total {out['stall_s']:.1f} s.")
    w("")

    w("## Pose markers\n")
    if not res["poses"]:
        w("No pose markers in this log.\n")
    else:
        w(f"Each pose uses the estimates logged in the {res.get('window_s', 5):g} s after its "
          "marker. error = arccos(mean estimate . reference); std = spread of per-frame errors.\n")
        w("| Pose | az ref | el ref | frames | saturated | error | std |")
        w("|---|---|---|---|---|---|---|")
        for p in res["poses"]:
            w(f"| {p['pose_id']} | {p['az_ref_deg']:g} | {p['el_ref_deg']:g} | "
              f"{p['frames_with_estimate']}/{p['frames_in_window']} | {p['saturated_frames']} | "
              f"{_p(p['error_deg'], 2, ' deg')} | {_p(p['std_deg'], 2, ' deg')} |")
        notes = [m for m in res["markers"] if m.get("parse_ok") != "1"]
        if notes:
            w("\nNotes typed during the run: " + "; ".join(
                f"{m['host_iso']}: {m['text']}" for m in notes))
        w("")

    w("## Charts\n")
    if isinstance(res["charts"], list):
        for c in res["charts"]:
            w(f"![{c}]({c})")
    else:
        w(f"Charts {res['charts']}.")
    Path(f"{res['stem']}_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyse a Tetralux-1 endurance log (temporary)")
    ap.add_argument("csv", help="overnight_test/test_logs/endurance_<stamp>.csv")
    ap.add_argument("--window", type=float, default=5.0,
                    help="seconds after each pose marker to average (default 5)")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args()
    p = Path(a.csv).expanduser()
    if not p.exists():
        raise SystemExit(f"no such file: {p}")
    res = analyse(p, a.window, charts=not a.no_charts)
    print((Path(f"{res['stem']}_summary.md")).read_text())
    print(f"[analysis] wrote {res['stem']}_summary.md (+ _gaps.csv, _buckets.csv, _poses.csv)")
    if isinstance(res.get("charts"), str):
        print(f"[analysis] charts {res['charts']}")


if __name__ == "__main__":
    main()
