"""Phase 6: real-hardware ingestion — HTTP + serial into one queue, with a
stream-health monitor.

``http_server`` / ``serial_reader`` need the ``ingest`` extra (fastapi, pyserial)
and are imported lazily by their own modules; only the pure ``StreamMonitor`` and
queue helper are re-exported here so importing the package stays light.
"""

from tetralux.ingest.monitor import StreamMonitor
from tetralux.ingest.queue import create_frame_queue

__all__ = ["StreamMonitor", "create_frame_queue"]
