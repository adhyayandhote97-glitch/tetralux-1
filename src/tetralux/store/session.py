"""Manual session control (Phase 8, Decision 8).

WHAT THIS FILE CONTRIBUTES
--------------------------
A gate around recording. Nothing is written to disk or Firebase until someone
explicitly starts a session, and everything stops the moment they stop it.

WHY MANUAL RATHER THAN AUTOMATIC. This prototype is not run continuously; it is
switched on for a test and switched off again. Automatic recording would fill
the disk and the Firebase quota with idle noise from every accidental launch,
and the interesting data would be buried in it. An explicit start also means the
operator decides where the boundary between one experiment and the next falls,
which is a judgement no timer can make.

There is deliberately NO automatic pruning, no retention limit and no rate
throttling. Data is deleted only when a person decides to delete it.

WHAT A SESSION IS ON DISK
    data/logs/S20260905_143000/
        records.jsonl   every record, one per line
        session.json    the metadata SessionInfo below describes

The metadata is written at start and again at stop, so a session interrupted by
a crash still leaves a readable record of what it was, with `active` stuck true
as evidence it never finished cleanly.

THE GATE IS THE POINT. `record()` does nothing at all when no session is active,
so callers such as groundstation.py call it unconditionally for every frame and
never need to check first. One `if` lives here instead of at every call site.

This is one of the three files that use print(), for the stop summary (see
docs/python-primer.md, section 2).

WHERE IT SITS IN THE FLOW
    store/recorder.py    the fan-out this drives
    groundstation.py     starts a session with --record
    dashboard/state.py   starts and stops sessions from the Live page buttons
    store/query.py       reads the session.json files this writes

New to Python? Read docs/python-primer.md first.
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
    #
    # stopped_at is None while running, which is what makes an interrupted
    # session identifiable afterwards: it has a start time, no stop time, and
    # active still true.
    #
    # The two byte counts are tracked separately because they answer different
    # questions. local_bytes is disk space, which is cheap; rtdb_bytes_est is
    # Firebase usage, which is metered and can cost money. Summing them into one
    # figure would hide the one worth watching.

    # RETURNS
    #   how long the session has run, in seconds.
    #
    # Works for both a finished and a running session, which is why the History
    # page can show a live duration that ticks upward.
    def duration_s(self) -> float:
        # fromisoformat parses the ISO-8601 text back into a datetime, the
        # inverse of the .isoformat() used when writing it.
        start = datetime.fromisoformat(self.started_at)
        # If the session is still running there is no stop time, so "now" is
        # used instead.
        end = datetime.fromisoformat(self.stopped_at) if self.stopped_at else datetime.now(timezone.utc)
        # Subtracting two datetimes gives a timedelta; .total_seconds() turns it
        # into a plain number.
        return (end - start).total_seconds()


class SessionController:
    """Start/stop gate around recording, with size/duration visibility."""

    # PARAMETERS
    #   base_dir     - where sessions are written.
    #   online_store - a Firebase store, or None for local only.
    # RETURNS
    #   None; a constructor sets the object up.
    #
    # Both internal fields start as None: a controller exists in a not-recording
    # state until start() is called, which is the gate's default position.
    def __init__(self, base_dir: str = "data/logs", online_store=None) -> None:
        self.base_dir = base_dir
        self.online_store = online_store
        self._recorder: Optional[Recorder] = None
        self._info: Optional[SessionInfo] = None

    # @property makes a method usable as if it were a plain attribute: callers
    # write `ctl.active`, not `ctl.active()`. Right when the value is computed
    # rather than stored, but reads as a simple fact about the object.
    #
    # RETURNS
    #   True only when a session exists AND is running. Both halves are needed:
    #   after stop(), _info still exists so the summary can be read, but active
    #   is False.
    @property
    def active(self) -> bool:
        return self._info is not None and self._info.active

    # Read-only access to the metadata. A property rather than a public
    # attribute so callers can look but the controller alone decides when the
    # counts change.
    @property
    def info(self) -> Optional[SessionInfo]:
        return self._info

    # PARAMETER
    #   session_id - a name for this session, or None to generate one.
    # RETURNS
    #   the new SessionInfo.
    def start(self, session_id: Optional[str] = None) -> SessionInfo:
        """Begin a session; recording is inactive until this is called."""
        # strftime formats a datetime as text: "S20260905_143000" for 14:30:00
        # on 5 September 2026. Leading with the year and using fixed-width
        # fields means the directory listing sorts chronologically on its own.
        session_id = session_id or datetime.now().strftime("S%Y%m%d_%H%M%S")
        local = LocalLog(session_id, self.base_dir)
        self._recorder = Recorder(local, self.online_store)
        self._info = SessionInfo(
            session_id=session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            # Counts start at zero, stopped_at at None, active at True.
            stopped_at=None, packet_count=0, local_bytes=0, rtdb_bytes_est=0,
            active=True,
        )
        # Write the metadata IMMEDIATELY, before any packet arrives. A session
        # killed one second in still leaves a file saying it existed and when it
        # began.
        self._write_meta()
        return self._info

    # PARAMETER
    #   record - one processed GroundStationRecord.
    # RETURNS
    #   None.
    def record(self, record: GroundStationRecord) -> None:
        """Persist one record - a no-op when no session is active."""
        # THE GATE. Returning early when inactive is what lets every caller
        # invoke this unconditionally. A "no-op" is a call that deliberately
        # does nothing.
        if not self.active or self._recorder is None:
            return
        # to_dict() applies the NaN and numpy scrubbing (see record.py) before
        # anything is written.
        local_bytes, online_bytes = self._recorder.record(record.to_dict())
        # Running totals, so the operator sees the session growing live.
        self._info.packet_count += 1
        self._info.local_bytes += local_bytes
        self._info.rtdb_bytes_est += online_bytes
        # Note the metadata file is NOT rewritten here. At ten packets a second
        # that would be ten extra file writes per second for information nobody
        # is reading between start and stop.

    # RETURNS
    #   the finalized SessionInfo, or None if no session was ever started.
    def stop(self) -> Optional[SessionInfo]:
        """End the session, persist metadata, and print a summary."""
        # IDEMPOTENT: calling stop twice is harmless, returning the same info
        # rather than raising. That matters because cleanup paths can run more
        # than once, such as a Ctrl-C during shutdown.
        if self._info is None or not self._info.active:
            return self._info
        self._info.active = False
        self._info.stopped_at = datetime.now(timezone.utc).isoformat()
        # Rewrite the metadata, now with the stop time and the final counts.
        self._write_meta()
        info = self._info
        # A summary for the person at the terminal. `:.1f` gives one decimal
        # place, and dividing by 1024 converts bytes to KiB, the binary
        # kilobyte of exactly 1024 bytes.
        print(
            f"[tetralux] session {info.session_id} stopped: "
            f"{info.packet_count} packets, {info.duration_s():.1f} s, "
            f"local {info.local_bytes / 1024:.1f} KiB, "
            # The tilde marks the Firebase figure as an ESTIMATE. The bytes sent
            # are known, but Firebase's own overhead is not, so claiming an
            # exact number would be false precision.
            f"rtdb ~{info.rtdb_bytes_est / 1024:.1f} KiB"
        )
        return info

    # Internal helper (primer 12). Writes session.json.
    def _write_meta(self) -> None:
        if self._info is None:
            return
        path = Path(self.base_dir) / self._info.session_id / META_FILE
        # .parent is the containing directory. Created here as well as in
        # LocalLog because this method can run before any record has been
        # written, so the directory may not exist yet.
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            # "w" TRUNCATES: the file is replaced rather than appended to, which
            # is what is wanted for metadata. Contrast local_log.py, which uses
            # "ab" precisely because records must accumulate.
            #
            # indent=2 pretty-prints, since a person may open this file. The
            # per-record log is not indented, for the opposite reason.
            json.dump(asdict(self._info), f, indent=2)
