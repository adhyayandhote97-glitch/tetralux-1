"""History queries over stored sessions (Phase 8).

WHAT THIS FILE CONTRIBUTES
--------------------------
Reading sessions back after they were recorded. local_log.py writes one session;
this file surveys all of them and answers the questions the History page asks:

    What sessions exist, how big are they, how long did they run?
    Give me the records between these two times.
    Export that to CSV so I can open it in a spreadsheet.

WHY A SEPARATE FILE FROM local_log.py. Writing and reading have opposite
priorities. Writing must be fast and durable, because it happens ten times a
second while data is arriving. Reading happens when a person clicks something,
so it can be slower but must cope with whatever is on disk: a session
interrupted mid-write, a metadata file that never got its stop time, a directory
someone half-deleted.

THAT ROBUSTNESS IS THE THEME HERE. Every function degrades rather than raising.
A missing metadata file gives an empty dict, an unreadable one gives an empty
dict, a directory with no records is skipped. The History page must render even
when some sessions are damaged, because a corrupt session is exactly when
someone needs to look at the list.

WHERE IT SITS IN THE FLOW
    store/local_log.py   supplies the reading and CSV machinery
    store/session.py     writes the session.json files read here
    dashboard/app.py     renders the History page from these results

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tetralux.store.local_log import LocalLog, export_csv

# Repeated from session.py and local_log.py rather than imported, keeping this
# module readable on its own. Small duplication, and these names are effectively
# frozen by the on-disk layout.
META_FILE = "session.json"
RECORDS_FILE = "records.jsonl"


@dataclass
class SessionSummary:
    """One row in the History session list."""

    session_id: str
    started_at: Optional[str]
    stopped_at: Optional[str]
    packet_count: int
    size_bytes: int          # local records file size
    rtdb_bytes_est: int
    first_ts_ms: Optional[int]
    last_ts_ms: Optional[int]
    #
    # MOST FIELDS ARE Optional BECAUSE THE DATA MAY BE INCOMPLETE. A session
    # killed mid-run has no stopped_at; one whose metadata file was lost has no
    # started_at; one with no records has no timestamps. None reports each gap
    # honestly rather than inventing a zero that would look like a real value.
    #
    # first_ts_ms and last_ts_ms come from the records themselves, while
    # started_at and stopped_at come from the metadata. They measure different
    # clocks: device time since boot versus ground-station wall clock. Both are
    # kept because a large disagreement between them is itself diagnostic.

    # RETURNS
    #   the file size as readable text, e.g. "1.4 MiB".
    #
    # Sizes are shown to a person, and "1503238 bytes" is genuinely hard to
    # judge at a glance while "1.4 MiB" is not.
    #
    # THE LOOP IS THE STANDARD TRICK: divide by 1024 repeatedly until the number
    # is small, stepping up a unit each time. KiB, MiB and GiB are the binary
    # units, powers of 1024 rather than 1000, which is what file sizes actually
    # use.
    def size_human(self) -> str:
        b = float(self.size_bytes)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if b < 1024.0:
                return f"{b:.1f} {unit}"
            b /= 1024.0
        # Only reached for something over a terabyte. Present for completeness.
        return f"{b:.1f} TiB"


# --- Survey every session on disk ---
#
# PARAMETER
#   base_dir - where sessions live.
# RETURNS
#   a list of SessionSummary, newest first.
def list_sessions(base_dir: str = "data/logs") -> list:
    """List all sessions with size/duration/packet-count, newest first."""
    root = Path(base_dir)
    # No directory at all means no sessions have been recorded yet, which is the
    # normal state on a fresh checkout, not an error.
    if not root.exists():
        return []

    summaries = []
    # .iterdir lists the directory's contents; sorted() gives a predictable
    # order to work through.
    for session_dir in sorted(root.iterdir()):
        records_path = session_dir / RECORDS_FILE
        # THE DEFINITION OF A REAL SESSION: it has a records file. This skips
        # stray files, half-deleted directories, and sessions that were started
        # but never received a packet.
        if not records_path.exists():
            continue
        meta = _read_meta(session_dir / META_FILE)
        records = LocalLog(session_dir.name, base_dir).read()
        # Collect timestamps, skipping any record missing one.
        ts = [r.get("timestamp_ms") for r in records if r.get("timestamp_ms") is not None]
        summaries.append(SessionSummary(
            # The directory name IS the session id, so this is correct even when
            # the metadata file is missing entirely.
            session_id=session_dir.name,
            started_at=meta.get("started_at"),
            stopped_at=meta.get("stopped_at"),
            # Prefer the metadata's count, but fall back to counting the records
            # actually present. Those differ when a session was interrupted
            # before its final metadata write, and the fallback keeps the row
            # useful rather than blank.
            packet_count=meta.get("packet_count", len(records)),
            # .stat().st_size asks the filesystem for the real size on disk,
            # rather than trusting anything recorded earlier.
            size_bytes=records_path.stat().st_size,
            rtdb_bytes_est=meta.get("rtdb_bytes_est", 0),
            # `if ts else None`: min and max raise on an empty list.
            first_ts_ms=min(ts) if ts else None,
            last_ts_ms=max(ts) if ts else None,
        ))
    # NEWEST FIRST. Session ids start with the date in YYYYMMDD form, so sorting
    # the text alphabetically sorts chronologically, and reverse=True puts the
    # most recent at the top, which is nearly always the one being looked for.
    # That is the payoff of the id format chosen in session.py.
    summaries.sort(key=lambda s: s.session_id, reverse=True)
    return summaries


# --- Fetch records from one session ---
#
# PARAMETERS
#   session_id - which session.
#   start_ms   - device-time lower bound, or None.
#   end_ms     - device-time upper bound, or None.
#   base_dir   - where sessions live.
# RETURNS
#   the matching records.
#
# A thin pass-through to LocalLog.time_range. Worth having anyway: the dashboard
# imports only `query` and asks it for history, without needing to know how
# sessions are stored. If the storage changed, this signature would not.
def read_range(session_id: str, start_ms: Optional[int] = None,
               end_ms: Optional[int] = None, base_dir: str = "data/logs") -> list:
    """Records for a session, optionally filtered to a device-time range."""
    return LocalLog(session_id, base_dir).time_range(start_ms, end_ms)


# --- Export to a spreadsheet ---
#
# PARAMETERS
#   session_id - which session.
#   out_path   - where to write the CSV.
#   start_ms   - optional lower time bound.
#   end_ms     - optional upper time bound.
#   base_dir   - where sessions live.
# RETURNS
#   how many rows were written.
#
# Composed from the two functions above: read_range selects, export_csv writes.
# The time bounds carry through, so a user can export just the interesting
# thirty seconds of an hour-long session rather than the whole thing.
def export_session_csv(session_id: str, out_path: str, start_ms: Optional[int] = None,
                       end_ms: Optional[int] = None, base_dir: str = "data/logs") -> int:
    """Export a session (optionally a time range) to CSV. Returns rows written."""
    return export_csv(read_range(session_id, start_ms, end_ms, base_dir), out_path)


# Internal helper (primer 12).
#
# PARAMETER
#   path - the session.json to read.
# RETURNS
#   its contents as a dict, or an empty dict if it cannot be read.
#
# NEVER RAISES, which is what makes list_sessions robust. Returning {} means
# every .get() call above falls back to its default, so one damaged session
# leaves a partially filled row rather than breaking the entire History page.
def _read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Two specific failures, both real. JSONDecodeError: the file was truncated
    # mid-write when the process was killed. OSError: a permissions problem or a
    # vanished disk. Named rather than a bare except, so a genuine bug in this
    # function still surfaces.
    except (json.JSONDecodeError, OSError):
        return {}
