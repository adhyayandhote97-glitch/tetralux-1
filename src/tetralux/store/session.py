"""Manual session control (Phase 8, Decision 8).

Logging is **off until `start()`** — never on app launch. While a session is
active, `record()` fans out to the local JSONL log and (if configured) Firebase
RTDB, tracking packet count, duration, and accumulated bytes (local + estimated
RTDB). `stop()` finalizes and prints a summary. No automatic pruning, retention,
or throttling — visibility only, so old sessions can be deleted manually.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tetralux.record import GroundStationRecord
from tetralux.store.local_log import LocalLog
from tetralux.store.recorder import Recorder

META_FILE = "session.json"


@dataclass
class SessionInfo:
    """Live/finalized stats for one recording session."""

    session_id: str
    started_at: str               # ISO-8601
    stopped_at: Optional[str]     # ISO-8601 or None while active
    packet_count: int
    local_bytes: int
    rtdb_bytes_est: int
    active: bool

    def duration_s(self) -> float:
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.stopped_at) if self.stopped_at else datetime.now(timezone.utc)
        return (end - start).total_seconds()


class SessionController:
    """Start/stop gate around recording, with size/duration visibility."""

    def __init__(self, base_dir: str = "data/logs", online_store=None) -> None:
        self.base_dir = base_dir
        self.online_store = online_store
        self._recorder: Optional[Recorder] = None
        self._info: Optional[SessionInfo] = None

    @property
    def active(self) -> bool:
        return self._info is not None and self._info.active

    @property
    def info(self) -> Optional[SessionInfo]:
        return self._info

    def start(self, session_id: Optional[str] = None) -> SessionInfo:
        """Begin a session; recording is inactive until this is called."""
        session_id = session_id or datetime.now().strftime("S%Y%m%d_%H%M%S")
        local = LocalLog(session_id, self.base_dir)
        self._recorder = Recorder(local, self.online_store)
        self._info = SessionInfo(
            session_id=session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            stopped_at=None, packet_count=0, local_bytes=0, rtdb_bytes_est=0,
            active=True,
        )
        self._write_meta()
        return self._info

    def record(self, record: GroundStationRecord) -> None:
        """Persist one record — a no-op when no session is active."""
        if not self.active or self._recorder is None:
            return
        local_bytes, online_bytes = self._recorder.record(record.to_dict())
        self._info.packet_count += 1
        self._info.local_bytes += local_bytes
        self._info.rtdb_bytes_est += online_bytes

    def stop(self) -> Optional[SessionInfo]:
        """End the session, persist metadata, and print a summary."""
        if self._info is None or not self._info.active:
            return self._info
        self._info.active = False
        self._info.stopped_at = datetime.now(timezone.utc).isoformat()
        self._write_meta()
        info = self._info
        print(
            f"[tetralux] session {info.session_id} stopped: "
            f"{info.packet_count} packets, {info.duration_s():.1f} s, "
            f"local {info.local_bytes / 1024:.1f} KiB, "
            f"rtdb ~{info.rtdb_bytes_est / 1024:.1f} KiB"
        )
        return info

    def _write_meta(self) -> None:
        if self._info is None:
            return
        path = Path(self.base_dir) / self._info.session_id / META_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self._info), f, indent=2)
