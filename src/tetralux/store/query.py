"""History queries over stored sessions (Phase 8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tetralux.store.local_log import LocalLog, export_csv

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

    def size_human(self) -> str:
        b = float(self.size_bytes)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if b < 1024.0:
                return f"{b:.1f} {unit}"
            b /= 1024.0
        return f"{b:.1f} TiB"


def list_sessions(base_dir: str = "data/logs") -> list:
    """List all sessions with size/duration/packet-count, newest first."""
    root = Path(base_dir)
    if not root.exists():
        return []

    summaries = []
    for session_dir in sorted(root.iterdir()):
        records_path = session_dir / RECORDS_FILE
        if not records_path.exists():
            continue
        meta = _read_meta(session_dir / META_FILE)
        records = LocalLog(session_dir.name, base_dir).read()
        ts = [r.get("timestamp_ms") for r in records if r.get("timestamp_ms") is not None]
        summaries.append(SessionSummary(
            session_id=session_dir.name,
            started_at=meta.get("started_at"),
            stopped_at=meta.get("stopped_at"),
            packet_count=meta.get("packet_count", len(records)),
            size_bytes=records_path.stat().st_size,
            rtdb_bytes_est=meta.get("rtdb_bytes_est", 0),
            first_ts_ms=min(ts) if ts else None,
            last_ts_ms=max(ts) if ts else None,
        ))
    summaries.sort(key=lambda s: s.session_id, reverse=True)
    return summaries


def read_range(session_id: str, start_ms: Optional[int] = None,
               end_ms: Optional[int] = None, base_dir: str = "data/logs") -> list:
    """Records for a session, optionally filtered to a device-time range."""
    return LocalLog(session_id, base_dir).time_range(start_ms, end_ms)


def export_session_csv(session_id: str, out_path: str, start_ms: Optional[int] = None,
                       end_ms: Optional[int] = None, base_dir: str = "data/logs") -> int:
    """Export a session (optionally a time range) to CSV. Returns rows written."""
    return export_csv(read_range(session_id, start_ms, end_ms, base_dir), out_path)


def _read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
