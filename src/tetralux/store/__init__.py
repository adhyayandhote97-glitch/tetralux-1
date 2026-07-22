"""Phase 8: logging store — local JSONL mirror + Firebase RTDB, with manual
session control and history queries.

``RTDBStore`` needs the ``firebase`` extra and is imported lazily by its own
module; the pure pieces (local log, session control, query, FakeStore) are
re-exported here.
"""

from tetralux.store.local_log import LocalLog, export_csv
from tetralux.store.query import (
    SessionSummary,
    export_session_csv,
    list_sessions,
    read_range,
)
from tetralux.store.recorder import Recorder
from tetralux.store.rtdb_store import FakeStore, make_online_store
from tetralux.store.session import SessionController, SessionInfo

__all__ = [
    "LocalLog",
    "export_csv",
    "Recorder",
    "FakeStore",
    "make_online_store",
    "SessionController",
    "SessionInfo",
    "SessionSummary",
    "list_sessions",
    "read_range",
    "export_session_csv",
]
