"""Shared ingest queue helper (Phase 6)."""

from __future__ import annotations

import queue as _queue


def create_frame_queue(maxsize: int = 10000) -> "_queue.Queue":
    """Create a bounded thread-safe queue of raw telemetry strings."""
    return _queue.Queue(maxsize=maxsize)
