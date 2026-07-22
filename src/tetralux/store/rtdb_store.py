"""Firebase Realtime Database online store (Phase 8).

Writes **one node per packet** at ``sessions/{sid}/packets/{key}`` — no per-write
op billing (RTDB is priced on storage/bandwidth), so it sustains the 100 Hz
target. Credentials come from the environment
(``GOOGLE_APPLICATION_CREDENTIALS``) plus a ``databaseURL``; they are never
handled in code or committed.

`FakeStore` is an in-memory stand-in used by tests and by the dashboard when no
Firebase credentials are configured.
"""

from __future__ import annotations

import json
import os
from typing import Optional


def _size(record_dict: dict) -> int:
    return len(json.dumps(record_dict).encode("utf-8"))


def make_online_store():
    """Return an :class:`RTDBStore` if Firebase env vars are set, else ``None``.

    Requires both ``GOOGLE_APPLICATION_CREDENTIALS`` and ``FIREBASE_DATABASE_URL``.
    Lets the dashboard/CLI enable online logging with no code change — and stay
    local-only (still full fidelity) when unconfigured.
    """
    if not (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            and os.environ.get("FIREBASE_DATABASE_URL")):
        return None
    try:
        store = RTDBStore()
        print("[tetralux] Firebase RTDB online logging enabled.")
        return store
    except Exception as exc:  # missing extra, bad creds, etc.
        print(f"[tetralux] Firebase disabled ({exc}); logging locally only.")
        return None


class FakeStore:
    """In-memory OnlineStore for tests / credential-free runs."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.bytes_written = 0

    def put(self, session_id: str, key: str, record_dict: dict) -> int:
        self.data.setdefault(session_id, {})[key] = record_dict
        n = _size(record_dict)
        self.bytes_written += n
        return n

    def list_sessions(self) -> list:
        return list(self.data.keys())

    def read_session(self, session_id: str) -> list:
        return list(self.data.get(session_id, {}).values())


class RTDBStore:
    """Firebase Realtime Database OnlineStore (needs the ``firebase`` extra)."""

    def __init__(self, database_url: Optional[str] = None,
                 credential_path: Optional[str] = None, root: str = "sessions") -> None:
        import firebase_admin  # lazy import (optional dep)
        from firebase_admin import credentials

        self.root = root
        database_url = database_url or os.environ.get("FIREBASE_DATABASE_URL")
        credential_path = credential_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not database_url:
            raise ValueError("databaseURL required (set FIREBASE_DATABASE_URL)")
        if not credential_path:
            raise ValueError("credential path required (set GOOGLE_APPLICATION_CREDENTIALS)")

        # Initialize a dedicated app once (idempotent across instances).
        if "tetralux" in firebase_admin._apps:
            self._app = firebase_admin.get_app("tetralux")
        else:
            cred = credentials.Certificate(credential_path)
            self._app = firebase_admin.initialize_app(
                cred, {"databaseURL": database_url}, name="tetralux"
            )
        self.bytes_written = 0

    def put(self, session_id: str, key: str, record_dict: dict) -> int:
        from firebase_admin import db

        ref = db.reference(f"{self.root}/{session_id}/packets/{key}", app=self._app)
        ref.set(record_dict)
        n = _size(record_dict)
        self.bytes_written += n
        return n

    def list_sessions(self) -> list:
        from firebase_admin import db

        ref = db.reference(f"{self.root}", app=self._app)
        data = ref.get(shallow=True) or {}
        return list(data.keys())

    def read_session(self, session_id: str) -> list:
        from firebase_admin import db

        ref = db.reference(f"{self.root}/{session_id}/packets", app=self._app)
        data = ref.get() or {}
        return [data[k] for k in sorted(data)]
