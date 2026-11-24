"""Summarise a Tetralux-1 endurance log and draw its plots.

usage: python scripts/summarize_endurance.py [log.csv]
Writes summary.txt next to the log and PNGs into plots/.
"""
import csv
import statistics as st
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = Path(sys.argv[1] if len(sys.argv) > 1 else "data/endurance-test/endurance_20261120_010001.csv")
FACES = ["px", "nx", "py", "ny", "pz", "nz"]
SENSORS = ([f"pd_{f}" for f in FACES] + [f"lux_{f}" for f in FACES] + ["mag_x", "mag_y", "mag_z"]
           + [f"opt{i}_{c}" for i in range(4) for c in ("X", "Y", "Z", "lux")] + [f"temp_{f}" for f in FACES])

rows = list(csv.DictReader(LOG.open(newline="")))
frames = [r for r in rows if r["parse_ok"] == "1"]
other = Counter(r["raw"] for r in rows if r["parse_ok"] != "1")
t = [datetime.fromisoformat(r["host_iso"]) for r in frames]
hours = [(x - t[0]).total_seconds() / 3600 for x in t]
seq = [int(r["seq"]) for r in frames]
ts = [int(r["ts_ms"]) for r in frames]

missing, gaps, restarts, dupes = 0, [], 0, 0
for a, b in zip(seq, seq[1:]):
    if b < a:
        restarts += 1
    elif b == a:
        dupes += 1
    elif b > a + 1:
        missing += b - a - 1
        gaps.append((a, b))

# board-side interval, only between consecutive frames
iv = [(h, y - x) for h, a, b, x, y in zip(hours[1:], seq, seq[1:], ts, ts[1:]) if b == a + 1]
ivs = [d for _, d in iv]
med = st.median(ivs)
slow = [d for d in ivs if d > 1.5 * med]
host = [r["host_mono"] for r in rows]
silent = sum(1 for a, b in zip(host, host[1:]) if float(b) - float(a) > 2.0)

out = [f"Log: {LOG.name}",
       f"Duration: {t[0]:%Y-%m-%d %H:%M:%S} -> {t[-1]:%H:%M:%S} ({(t[-1] - t[0]).total_seconds() / 3600:.2f} h)",
       f"Lines received: {len(rows)}; valid frames: {len(frames)}; other lines: {len(rows) - len(frames)}",
       f"Missing frames (seq gaps): {missing} in {len(gaps)} gap(s); duplicates: {dupes}; board restarts: {restarts}",
       f"Expected frames {seq[-1] - seq[0] + 1}, received {len(frames)} -> {100 * len(frames) / (seq[-1] - seq[0] + 1):.3f} %",
       f"Interval (Arduino millis): median {med} ms, min {min(ivs)}, max {max(ivs)}, >1.5x median: {len(slow)}",
       f"Silent periods > 2 s (laptop clock): {silent}", "",
       f"{'sensor':<10}{'min':>10}{'max':>10}{'mean':>10}"]
stuck = []
for s in SENSORS:
    v = [float(r[s]) for r in frames if r[s] not in ("", "nan", "NaN")]
    if not v:
        out.append(f"{s:<10}{'no data':>30}")
        continue
    out.append(f"{s:<10}{min(v):>10.2f}{max(v):>10.2f}{st.fmean(v):>10.2f}")
    if min(v) == max(v):
        stuck.append(f"{s}={v[0]:g}")
out += ["", "Anomalies:",
        f"- sensors constant for the whole run: {', '.join(stuck) or 'none'}",
        *[f"- non-frame line x{n}: {text}" for text, n in other.most_common(3)],
        *[f"- gap: seq {a} -> {b}" for a, b in gaps[:20]]]
if not (stuck or other or gaps or restarts or slow or silent):
    out.append("- none")

text = "\n".join(out)
print(text)
(LOG.parent / "summary.txt").write_text(text + "\n")

plots = LOG.parent / "plots"
plots.mkdir(exist_ok=True)

def minute_means(col):
    # 1-minute means keep 69k points readable
    buckets = {}
    for h, r in zip(hours, frames):
        if r[col] not in ("", "nan", "NaN"):
            buckets.setdefault(int(h * 60), []).append(float(r[col]))
    k = sorted(buckets)
    return [m / 60 for m in k], [st.fmean(buckets[m]) for m in k]

for name, prefix, ylabel, title in [("photodiodes.png", "pd_", "ADC counts (0-4095)", "Photodiode"),
                                    ("temperature.png", "temp_", "Temperature (°C)", "DS18B20 temperature")]:
    fig, ax = plt.subplots(figsize=(9, 4))
    for f in FACES:
        ax.plot(*minute_means(prefix + f), label=f.replace("p", "+").replace("n", "-"), lw=1)
    ax.set(xlabel="Hours since start", ylabel=ylabel, title=f"{title} per face, 1-minute means")
    ax.legend(ncol=6, fontsize=8)
    fig.tight_layout()
    fig.savefig(plots / name, dpi=120)
    plt.close(fig)

fig, ax = plt.subplots(figsize=(9, 4))
arrive = [1000 * (float(b["host_mono"]) - float(a["host_mono"])) for a, b in zip(frames, frames[1:])]
ax.plot(hours[1:], arrive, ".", ms=1, color="0.7", label="laptop arrival (USB jitter)")
ax.plot([h for h, _ in iv], ivs, ".", ms=1, label="board millis()")
ax.set(xlabel="Hours since start", ylabel="Interval between frames (ms)", ylim=(0, 800),
       title=f"Sample-rate stability (board median {med} ms)")
ax.legend(markerscale=10, fontsize=8)
fig.tight_layout()
fig.savefig(plots / "sample_interval.png", dpi=120)
plt.close(fig)
