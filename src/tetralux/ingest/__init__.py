"""Phase 6: real-hardware ingestion - HTTP + serial into one queue, with a stream-health monitor.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `ingest/` as a package and re-exports the two pieces every caller needs.

This subpackage receives telemetry. Two transports, one destination:

    http_server.py   WiFi. The satellite POSTs packets to /ingest. The project's
                     only `async def` code lives here, because a web server must
                     keep accepting connections while waiting on one.
    serial_reader.py USB. A background thread reassembles whole lines from a raw
                     byte stream, which is what a serial port actually gives you.
    queue.py         the thread-safe buffer both transports feed.
    monitor.py       link health: rate, drops, corruption, connected or not.

NOTE WHAT IS *NOT* RE-EXPORTED. The two transports are absent from this list on
purpose: importing them pulls in optional dependencies (fastapi, uvicorn,
pyserial) that may not be installed. Callers that need one import it directly,
at the moment they need it. StreamMonitor and the queue have no such
dependencies and are always safe.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
"""

from tetralux.ingest.monitor import StreamMonitor
from tetralux.ingest.queue import create_frame_queue

__all__ = ["StreamMonitor", "create_frame_queue"]
