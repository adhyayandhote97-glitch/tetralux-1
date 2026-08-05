"""Ground-station runner - the real-hardware path (Phase 9)."""

from __future__ import annotations

import argparse
import queue
import threading

from tetralux.calibration import Calibration
from tetralux.frames import RejectedFrame
from tetralux.ingest.http_server import run_ingest_server
from tetralux.ingest.monitor import StreamMonitor
from tetralux.ingest.queue import create_frame_queue
from tetralux.pipeline import make_streaming_context, process
from tetralux.store.session import SessionController
from tetralux.telemetry.json_frame import decode_json_frame


def run(host: str = "0.0.0.0", port: int = 8000, record: bool = False,
        serial_port: "str | None" = None, base_dir: str = "data/logs",
        online_store=None, calibration: "Calibration | None" = None) -> None:
    """Run the ingest server + processing loop (blocking)."""
    frame_queue = create_frame_queue()
    monitor = StreamMonitor()
    ctx = make_streaming_context(monitor=monitor, calibration=calibration)
    session = SessionController(base_dir, online_store)
    if record:
        info = session.start()
        print(f"[tetralux] recording session {info.session_id}")

    stop = threading.Event()

    def process_loop():
        while not stop.is_set():
            try:
                raw = frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            result = decode_json_frame(raw, source="real")
            if isinstance(result, RejectedFrame):
                monitor.record_rejected(result)
                continue
            monitor.record_accepted(result)
            session.record(process(result, ctx))

    worker = threading.Thread(target=process_loop, daemon=True)
    worker.start()

    reader = None
    if serial_port:
        from tetralux.ingest.serial_reader import SerialReader

        reader = SerialReader(frame_queue.put_nowait, serial_port)
        reader.start()
        print(f"[tetralux] serial reader on {serial_port}")

    print(f"[tetralux] ingest server on http://{host}:{port}/ingest")
    try:
        run_ingest_server(frame_queue.put_nowait, host=host, port=port, monitor=monitor)
    finally:
        stop.set()
        if reader is not None:
            reader.stop()
        if record:
            session.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Tetralux-1 ground station (real path)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--serial", default=None, help="serial port (USB fallback)")
    ap.add_argument("--record", action="store_true",
                    help="start a logging session (off by default)")
    ap.add_argument("--base-dir", default="data/logs")
    ap.add_argument("--calibration", default=None,
                    help="path to a calibration.json from calibration_tool.py "
                         "(defaults to built-in placeholder values)")
    args = ap.parse_args()
    from tetralux.store import make_online_store

    calibration = Calibration.load(args.calibration) if args.calibration else None

    run(host=args.host, port=args.port, record=args.record,
        serial_port=args.serial, base_dir=args.base_dir,
        online_store=make_online_store(), calibration=calibration)


if __name__ == "__main__":
    main()
