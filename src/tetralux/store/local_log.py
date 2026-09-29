"""Local full-fidelity log (Phase 8).

WHAT THIS FILE CONTRIBUTES
--------------------------
Every processed record is written to disk here, one per line, forever. "Full
fidelity" means nothing is summarised, averaged or thinned: what the pipeline
computed is what lands in the file.

That matters because a test session cannot be repeated. The lamp was at that
angle, the room was that temperature, the hardware was in that state. If the
data was thinned to save space, the detail needed to explain an anomaly six
weeks later is gone and cannot be recovered.

THE FORMAT IS JSONL: JSON Lines. One complete JSON object per line, newline
separated, no enclosing brackets.

    {"seq": 1, "timestamp_ms": 100, ...}
    {"seq": 2, "timestamp_ms": 200, ...}

WHY NOT ONE BIG JSON ARRAY. A JSON array must be closed with `]` to be valid, so
a session interrupted by Ctrl-C or a power cut would produce a file no parser
would read, losing everything. JSONL has no closing anything: each line stands
alone, appending is just writing to the end, and a file truncated mid-write
loses one line rather than the session. For an append-only log written
continuously, those properties matter more than tidiness.

This file also handles CSV export, for opening a session in a spreadsheet. That
needs flattening, because a record is nested and CSV is flat, which `_flatten`
below handles.

WHERE IT SITS IN THE FLOW
    record.py           supplies the JSON-safe dicts written here
    store/recorder.py   calls append() for every record
    store/query.py      reads these files back for the History page

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# csv: the standard library's CSV writer, which handles quoting and escaping.
import csv
import json
from pathlib import Path
# Iterable is a type hint for "anything you can loop over".
from typing import Iterable, Optional

RECORDS_FILE = "records.jsonl"


class LocalLog:
    """Append-only JSONL log for one session."""

    # PARAMETERS
    #   session_id - names this session, e.g. "S20260905_143000". Becomes the
    #                directory name.
    #   base_dir   - where sessions live, "data/logs" by default.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, session_id: str, base_dir: str = "data/logs") -> None:
        self.session_id = session_id
        # The `/` operator joins path components on a Path object, and picks the
        # right separator for the operating system automatically.
        self.dir = Path(base_dir) / session_id
        # parents=True creates any missing parent directories too, so a fresh
        # checkout with no data/ folder works. exist_ok=True means an existing
        # directory is fine rather than an error, which matters when resuming.
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / RECORDS_FILE

    # PARAMETER
    #   record_dict - one record, already JSON-safe via to_dict().
    # RETURNS
    #   how many bytes were written. The session controller sums these to show
    #   the operator how large the session is getting.
    def append(self, record_dict: dict) -> int:
        """Append one record; return the number of bytes written."""
        # No indent, deliberately: the whole record must be on ONE line, which
        # is what makes the file JSONL. Pretty-printing would break the format
        # entirely. The explicit "\n" is the line terminator.
        line = json.dumps(record_dict) + "\n"
        data = line.encode("utf-8")
        # "ab" is APPEND BINARY. Append, so each write goes to the end and
        # nothing is overwritten. Binary, so the byte count returned is the
        # exact number of bytes on disk; in text mode the operating system might
        # translate line endings and the count would be wrong.
        #
        # `with` opens the file and guarantees it is closed afterwards, even if
        # an error occurs partway. Reopening per record rather than holding the
        # file open costs a little speed and buys durability: each record is
        # flushed to disk immediately, so a crash loses nothing already written.
        with open(self.path, "ab") as f:
            f.write(data)
        return len(data)

    # RETURNS
    #   every record in this session as a list of dicts, or an empty list if
    #   the session has no file yet.
    def read(self) -> list:
        """Read all records for the session (empty list if none)."""
        # A session that was started but never received a packet has no file.
        # That is normal, not an error, so it returns empty rather than raising.
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            # Parse each line independently, which is the JSONL payoff.
            # `if line.strip()` skips blank lines, so a stray newline at the end
            # of the file cannot break the whole read.
            return [json.loads(line) for line in f if line.strip()]

    # PARAMETERS
    #   start_ms - keep records at or after this device timestamp, or None for
    #              no lower bound.
    #   end_ms   - keep records at or before this, or None for no upper bound.
    # RETURNS
    #   the matching records.
    #
    # Both bounds are INCLUSIVE, and both default to None so either can be
    # given alone: "everything after t" and "everything before t" are both
    # common questions on the History page.
    def time_range(self, start_ms: Optional[int] = None,
                   end_ms: Optional[int] = None) -> list:
        """Records whose ``timestamp_ms`` falls within [start_ms, end_ms]."""
        out = []
        # Reads the whole file, then filters. Fine at this scale: an hour at
        # 10 Hz is 36,000 records, which modern machines handle instantly.
        for rec in self.read():
            ts = rec.get("timestamp_ms")
            # `continue` skips records outside the window. Two separate checks
            # rather than one combined condition, so each bound can be absent
            # independently.
            if start_ms is not None and ts < start_ms:
                continue
            if end_ms is not None and ts > end_ms:
                continue
            out.append(rec)
        return out


# --- Flattening for CSV ---
#
# PARAMETERS
#   record - a nested record dict.
#   prefix - the accumulated column-name prefix, used by the recursion. Callers
#            leave it empty; the function supplies it to itself.
# RETURNS
#   a flat dict where every value is a single scalar.
#
# THE PROBLEM. A record is nested: `weights` is itself a dict of six faces. CSV
# has no nesting at all, only flat columns.
#
# THE SOLUTION. Walk down through the nesting, joining names with underscores,
# so `{"weights": {"+x": 0.5}}` becomes `{"weights_+x": 0.5}`. Every nested
# value gets its own column, and the column name records where it came from.
#
# RECURSIVE, like record._clean: it calls itself to descend one layer at a time,
# and the base case is a value that is neither dict nor list.
def _flatten(record: dict, prefix: str = "") -> dict:
    """Flatten a nested record into scalar columns for CSV export."""
    flat = {}
    for key, value in record.items():
        col = f"{prefix}{key}"
        # A nested dict: recurse, extending the prefix with this key. This is
        # what builds names like "thermal_drift_rates_T1".
        if isinstance(value, dict):
            # .update merges the returned dict into this one.
            flat.update(_flatten(value, prefix=f"{col}_"))
        # A list, such as sun_vector's three components. Stored as JSON text in
        # ONE cell rather than split into three columns, because lists here vary
        # in length between records and columns must be consistent across every
        # row of a CSV. "[0.81, 0.47, 0.34]" in a single cell is readable and
        # keeps the file valid.
        elif isinstance(value, (list, tuple)):
            flat[col] = json.dumps(value)
        # The base case: a plain number, string, bool or None goes straight in.
        else:
            flat[col] = value
    return flat


# --- Writing a CSV ---
#
# PARAMETERS
#   records  - the records to write, any iterable of dicts.
#   out_path - where to write the file.
# RETURNS
#   how many rows were written.
def export_csv(records: Iterable[dict], out_path: str) -> int:
    """Write records to a flat CSV. Returns the number of rows written."""
    rows = [_flatten(r) for r in records]

    # COLUMN COLLECTION, and the ordering is the point. Different records can
    # have different keys: one frame has thermal data and another does not. A
    # CSV needs one fixed header covering every column any row uses.
    #
    # This walks every row collecting keys in FIRST-SEEN order, using a set to
    # skip duplicates. A set alone would be simpler but sets have no order, so
    # the columns would shuffle between exports and the files would be
    # frustrating to compare. The list preserves the record's own field order,
    # so a spreadsheet reads seq, timestamp, photodiodes, and so on, in the
    # order the pipeline computes them.
    columns: list = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is REQUIRED by the csv module. Without it, Windows writes an
    # extra carriage return per row and every other line comes out blank.
    with open(out, "w", newline="", encoding="utf-8") as f:
        # DictWriter maps dict keys to columns, and crucially fills in an empty
        # cell for any column a given row lacks, which is what makes rows with
        # different keys line up under one header.
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
