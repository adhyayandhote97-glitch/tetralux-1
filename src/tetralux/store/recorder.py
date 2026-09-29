"""Record fan-out (Phase 8).

WHAT THIS FILE CONTRIBUTES
--------------------------
One record needs to go to two places: the local disk file and, when configured,
Firebase. "Fan-out" is the name for that pattern, one input sent to several
destinations, and this small class is the single point where it happens.

THE ORDERING IS THE WHOLE DESIGN. Local first, always, and unconditionally.
Firebase second, optional, and wrapped so that its failure cannot affect the
local write that already succeeded.

That priority is deliberate. The local file is the record of the experiment;
Firebase is a convenience for viewing it elsewhere. WiFi drops, credentials
expire, quotas run out, and none of those are reasons to lose data from a
session that cannot be repeated. Every failure mode here has been arranged so
the worst outcome is "the cloud copy is missing", never "the measurement is
gone".

It is a class rather than a function because it holds the two destinations
between calls, so the caller configures them once at session start and then
records thousands of times without repeating itself.

WHERE IT SITS IN THE FLOW
    store/session.py     creates one per session and calls record() per packet
    store/local_log.py   the always-on destination
    store/rtdb_store.py  the optional one

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations


from tetralux.store.local_log import LocalLog


class Recorder:
    """Fan-out writer: local JSONL (always) + online store (optional)."""

    # PARAMETERS
    #   local_log    - REQUIRED. There is no mode in which local logging is off.
    #   online_store - an object with a .put method, or None. Note the type hint
    #                  is deliberately absent: anything providing .put works,
    #                  which is what lets FakeStore stand in during tests
    #                  without Firebase being installed at all.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, local_log: LocalLog, online_store=None) -> None:
        self.local = local_log
        self.online = online_store

    # PARAMETER
    #   record_dict - one JSON-safe record from GroundStationRecord.to_dict.
    # RETURNS
    #   a tuple (local_bytes, online_bytes). The session controller adds these
    #   up so the operator can watch both the disk usage and the Firebase usage
    #   grow, the latter mattering because cloud storage is metered.
    def record(self, record_dict: dict) -> "tuple[int, int]":
        """Persist one record. Returns ``(local_bytes, online_bytes)``."""
        # LOCAL FIRST, outside any try. If this fails, the exception propagates
        # and the caller finds out, because a failure to write the primary
        # record is a genuine problem that must not be swallowed.
        local_bytes = self.local.append(record_dict)
        online_bytes = 0
        if self.online is not None:
            # A key that is both unique and SORTABLE. Firebase stores children
            # under string keys in lexicographic order, so leading with the
            # timestamp means the records come back in chronological order for
            # free. The sequence number breaks ties between two packets sharing
            # a millisecond.
            key = f"{record_dict.get('timestamp_ms', 0)}_{record_dict.get('seq', 0)}"
            try:
                online_bytes = self.online.put(self.local.session_id, key, record_dict)
            except Exception:  # never let an upload failure break local logging
                # A BROAD except, and one of the few genuinely justified ones in
                # this project. A network call can fail in a great many ways:
                # timeout, DNS failure, expired credentials, quota exceeded,
                # library-specific errors. Every one of them means the same
                # thing here, and none of them is a reason to lose the session.
                #
                # The local write on the line above already succeeded, so the
                # data is safe. Reporting 0 bytes online is honest: nothing was
                # uploaded.
                online_bytes = 0
        return local_bytes, online_bytes
