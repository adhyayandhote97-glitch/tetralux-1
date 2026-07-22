"""Local full-fidelity log (Phase 8).

Every processed record is appended as one JSON line to
``<base_dir>/<session_id>/records.jsonl``. This is the always-on source of
truth (independent of Firebase) and backs the History page's browse / time-range
/ CSV-export features.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Optional

RECORDS_FILE = "records.jsonl"


class LocalLog:
    """Append-only JSONL log for one session."""

    def __init__(self, session_id: str, base_dir: str = "data/logs") -> None:
        self.session_id = session_id
        self.dir = Path(base_dir) / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / RECORDS_FILE

    def append(self, record_dict: dict) -> int:
        """Append one record; return the number of bytes written."""
        line = json.dumps(record_dict) + "\n"
        data = line.encode("utf-8")
        with open(self.path, "ab") as f:
            f.write(data)
        return len(data)

    def read(self) -> list:
        """Read all records for the session (empty list if none)."""
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def time_range(self, start_ms: Optional[int] = None,
                   end_ms: Optional[int] = None) -> list:
        """Records whose ``timestamp_ms`` falls within [start_ms, end_ms]."""
        out = []
        for rec in self.read():
            ts = rec.get("timestamp_ms")
            if start_ms is not None and ts < start_ms:
                continue
            if end_ms is not None and ts > end_ms:
                continue
            out.append(rec)
        return out


def _flatten(record: dict, prefix: str = "") -> dict:
    """Flatten a nested record into scalar columns for CSV export."""
    flat = {}
    for key, value in record.items():
        col = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, prefix=f"{col}_"))
        elif isinstance(value, (list, tuple)):
            flat[col] = json.dumps(value)
        else:
            flat[col] = value
    return flat


def export_csv(records: Iterable[dict], out_path: str) -> int:
    """Write records to a flat CSV. Returns the number of rows written."""
    rows = [_flatten(r) for r in records]
    columns: list = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
