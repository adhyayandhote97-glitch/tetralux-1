"""Shared ingest queue helper (Phase 6).

Both transports (HTTP and serial) forward raw JSON strings to one place. This
thin module centralizes that as a thread-safe ``queue.Queue`` so producers
(FastAPI handler thread, serial thread) and the processing consumer are
decoupled without asyncio event-loop binding concerns.
"""

from __future__ import annotations

import queue as _queue


def create_frame_queue(maxsize: int = 10000) -> "_queue.Queue":
    """Create a bounded thread-safe queue of raw telemetry strings."""
    return _queue.Queue(maxsize=maxsize)
