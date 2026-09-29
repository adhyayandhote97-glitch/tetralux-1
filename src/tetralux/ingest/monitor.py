"""Telemetry stream health monitor (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
This file watches the radio link itself rather than the measurements travelling
over it. A perfect sun estimate is worthless if half the packets never arrive,
and nothing else in the project would notice that.

It answers questions the individual frames cannot:

    Is the satellite still transmitting?   (connected)
    How fast are packets arriving?         (rate_hz)
    Are any going missing in transit?      (dropped, drop_rate, seq_gaps)
    Are any arriving corrupted?            (corrupt)

HOW LOSS IS DETECTED. Every packet carries a sequence number that counts up:
1, 2, 3. If 47 arrives after 45, packet 46 was lost. That gap is the only
evidence available, since a packet that never arrives leaves no other trace, and
it is the reason SensorFrame carries a `seq` field at all.

REJECTED VERSUS DROPPED, WHICH ARE DIFFERENT PROBLEMS. A rejected packet
arrived but failed its checksum, meaning the link is noisy and corrupting data.
A dropped packet never arrived at all, meaning the link is congested or the
signal is weak. Counting them separately is what lets an operator tell those
apart instead of guessing.

WHY MONOTONIC TIME. Every timestamp here comes from time.monotonic(), a clock
that only ever moves forward. The ordinary wall clock can jump backwards when
the system syncs with a time server, which would make a packet appear to arrive
before the one preceding it and produce negative rates.

WHERE IT SITS IN THE FLOW
    groundstation.py        feeds it every accepted and rejected frame
    ingest/http_server.py   exposes its stats at /health
    pipeline.py             embeds its snapshot in each record's `stream` field

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from tetralux.frames import RejectedFrame, SensorFrame


class StreamMonitor:
    """Rolling counters + rate/connection estimate for one telemetry stream."""

    # PARAMETERS
    #   timeout_s   - how long without a packet before the link counts as
    #                 disconnected. At about 10 packets per second, one full
    #                 second of silence means roughly ten missed in a row, which
    #                 is well past normal jitter.
    #   rate_window - how many recent arrival times to remember for the rate
    #                 calculation.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, timeout_s: float = 1.0, rate_window: int = 200) -> None:
        self._timeout = timeout_s
        # A self-limiting deque again (see validation/rolling.py): at 200
        # entries the oldest drops automatically, so an eight-hour session
        # cannot grow this without bound.
        self._accept_times: deque = deque(maxlen=rate_window)  # monotonic seconds
        # These six have NO leading underscore, unlike most attributes in this
        # project. That is deliberate: they are plain public counters meant to
        # be read directly, and there is nothing internal about them.
        self.total_received = 0
        self.total_accepted = 0
        self.total_rejected = 0
        self.seq_gaps = 0
        self.dropped = 0
        self.corrupt = 0
        # None rather than 0, because "no packet has ever arrived" is genuinely
        # different from "the last packet had sequence number 0" and from "the
        # last packet arrived at time zero".
        self._last_seq: Optional[int] = None
        self._last_accept_mono: Optional[float] = None

    # Called for each packet that passed its checksum.
    #
    # PARAMETERS
    #   frame - the accepted frame. Only its `seq` is used, for gap detection.
    #   now   - the current monotonic time, or None to read the clock. Passing
    #           it in is what makes this TESTABLE: a test can hand over
    #           fabricated timestamps and check the rate calculation without
    #           actually waiting a second. Every method here takes the same
    #           optional parameter for that reason.
    # RETURNS
    #   None; it updates counters.
    def record_accepted(self, frame: SensorFrame, now: Optional[float] = None) -> None:
        """Count an accepted frame; detect sequence gaps."""
        now = time.monotonic() if now is None else now
        # Both counters increment: received counts everything that arrived,
        # accepted counts the subset that was valid. record_rejected increments
        # received too, so the two always reconcile.
        self.total_received += 1
        self.total_accepted += 1
        self._accept_times.append(now)
        self._last_accept_mono = now

        # GAP DETECTION. Skipped on the very first packet, since there is
        # nothing to compare against and any starting sequence number is valid.
        if self._last_seq is not None:
            gap = frame.seq - self._last_seq
            # A gap of exactly 1 is normal: consecutive packets. Anything larger
            # means packets are missing.
            if gap > 1:
                # Two separate counts, measuring different things. seq_gaps
                # counts how many times a break occurred; dropped counts how
                # many packets were lost in total. One gap of 50 and fifty gaps
                # of 1 both lose 50 packets, but the first is a brief outage and
                # the second is a persistently bad link.
                self.seq_gaps += 1
                # `gap - 1` because a gap of 2 (45 to 47) means ONE packet lost,
                # not two.
                self.dropped += gap - 1
        self._last_seq = frame.seq

    # Called for each packet that failed to decode.
    #
    # PARAMETER
    #   rejected - the RejectedFrame, carrying the reason it failed.
    # RETURNS
    #   None.
    #
    # Note it does NOT touch _last_seq or _accept_times. A corrupt packet's
    # sequence number cannot be trusted, so using it for gap detection would
    # produce phantom gaps; and the rate is deliberately a rate of USABLE data.
    def record_rejected(self, rejected: RejectedFrame) -> None:
        """Count a rejected frame; classify checksum failures as corrupt."""
        self.total_received += 1
        self.total_rejected += 1
        # Distinguishing corruption from malformed structure. A checksum failure
        # means the link damaged the data in transit; a missing field means the
        # firmware sent something wrong. .lower() makes the match
        # case-insensitive, matching the message built in json_frame.py.
        if "checksum" in rejected.reason.lower():
            self.corrupt += 1

    # PARAMETERS
    #   now - current monotonic time, or None to read the clock.
    # RETURNS
    #   how many frames arrived in the last second, which IS the frequency in
    #   hertz, since hertz means "per second".
    #
    # Counting arrivals within a one-second window, rather than dividing a total
    # by an elapsed time, means this reflects the rate RIGHT NOW. An average
    # over the whole session would keep reporting 10 Hz for a long time after
    # the link went dead.
    def rate_hz(self, now: Optional[float] = None) -> float:
        """Accepted frames within the last second (≈ instantaneous Hz)."""
        now = time.monotonic() if now is None else now
        # `sum(1 for ...)` counts matching items: it produces a 1 for each and
        # adds them up.
        return float(sum(1 for t in self._accept_times if now - t <= 1.0))

    # RETURNS
    #   True if a packet arrived recently enough.
    #
    # There is no such thing as an open connection to check here: the satellite
    # posts packets and closes. So "connected" can only be inferred from recent
    # traffic, which is what this does. The `is not None` half handles the case
    # where nothing has ever arrived, which is disconnected rather than an
    # error.
    def connected(self, now: Optional[float] = None) -> bool:
        """True if a frame arrived within ``timeout_s``."""
        now = time.monotonic() if now is None else now
        return (
            self._last_accept_mono is not None
            and (now - self._last_accept_mono) <= self._timeout
        )

    # RETURNS
    #   the fraction of expected packets that were lost, 0.0 to 1.0.
    #   Dimensionless, since it is a count divided by a count.
    #
    # The denominator is accepted PLUS dropped, which is how many should have
    # arrived. Dividing by accepted alone would understate the loss: 90 received
    # and 10 lost is 10% loss, not 11%.
    def drop_rate(self) -> float:
        """Fraction of expected frames lost to sequence gaps (dimensionless)."""
        expected = self.total_accepted + self.dropped
        # `if expected else 0.0` avoids dividing by zero before any packet has
        # arrived. Zero loss is the honest answer when nothing was expected yet.
        return self.dropped / expected if expected else 0.0

    # RETURNS
    #   every counter as one plain dict.
    #
    # A single snapshot taken at one instant, so the numbers are consistent with
    # each other. Callers reading each counter separately could catch the
    # monitor mid-update and see a rate that does not match the totals. This is
    # what /health returns and what pipeline.py embeds in each record.
    def stats(self, now: Optional[float] = None) -> dict:
        """Snapshot of all counters for display."""
        return {
            "total_received": self.total_received,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "seq_gaps": self.seq_gaps,
            "dropped": self.dropped,
            "corrupt": self.corrupt,
            # The three computed values, evaluated now rather than stored.
            "rate_hz": self.rate_hz(now),
            "drop_rate": self.drop_rate(),
            "connected": self.connected(now),
            "last_seq": self._last_seq,
        }

    # Zero every counter, for the start of a new session.
    #
    # CALLING __init__ AGAIN is an unusual move and worth flagging. It works,
    # and it guarantees reset can never fall out of step with the constructor:
    # add a counter above and it is reset here automatically, with no second
    # place to remember. The two current settings are read back off the object
    # so they survive the reset.
    def reset(self) -> None:
        self.__init__(self._timeout, self._accept_times.maxlen)
