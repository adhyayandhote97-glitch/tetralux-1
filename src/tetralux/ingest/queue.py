"""Shared ingest queue helper (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
One tiny function, and a genuinely important piece of the architecture.

THE PROBLEM IT SOLVES. Packets arrive on one thread (the web server or the
serial reader) and are processed on another. Processing one takes a few
milliseconds, so if the receiving side did the work itself it would be busy
doing maths while the next packet was arriving, and packets would be lost.

A queue decouples them. The receiver's only job is to drop raw text in, which is
almost instant; a separate thread takes items out and does the real work. A
sudden burst piles up harmlessly instead of being dropped.

WHY A queue.Queue RATHER THAN A LIST. It is THREAD-SAFE: two threads can add and
remove at the same moment without corrupting it. An ordinary list makes no such
promise, and the resulting bugs are intermittent and nearly impossible to
reproduce.

WHY BOUNDED. maxsize caps how many items can wait. Without a cap, a processing
thread that stalled would let the queue grow until the machine ran out of
memory. Bounded, the queue refuses new items instead, and the callers use
put_nowait so they drop the newest frame rather than blocking the receiver.

Losing one frame is a small, visible cost that the StreamMonitor's counters
reveal. Exhausting memory takes down the whole ground station.

WHERE IT SITS IN THE FLOW
    ingest/http_server.py    puts raw text in, via a callback
    ingest/serial_reader.py  the same, from USB
    groundstation.py         takes items out on its processing thread
    dashboard/state.py       likewise, for the dashboard's Real mode

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# `as _queue` renames the standard library module on import, because the FILE is
# also called queue.py. Without the rename, `import queue` inside this file
# could be ambiguous, and the leading underscore marks it as internal so it does
# not become part of this module's public surface.
import queue as _queue


# PARAMETER
#   maxsize - how many raw frames may wait before the queue refuses more. At
#             about 10 packets per second, 10000 is roughly 16 minutes of
#             backlog: far more headroom than any real stall needs, while still
#             being a hard ceiling on memory.
# RETURNS
#   a new empty thread-safe queue.
#
# A one-line function rather than calling queue.Queue directly at each site, so
# the size limit is decided in ONE place. Three separate callers create queues,
# and without this they could each pick a different limit.
def create_frame_queue(maxsize: int = 10000) -> "_queue.Queue":
    """Create a bounded thread-safe queue of raw telemetry strings."""
    # RAW STRINGS go in, not decoded frames. Decoding is work, and doing it on
    # the receiving thread would defeat the purpose of the queue.
    return _queue.Queue(maxsize=maxsize)
