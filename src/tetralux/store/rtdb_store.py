"""Firebase Realtime Database online store (Phase 8).

WHAT THIS FILE CONTRIBUTES
--------------------------
Optional cloud logging. Every record can be uploaded to Firebase as well as
written locally, so a session can be watched or reviewed from another machine.

Three classes and a factory, and the shape is worth understanding before the
details:

    make_online_store  decides whether Firebase is available at all, and returns
                       None rather than failing when it is not
    FakeStore          an in-memory stand-in with the same methods, used by tests
    RTDBStore          the real thing

THE COMMON INTERFACE IS THE DESIGN. FakeStore and RTDBStore both provide put,
list_sessions and read_session, so nothing that uses a store needs to know which
one it holds. Recorder just calls .put. That is what lets the whole storage path
be tested without credentials, without a network, and without firebase_admin
installed. Python does not require these to share a base class; matching method
names is enough.

CREDENTIALS ARE NEVER IN THIS FILE, and must never be. They come from two
environment variables set outside the code:

    GOOGLE_APPLICATION_CREDENTIALS   path to a service-account JSON file
    FIREBASE_DATABASE_URL            the database address

The service-account file grants full write access to the database. .gitignore
excludes it along with .env, so it cannot be committed. Never paste its contents
into a source file, a commit, or a message.

FAILURE IS ALWAYS OPTIONAL HERE. Missing variables, bad credentials, no network:
every one of them results in None or a caught exception and local logging
continues untouched (see store/recorder.py).

WHERE IT SITS IN THE FLOW
    store/recorder.py    calls .put on whatever store it was given
    groundstation.py     calls make_online_store() at startup
    store/session.py     tracks the byte counts .put returns

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import json
# os: access to the operating system, used here only to read environment
# variables.
import os
from typing import Optional


# Internal helper (primer 12).
#
# PARAMETER
#   record_dict - one record.
# RETURNS
#   its size in bytes as JSON.
#
# Measured by actually serializing and encoding rather than estimated, so the
# figure reflects what is really sent. It matters because Firebase bills by data
# transferred, and the session summary shows this so a long run does not quietly
# consume a quota.
def _size(record_dict: dict) -> int:
    return len(json.dumps(record_dict).encode("utf-8"))


# --- Decide whether cloud logging is possible ---
#
# PARAMETERS: none.
# RETURNS
#   an RTDBStore if everything is configured and working, otherwise None.
#
# A FACTORY FUNCTION that never raises. Callers pass the result straight to
# Recorder, which treats None as "local only", so no caller needs a try/except
# or a configuration check of its own.
def make_online_store():
    """Return an :class:`RTDBStore` if Firebase env vars are set, else ``None``."""
    # os.environ.get reads an environment variable, returning None if it is not
    # set. BOTH are required: a URL with no credentials cannot authenticate, and
    # credentials with no URL have nowhere to write.
    #
    # Checking first means the common case, running without Firebase configured,
    # produces no error and no noise at all.
    if not (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            and os.environ.get("FIREBASE_DATABASE_URL")):
        return None
    try:
        store = RTDBStore()
        # Printed so the operator knows uploading is happening. Silence about
        # something that sends data off the machine would be the wrong default.
        print("[tetralux] Firebase RTDB online logging enabled.")
        return store
    except Exception as exc:  # missing extra, bad creds, etc.
        # A broad except, justified as in recorder.py: the firebase extra may
        # not be installed, the credential file may be missing or malformed, the
        # project may not exist. All of them mean "no cloud logging today", and
        # none of them should stop a test session from running.
        #
        # The reason is printed rather than swallowed, so a misconfiguration is
        # visible instead of mysteriously silent.
        print(f"[tetralux] Firebase disabled ({exc}); logging locally only.")
        return None


class FakeStore:
    """In-memory OnlineStore for tests / credential-free runs."""

    # Same three methods as RTDBStore, so anything that works with one works
    # with the other. This is what lets test_store.py exercise the complete
    # recording path, including the byte accounting, with no network and no
    # credentials.
    def __init__(self) -> None:
        # A dict of dicts: session id -> key -> record. Mirrors the structure
        # RTDBStore creates in Firebase, so the fake is a fair stand-in rather
        # than a simplification that hides shape bugs.
        self.data: dict = {}
        self.bytes_written = 0

    # PARAMETERS
    #   session_id  - which session this record belongs to.
    #   key         - the sortable timestamp_seq key built by Recorder.
    #   record_dict - the record itself.
    # RETURNS
    #   how many bytes it would have sent.
    def put(self, session_id: str, key: str, record_dict: dict) -> int:
        # .setdefault returns the existing value for a key, or inserts the
        # default and returns that. So this creates the session's dict on first
        # use and reuses it afterwards, in one expression.
        self.data.setdefault(session_id, {})[key] = record_dict
        n = _size(record_dict)
        self.bytes_written += n
        return n

    def list_sessions(self) -> list:
        return list(self.data.keys())

    def read_session(self, session_id: str) -> list:
        # .get with a default of {} so an unknown session returns an empty list
        # rather than raising.
        return list(self.data.get(session_id, {}).values())


class RTDBStore:
    """Firebase Realtime Database OnlineStore (needs the ``firebase`` extra)."""

    # PARAMETERS
    #   database_url    - the database address, or None to read the environment.
    #   credential_path - path to the service-account file, or None likewise.
    #   root            - the top-level node to write under. Namespacing under
    #                     "sessions" leaves the rest of the database free for
    #                     other uses.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, database_url: Optional[str] = None,
                 credential_path: Optional[str] = None, root: str = "sessions") -> None:
        # Lazy imports: firebase_admin is an optional dependency and pulls in a
        # large tree of packages. Importing at the top of the file would make
        # every part of the project depend on it.
        import firebase_admin  # lazy import (optional dep)
        from firebase_admin import credentials

        self.root = root
        # Explicit arguments win over the environment, which suits tests and
        # unusual setups, while the environment remains the normal path.
        database_url = database_url or os.environ.get("FIREBASE_DATABASE_URL")
        credential_path = credential_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        # Raise with a message naming the variable to set. This runs inside
        # make_online_store's try, so it becomes a printed explanation rather
        # than a crash.
        if not database_url:
            raise ValueError("databaseURL required (set FIREBASE_DATABASE_URL)")
        if not credential_path:
            raise ValueError("credential path required (set GOOGLE_APPLICATION_CREDENTIALS)")

        # Initialize a dedicated app once (idempotent across instances).
        #
        # firebase_admin keeps a global registry of initialized apps, and
        # initializing the same name twice raises. So this checks the registry
        # first and reuses the existing app if present.
        #
        # A NAMED app, "tetralux", rather than the default: if this code ever
        # runs alongside anything else using firebase_admin, the two do not
        # collide over the unnamed default app.
        if "tetralux" in firebase_admin._apps:
            self._app = firebase_admin.get_app("tetralux")
        else:
            # Reads the service-account file. THIS is where the credentials
            # enter the process, from a file path supplied by the environment.
            # The secret itself never appears in this repository.
            cred = credentials.Certificate(credential_path)
            self._app = firebase_admin.initialize_app(
                cred, {"databaseURL": database_url}, name="tetralux"
            )
        self.bytes_written = 0

    # Upload one record. Same signature as FakeStore.put, which is the point.
    def put(self, session_id: str, key: str, record_dict: dict) -> int:
        from firebase_admin import db

        # A Realtime Database is one large JSON tree, and a path addresses a
        # node in it, much like a file path. This creates
        # sessions/<id>/packets/<key>, so every packet is its own node. That is
        # what "per-packet logging" means: nothing is batched or summarised.
        ref = db.reference(f"{self.root}/{session_id}/packets/{key}", app=self._app)
        # .set writes the record at that node, replacing anything there. Safe
        # because the key includes both timestamp and sequence number, so two
        # different packets cannot collide.
        ref.set(record_dict)
        n = _size(record_dict)
        self.bytes_written += n
        return n

    def list_sessions(self) -> list:
        from firebase_admin import db

        ref = db.reference(f"{self.root}", app=self._app)
        # shallow=True fetches only the KEY NAMES, not the data beneath them.
        # Essential here: without it, listing sessions would download every
        # packet of every session, potentially hundreds of megabytes, to answer
        # a question about names.
        #
        # `or {}` handles an empty database, where .get returns None.
        data = ref.get(shallow=True) or {}
        return list(data.keys())

    def read_session(self, session_id: str) -> list:
        from firebase_admin import db

        ref = db.reference(f"{self.root}/{session_id}/packets", app=self._app)
        data = ref.get() or {}
        # sorted(data) sorts the keys. Because Recorder built them as
        # "timestamp_seq", sorting the text puts the packets back in
        # chronological order, which is exactly why that key format was chosen.
        return [data[k] for k in sorted(data)]
