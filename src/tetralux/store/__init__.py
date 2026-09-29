"""Phase 8: logging store - local JSONL mirror + Firebase RTDB, with manual session control and history queries.

WHAT THIS FILE CONTRIBUTES
--------------------------
Marks `store/` as a package and re-exports its whole public surface. This is the
largest set of re-exports in the project, because the dashboard, the ground
station and the tests all reach into different parts of it.

This subpackage persists what the pipeline produces:

    local_log.py   append-only JSONL on disk, one record per line, plus CSV export
    rtdb_store.py  optional Firebase upload, and a fake stand-in for tests
    recorder.py    fan-out: local always, cloud optional and never able to break it
    session.py     the manual start/stop gate around all recording
    query.py       reading sessions back for the History page

THE ORGANISING RULE: the local file is the record of the experiment and Firebase
is a convenience. Every failure mode is arranged so the worst outcome is "the
cloud copy is missing", never "the measurement is gone".

Recording is OFF until someone starts a session, deliberately. There is no
automatic pruning, retention limit or throttling; data is deleted only when a
person decides to delete it.

New to Python? Read docs/python-primer.md first, and see tetralux/__init__.py
for what an __init__.py is.
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

# Grouped by role rather than alphabetically: writing, then the destinations,
# then session control, then reading back.
__all__ = [
    # writing
    "LocalLog",
    "export_csv",
    "Recorder",
    # online destinations
    "FakeStore",           # in-memory stand-in, same methods as RTDBStore
    "make_online_store",   # returns None when Firebase is not configured
    # session control
    "SessionController",
    "SessionInfo",
    # reading back
    "SessionSummary",
    "list_sessions",
    "read_range",
    "export_session_csv",
]
