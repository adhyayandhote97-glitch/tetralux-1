"""Ground-station runner - the real-hardware path (Phase 9).

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the program you actually run when a physical prototype is transmitting:

    python -m tetralux.groundstation --port 8000 --record

It is the assembly point for the real path. Every piece it uses is built
elsewhere; this file wires them together and starts them:

    receive (HTTP or serial)  ->  queue  ->  decode  ->  process  ->  log

THE QUEUE IN THE MIDDLE IS THE KEY DESIGN CHOICE. Packets arrive on the web
server's thread, and processing one takes a few milliseconds. If the server
processed each packet itself, it would be busy doing maths while the next packet
was arriving, and packets would be dropped. So the receiving side does the
absolute minimum, putting raw text into a queue, and a separate background
thread takes items out and does the real work. The queue absorbs bursts: a
sudden run of packets piles up harmlessly instead of being lost.

That structure is why the receiving code takes a callback. `frame_queue.put_nowait`
is passed as the on_frame function to both transports, so neither the HTTP
server nor the serial reader knows anything about decoding or logging.

THIS IS ALSO ONE OF THE THREE FILES THAT USE print(). Everything else in the
project is a library: it computes values and returns them. This is a
command-line program a person watches, so it prints status directly to the
terminal. print() shows text and discards it; it is not how a program returns a
value (see docs/python-primer.md, section 2).

WHERE IT SITS IN THE FLOW
    ingest/            supplies both transports and the queue
    telemetry/         decodes each raw line
    pipeline.py        processes each accepted frame
    store/session.py   writes records to disk and Firebase

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# argparse: builds command-line interfaces, so --port and --record work.
import argparse
# queue: the thread-safe handoff between receiving and processing.
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


# --- Start everything and run until interrupted ---
#
# PARAMETERS
#   host        - which network interface to listen on. "0.0.0.0" means all of
#                 them, so the Arduino can reach this machine over WiFi.
#   port        - the TCP port to listen on. Must match the firmware's config.
#   record      - whether to log to disk. DEFAULTS TO FALSE, deliberately:
#                 recording is a decision the operator makes explicitly, so a
#                 quick connectivity check does not silently create session
#                 files.
#   serial_port - a device path for USB, or None for WiFi only. Passing this
#                 runs BOTH transports at once, which is useful while debugging.
#   base_dir    - where session logs are written.
#   online_store- a Firebase store, or None for local logging only.
#   calibration - this prototype's measured parameters, or None for the
#                 placeholder defaults.
# RETURNS
#   None, and not until the server stops. "Blocking" means exactly that.
def run(host: str = "0.0.0.0", port: int = 8000, record: bool = False,
        serial_port: "str | None" = None, base_dir: str = "data/logs",
        online_store=None, calibration: "Calibration | None" = None) -> None:
    """Run the ingest server + processing loop (blocking)."""
    # The buffer between receiving and processing. A queue is THREAD-SAFE: two
    # threads can add and remove at the same time without corrupting it. An
    # ordinary list cannot promise that.
    frame_queue = create_frame_queue()
    monitor = StreamMonitor()
    # A STREAMING context, so it carries a rolling validator and a thermal
    # analyzer. A plain PipelineContext would leave bias, repeatability and
    # drift permanently None, since those need history (see pipeline.py).
    ctx = make_streaming_context(monitor=monitor, calibration=calibration)
    session = SessionController(base_dir, online_store)
    if record:
        info = session.start()
        # print, not logging: this is a person at a terminal who needs to see
        # which session id their data is going into.
        print(f"[tetralux] recording session {info.session_id}")

    # The shutdown flag shared with the worker thread below (see
    # ingest/serial_reader.py for why an Event rather than a boolean).
    stop = threading.Event()

    # A NESTED FUNCTION defined inside run(), so it can see frame_queue,
    # monitor, ctx and session directly without them being passed in. This is
    # the consumer half of the queue.
    def process_loop():
        while not stop.is_set():
            try:
                # Wait for an item, giving up after 0.2 seconds. The timeout is
                # what makes shutdown possible: without it this would block
                # forever on a silent link and never re-check the stop flag.
                raw = frame_queue.get(timeout=0.2)
            except queue.Empty:
                # Nothing arrived in that window. Loop around, which re-checks
                # the flag. Not an error, just a quiet moment.
                continue
            result = decode_json_frame(raw, source="real")
            # decode returns one of two types, so the type IS the verdict (see
            # frames.py). A rejected frame is counted and discarded, and
            # `continue` guarantees it can never reach process().
            if isinstance(result, RejectedFrame):
                monitor.record_rejected(result)
                continue
            monitor.record_accepted(result)
            # The whole pipeline in one line: process() builds the record, and
            # session.record() writes it. session.record does nothing unless
            # recording was started, so this line is correct either way.
            session.record(process(result, ctx))

    # Launch the consumer. target=process_loop with no brackets passes the
    # function itself; with brackets it would run here and block forever.
    worker = threading.Thread(target=process_loop, daemon=True)
    worker.start()

    reader = None
    if serial_port:
        # Lazy import so pyserial is only required when USB is actually used.
        from tetralux.ingest.serial_reader import SerialReader

        # THE CALLBACK. frame_queue.put_nowait is passed as the on_frame
        # function, so the reader's only job is to drop text into the queue.
        # put_nowait rather than put: it never blocks, so a full queue cannot
        # stall the reading thread and cause bytes to be missed at the port.
        reader = SerialReader(frame_queue.put_nowait, serial_port)
        reader.start()
        print(f"[tetralux] serial reader on {serial_port}")

    # Printed before the blocking call below, so the operator sees the address
    # to configure in the firmware.
    print(f"[tetralux] ingest server on http://{host}:{port}/ingest")
    # try/finally, with no `except`. That combination means: run this, and
    # whatever happens, run the cleanup afterwards. There is no except because
    # the goal is not to handle errors, it is to guarantee cleanup on ANY exit,
    # including Ctrl-C, which is how this program normally ends.
    try:
        # The identical callback goes to the HTTP server, which is why both
        # transports can run simultaneously and feed one queue. This call
        # blocks until the server stops.
        run_ingest_server(frame_queue.put_nowait, host=host, port=port, monitor=monitor)
    finally:
        # Without this, Ctrl-C would leave the worker thread running, the serial
        # port open, and the session file unclosed with its last records
        # possibly unwritten.
        stop.set()
        if reader is not None:
            reader.stop()
        if record:
            session.stop()


# --- The command-line entry point ---
#
# PARAMETERS: none. It reads the command line instead.
# RETURNS: None.
#
# argparse turns text typed in a terminal into Python values, and generates
# --help automatically from the definitions below.
def main() -> None:
    ap = argparse.ArgumentParser(description="Tetralux-1 ground station (real path)")
    ap.add_argument("--host", default="0.0.0.0")
    # type=int converts the text "8000" into the number 8000, and rejects
    # non-numeric input with a clear message rather than failing later.
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--serial", default=None, help="serial port (USB fallback)")
    # action="store_true" makes this a FLAG: writing --record sets it True, and
    # omitting it leaves False. No value is typed after it.
    ap.add_argument("--record", action="store_true",
                    help="start a logging session (off by default)")
    # argparse converts --base-dir on the command line into args.base_dir.
    ap.add_argument("--base-dir", default="data/logs")
    ap.add_argument("--calibration", default=None,
                    help="path to a calibration.json from calibration_tool.py "
                         "(defaults to built-in placeholder values)")
    args = ap.parse_args()
    # Lazy import again: this reaches for Firebase, an optional dependency.
    from tetralux.store import make_online_store

    # Load the file only if one was named; otherwise None, and the pipeline uses
    # the placeholder defaults.
    calibration = Calibration.load(args.calibration) if args.calibration else None

    run(host=args.host, port=args.port, record=args.record,
        serial_port=args.serial, base_dir=args.base_dir,
        online_store=make_online_store(), calibration=calibration)


# THE STANDARD PYTHON ENTRY-POINT GUARD.
#
# `__name__` is a variable Python sets automatically in every file. When a file
# is RUN directly it is "__main__"; when the file is merely IMPORTED by another,
# it is the module's name instead.
#
# So this line means "only call main() if this file was run directly". Without
# it, importing anything from this module would immediately start a web server,
# which would make the file impossible to test or reuse.
if __name__ == "__main__":
    main()
