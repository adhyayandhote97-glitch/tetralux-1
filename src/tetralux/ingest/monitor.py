"""Telemetry stream health monitor (Phase 6).

Tracks packet counts, sequence gaps (dropped frames), checksum failures
(corrupt frames), the live packet rate, and connection state (age of the last
accepted frame). Feeds the dashboard's stream-status and connection indicators.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from tetralux.frames import RejectedFrame, SensorFrame


class StreamMonitor:
    """Rolling counters + rate/connection estimate for one telemetry stream."""

    def __init__(self, timeout_s: float = 1.0, rate_window: int = 200) -> None:
        self._timeout = timeout_s
        self._accept_times: deque = deque(maxlen=rate_window)  # monotonic seconds
        self.total_received = 0
        self.total_accepted = 0
        self.total_rejected = 0
        self.seq_gaps = 0
        self.dropped = 0
        self.corrupt = 0
        self._last_seq: Optional[int] = None
        self._last_accept_mono: Optional[float] = None

    def record_accepted(self, frame: SensorFrame, now: Optional[float] = None) -> None:
        """Count an accepted frame; detect sequence gaps."""
        now = time.monotonic() if now is None else now
        self.total_received += 1
        self.total_accepted += 1
        self._accept_times.append(now)
        self._last_accept_mono = now

        if self._last_seq is not None:
            gap = frame.seq - self._last_seq
            if gap > 1:
                self.seq_gaps += 1
                self.dropped += gap - 1
        self._last_seq = frame.seq

    def record_rejected(self, rejected: RejectedFrame) -> None:
        """Count a rejected frame; classify checksum failures as corrupt."""
        self.total_received += 1
        self.total_rejected += 1
        if "checksum" in rejected.reason.lower():
            self.corrupt += 1

    def rate_hz(self, now: Optional[float] = None) -> float:
        """Accepted frames within the last second (≈ instantaneous Hz)."""
        now = time.monotonic() if now is None else now
        return float(sum(1 for t in self._accept_times if now - t <= 1.0))

    def connected(self, now: Optional[float] = None) -> bool:
        """True if a frame arrived within ``timeout_s``."""
        now = time.monotonic() if now is None else now
        return (
            self._last_accept_mono is not None
            and (now - self._last_accept_mono) <= self._timeout
        )

    def drop_rate(self) -> float:
        """Fraction of expected frames lost to sequence gaps (dimensionless)."""
        expected = self.total_accepted + self.dropped
        return self.dropped / expected if expected else 0.0

    def stats(self, now: Optional[float] = None) -> dict:
        """Snapshot of all counters for display."""
        return {
            "total_received": self.total_received,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "seq_gaps": self.seq_gaps,
            "dropped": self.dropped,
            "corrupt": self.corrupt,
            "rate_hz": self.rate_hz(now),
            "drop_rate": self.drop_rate(),
            "connected": self.connected(now),
            "last_seq": self._last_seq,
        }

    def reset(self) -> None:
        self.__init__(self._timeout, self._accept_times.maxlen)
