"""Record fan-out (Phase 8)."""

from __future__ import annotations


from tetralux.store.local_log import LocalLog


class Recorder:
    """Fan-out writer: local JSONL (always) + online store (optional)."""

    def __init__(self, local_log: LocalLog, online_store=None) -> None:
        self.local = local_log
        self.online = online_store

    def record(self, record_dict: dict) -> "tuple[int, int]":
        """Persist one record. Returns ``(local_bytes, online_bytes)``."""
        local_bytes = self.local.append(record_dict)
        online_bytes = 0
        if self.online is not None:
            key = f"{record_dict.get('timestamp_ms', 0)}_{record_dict.get('seq', 0)}"
            try:
                online_bytes = self.online.put(self.local.session_id, key, record_dict)
            except Exception:  # never let an upload failure break local logging
                online_bytes = 0
        return local_bytes, online_bytes
