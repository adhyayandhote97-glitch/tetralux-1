#!/usr/bin/env python3
"""Overnight telemetry-reliability + endurance logger for Tetralux-1.

TEMPORARY (delete overnight_test/ when done). Reads the USB serial port
directly - the dashboard must be closed, because only one program can own the
port. Writes three CSVs into overnight_test/test_logs/:

  endurance_<stamp>.csv          every line received (bad lines too, parse_ok=0)
  endurance_<stamp>_events.csv   start/stop, disconnects, reconnects, stalls, resets
  endurance_<stamp>_markers.csv  pose tags you type, e.g.  P3 az=45 el=0

Usage:
  /usr/bin/python3 overnight_test/endurance_log.py --hours 8
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from endurance_common import (  # noqa: E402
    EVENT_COLUMNS, LOG_DIR, MARKER_COLUMNS, PACKET_COLUMNS, TAGS,
    load_estimator, parse_marker, pose_stats,
)

STATUS_EVERY_S = 60.0
VECTOR_EVERY_S = 1.0
FSYNC_EVERY_S = 60.0


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def fmt(v, nd=6):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{nd}g}"
    return str(v)


class CsvSink:
    """CSV file that flushes after every row."""

    def __init__(self, path: Path, columns):
        self.path = path
        self.columns = columns
        self._f = open(path, "w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=columns, extrasaction="raise")
        self._w.writeheader()
        self._f.flush()

    def write(self, row: dict) -> None:
        full = {c: "" for c in self.columns}
        full.update(row)
        self._w.writerow(full)
        self._f.flush()

    def fsync(self) -> None:
        try:
            os.fsync(self._f.fileno())
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._f.flush()
            self.fsync()
            self._f.close()
        except Exception:
            pass


def find_port(preferred: str) -> str | None:
    """The requested port if it exists, else the first /dev/cu.usbmodem*."""
    if preferred != "auto" and os.path.exists(preferred):
        return preferred
    found = sorted(glob.glob("/dev/cu.usbmodem*"))
    return found[0] if found else None


def other_port_users(port: str):
    """Other processes holding the port open, as [(pid, command)]. None if unknown.

    macOS lets two programs open the same serial port; each line then goes to
    whichever reads first, so both get broken data. This is how we notice.
    """
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-t", port], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return None
    users = []
    for tok in out.split():
        if tok.isdigit() and int(tok) != os.getpid():
            try:
                cmd = subprocess.run(["ps", "-p", tok, "-o", "command="], capture_output=True,
                                     text=True, timeout=5).stdout.strip()
            except Exception:
                cmd = "?"
            users.append((int(tok), cmd))
    return users


def stdin_reader(out: "queue.Queue") -> None:
    """Every line typed + Enter goes on the queue with the moment Enter was hit."""
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        if line == "":          # EOF (no terminal attached) - stop quietly
            return
        out.put((time.monotonic(), now_iso(), line.rstrip("\n")))


class Logger:
    def __init__(self, args):
        import serial  # pyserial
        self.serial_mod = serial
        self.args = args
        self.est = load_estimator(args.estimator)

        cal = None
        cal_path = Path(args.calibration).expanduser() if args.calibration else (
            Path(self.est.__file__).with_name("calibration.json"))
        if cal_path.exists():
            cal = self.est.Calibration.load(cal_path)
            self.cal_note = f"calibration from {cal_path}"
        else:
            self.cal_note = "placeholder calibration (no calibration.json found)"
        self.ctx = self.est.make_streaming_context(calibration=cal)

        out_dir = Path(args.out_dir).expanduser() if args.out_dir else LOG_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.stem = out_dir / f"endurance_{stamp}"
        self.packets = CsvSink(Path(f"{self.stem}.csv"), PACKET_COLUMNS)
        self.events = CsvSink(Path(f"{self.stem}_events.csv"), EVENT_COLUMNS)
        self.markers = CsvSink(Path(f"{self.stem}_markers.csv"), MARKER_COLUMNS)

        self.ser = None
        self.port = None
        self.buffer = b""
        self.t_start = time.monotonic()
        self.last_byte_t = None
        self.stalled = False
        self.down_since = None        # monotonic time the port was lost
        self.open_fail_logged = False

        # running numbers for the status line (the analysis recomputes everything)
        self.n_lines = 0
        self.n_valid = 0
        self.n_bad = 0
        self.n_missing = 0
        self.n_resets = 0
        self.prev_seq = None
        self.latest = None            # (seq, vector, az, el, saturated, temps)
        self.pending_poses = []       # [pose, az, el, t_mark, t_end, vectors]
        self.shared_pids = set()

    # ---- events ---------------------------------------------------------------
    def event(self, name: str, detail: str = "") -> None:
        self.events.write({"host_iso": now_iso(), "host_mono": f"{time.monotonic():.6f}",
                           "event": name, "port": self.port or "", "detail": detail})
        print(f"[{datetime.now():%H:%M:%S}] EVENT {name} {detail}".rstrip(), flush=True)

    # ---- serial ---------------------------------------------------------------
    def try_open(self) -> bool:
        port = find_port(self.args.port)
        if port is None:
            if not self.open_fail_logged:
                self.event("open_failed", f"no port found (asked for {self.args.port})")
                self.open_fail_logged = True
            return False
        try:
            # exclusive=True: a second program (e.g. the dashboard) gets an error
            # instead of silently stealing half the bytes
            self.ser = self.serial_mod.Serial(port, self.args.baud, timeout=0.2,
                                              exclusive=True)
        except Exception as exc:
            self.ser = None
            if not self.open_fail_logged:
                self.event("open_failed", f"{port}: {exc}")
                self.open_fail_logged = True
            return False
        if self.port and port != self.port:
            self.event("port_changed", f"{self.port} -> {port}")
        self.port = port
        self.open_fail_logged = False
        self.buffer = b""
        self.last_byte_t = time.monotonic()
        if self.down_since is not None:
            self.event("reconnect", f"down {time.monotonic() - self.down_since:.1f} s")
            self.down_since = None
        else:
            self.event("port_open", f"{port} @ {self.args.baud}")
        return True

    def drop_port(self, why: str) -> None:
        if self.buffer.strip():
            self.handle_line(self.buffer, partial=True)
        self.buffer = b""
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.down_since = time.monotonic()
        self.event("disconnect", why)

    # ---- one line -------------------------------------------------------------
    def handle_line(self, raw: bytes, partial: bool = False) -> None:
        mono = time.monotonic()
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            return
        self.n_lines += 1
        row = {"host_iso": now_iso(), "host_mono": f"{mono:.6f}"}

        if partial or not text.startswith("{"):
            reason = "partial line at disconnect" if partial else "not a JSON frame"
            row.update(parse_ok=0, reject_reason=reason, raw=text)
            self.packets.write(row)
            self.n_bad += 1
            return

        res = self.est.decode_json_frame(text, source="real")
        if isinstance(res, self.est.RejectedFrame):
            row.update(parse_ok=0, reject_reason=res.reason, raw=text,
                       seq="" if res.seq is None else res.seq)
            self.packets.write(row)
            self.n_bad += 1
            return

        f = res
        row.update(parse_ok=1, seq=f.seq, ts_ms=f.timestamp_ms, flags=f.flags, chk=f.checksum,
                   mag_x=f.magnetometer["x"], mag_y=f.magnetometer["y"],
                   mag_z=f.magnetometer["z"])
        for i, t in enumerate(TAGS):
            row[f"pd_{t}"] = f.photodiodes[i]
            row[f"lux_{t}"] = fmt(f.lux[i])
            row[f"temp_{t}"] = fmt(f.temperatures[i])
        for i, o in enumerate(f.opt):
            for k in ("X", "Y", "Z", "lux"):
                row[f"opt{i}_{k}"] = fmt(o[k])

        vec = az = el = None
        sat = []
        try:
            rec = self.est.process(f, self.ctx)
            vec, az, el, sat = rec.sun_vector, rec.azimuth_deg, rec.elevation_deg, rec.saturated_faces
        except Exception as exc:  # estimation failing must never stop logging
            row["reject_reason"] = f"estimate failed: {type(exc).__name__}: {exc}"
        if vec is not None:
            row.update(est_x=fmt(vec[0], 8), est_y=fmt(vec[1], 8), est_z=fmt(vec[2], 8),
                       est_az_deg=fmt(az, 8), est_el_deg=fmt(el, 8))
        row["saturated_faces"] = " ".join(sat)
        self.packets.write(row)

        # sequence bookkeeping for the live status line
        if self.prev_seq is not None:
            d = f.seq - self.prev_seq
            if d == 0:
                self.event("duplicate_seq", f"seq {f.seq}")
            elif d < 0:
                self.n_resets += 1
                self.event("seq_reset", f"{self.prev_seq} -> {f.seq} (board restarted?)")
            elif d > 1:
                self.n_missing += d - 1
        if self.prev_seq is None or f.seq != self.prev_seq:
            self.n_valid += 1
        self.prev_seq = f.seq
        self.latest = (f.seq, vec, az, el, sat, f.temperatures)

        for p in self.pending_poses:
            if p[3] <= mono < p[4] and vec is not None:
                p[5].append(vec)

    # ---- markers --------------------------------------------------------------
    def handle_marker(self, mono: float, iso: str, text: str) -> None:
        if not text.strip():
            return
        parsed = parse_marker(text)
        last = "" if self.prev_seq is None else self.prev_seq
        if parsed is None:
            self.markers.write({"host_iso": iso, "host_mono": f"{mono:.6f}", "parse_ok": 0,
                                "last_seq": last, "text": text})
            print("  -> saved as a NOTE (not a pose). Pose format:  P3 az=45 el=0", flush=True)
            return
        pose, az, el = parsed
        self.markers.write({"host_iso": iso, "host_mono": f"{mono:.6f}", "pose_id": pose,
                            "az_ref_deg": az, "el_ref_deg": el, "parse_ok": 1,
                            "last_seq": last, "text": text})
        w = self.args.window
        self.pending_poses.append([pose, az, el, mono, mono + w, []])
        print(f"  -> marker {pose} saved (az={az:g}, el={el:g}). HOLD STILL {w:g} s...",
              flush=True)

    def finish_poses(self, now: float) -> None:
        keep = []
        for p in self.pending_poses:
            if now < p[4]:
                keep.append(p)
                continue
            s = pose_stats(p[5], p[1], p[2])
            if s["error_deg"] is None:
                print(f"  -> {p[0]} done: no estimates in the window (too dark?)", flush=True)
            else:
                print(f"  -> {p[0]} done: {s['n']} frames, error {s['error_deg']:.1f} deg, "
                      f"std {s['std_deg']:.1f} deg  (targets <=10 / <=5)", flush=True)
        self.pending_poses = keep

    # ---- printing ---------------------------------------------------------------
    def print_vector(self) -> None:
        clock = f"{datetime.now():%H:%M:%S}"
        if self.ser is None:
            print(f"[{clock}] (port disconnected - retrying)", flush=True)
            return
        if self.latest is None or (time.monotonic() - (self.last_byte_t or 0)) > 2.0:
            print(f"[{clock}] (no data)", flush=True)
            return
        seq, vec, az, el, sat, _ = self.latest
        if vec is None:
            print(f"[{clock}] seq {seq}: no sun estimate (too dark)", flush=True)
            return
        satnote = f"  SATURATED {' '.join(sat)}" if sat else ""
        print(f"[{clock}] seq {seq}: sun x={vec[0]:+.3f} y={vec[1]:+.3f} z={vec[2]:+.3f}"
              f"  az={az:+7.1f} el={el:+6.1f}{satnote}", flush=True)

    def check_sharing(self) -> None:
        if not self.port:
            return
        users = other_port_users(self.port) or []
        pids = {pid for pid, _ in users}
        for pid, cmd in users:
            if pid not in self.shared_pids:
                self.event("port_shared", f"pid {pid} also has the port open: {cmd} "
                                          "- data from now on is unreliable, close it")
        self.shared_pids = pids

    def print_status(self) -> None:
        el_s = time.monotonic() - self.t_start
        exp = self.n_valid + self.n_missing
        loss = 100.0 * self.n_missing / exp if exp else 0.0
        temps = "-"
        if self.latest is not None:
            temps = " ".join("--" if t is None else f"{t:.2f}" for t in self.latest[5])
        print(f"===== STATUS {int(el_s // 3600)}h{int(el_s % 3600 // 60):02d}m | "
              f"received {self.n_valid} | bad lines {self.n_bad} | missing {self.n_missing} "
              f"| loss {loss:.2f}% | resets {self.n_resets} | temp C {temps} =====",
              flush=True)

    # ---- main loop ----------------------------------------------------------------
    def run(self) -> None:
        a = self.args
        print(f"[tetralux-endurance] logging to {self.stem}.csv")
        print(f"[tetralux-endurance] estimator: {self.est.__file__}")
        print(f"[tetralux-endurance] {self.cal_note}")
        print("[tetralux-endurance] type a pose tag + Enter at any time, e.g.  P3 az=45 el=0")
        print("[tetralux-endurance] Ctrl+C stops cleanly")
        self.event("start", f"hours={a.hours} port={a.port} baud={a.baud} "
                            f"window={a.window} {self.cal_note}")

        typed: "queue.Queue" = queue.Queue()
        threading.Thread(target=stdin_reader, args=(typed,), daemon=True).start()

        deadline = self.t_start + a.hours * 3600.0
        next_vec = next_status = time.monotonic()
        next_status += STATUS_EVERY_S
        next_fsync = time.monotonic() + FSYNC_EVERY_S
        reason = "finished"
        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    reason = f"finished ({a.hours} h elapsed)"
                    break

                if self.ser is None:
                    if not self.try_open():
                        time.sleep(1.0)
                else:
                    try:
                        chunk = self.ser.read(512)
                    except Exception as exc:
                        self.drop_port(f"read error: {type(exc).__name__}: {exc}")
                        chunk = b""
                    else:
                        # the port can vanish without raising: check it still exists
                        if not chunk and self.port and not os.path.exists(self.port):
                            self.drop_port("port disappeared")
                    if chunk:
                        self.last_byte_t = time.monotonic()
                        if self.stalled:
                            self.stalled = False
                            self.event("data_resumed")
                        self.buffer += chunk
                        while b"\n" in self.buffer:
                            line, self.buffer = self.buffer.split(b"\n", 1)
                            self.handle_line(line)
                        if len(self.buffer) > 8192:    # runaway line with no newline
                            self.handle_line(self.buffer, partial=False)
                            self.buffer = b""
                    elif (self.ser is not None and not self.stalled
                          and time.monotonic() - self.last_byte_t > a.stall_s):
                        self.stalled = True
                        self.event("no_data", f"nothing received for {a.stall_s:g} s")
                    elif (self.ser is not None and self.stalled
                          and time.monotonic() - self.last_byte_t > 3 * a.stall_s):
                        # after a board reset/upload the old handle can stay open but
                        # dead; reopening picks up the board's new USB connection
                        self.drop_port(f"silent for {3 * a.stall_s:g} s - reopening port")

                while not typed.empty():
                    self.handle_marker(*typed.get_nowait())
                now = time.monotonic()
                self.finish_poses(now)
                if not a.no_vector and now >= next_vec:
                    self.print_vector()
                    next_vec = now + VECTOR_EVERY_S
                if now >= next_status:
                    self.check_sharing()
                    self.print_status()
                    next_status = now + STATUS_EVERY_S
                if now >= next_fsync:
                    for s in (self.packets, self.events, self.markers):
                        s.fsync()
                    next_fsync = now + FSYNC_EVERY_S
        except KeyboardInterrupt:
            reason = "stopped by Ctrl+C"
        finally:
            self.print_status()
            self.event("stop", reason)
            try:
                if self.ser is not None:
                    self.ser.close()
            except Exception:
                pass
            for s in (self.packets, self.events, self.markers):
                s.close()
            print(f"[tetralux-endurance] saved {self.stem}.csv (+ _events, _markers)")
            print(f"[tetralux-endurance] analyse with:  /usr/bin/python3 "
                  f"overnight_test/analyse_endurance.py \"{self.stem}.csv\"")


def main() -> None:
    ap = argparse.ArgumentParser(description="Tetralux-1 overnight endurance logger (temporary)")
    ap.add_argument("--hours", type=float, default=8.0, help="stop after this many hours")
    ap.add_argument("--port", default="auto",
                    help="serial port, e.g. /dev/cu.usbmodem1201 (default: first usbmodem)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--window", type=float, default=5.0,
                    help="seconds after a pose marker that count for that pose")
    ap.add_argument("--stall-s", type=float, default=5.0,
                    help="log a no_data event after this many silent seconds")
    ap.add_argument("--estimator", default=None, help="path to personal_project_final_V2.py")
    ap.add_argument("--calibration", default=None,
                    help="calibration.json (default: the one next to the estimator)")
    ap.add_argument("--out-dir", default=None, help="default: overnight_test/test_logs")
    ap.add_argument("--allow-shared", action="store_true",
                    help="start even if another program has the port open (not recommended)")
    ap.add_argument("--no-vector", action="store_true", help="skip the 1 s sun-vector line")
    args = ap.parse_args()

    # `kill` / closing the terminal: stop cleanly, same as Ctrl+C
    def _term(_sig, _frm):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGHUP, _term)

    port = find_port(args.port)
    users = other_port_users(port) if port else None
    if users and not args.allow_shared:
        print(f"[tetralux-endurance] REFUSING TO START: {port} is already open in:")
        for pid, cmd in users:
            print(f"    pid {pid}: {cmd}")
        print("  Two readers split the data and both get broken lines. Close that program")
        print("  (Ctrl+C in its terminal, or quit Arduino IDE / the dashboard), then re-run.")
        raise SystemExit(1)

    Logger(args).run()


if __name__ == "__main__":
    main()
