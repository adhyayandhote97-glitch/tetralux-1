"""The ground-station frame contract (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
This file defines the shape of one sensor reading. It is the agreed contract
between the hardware and the rest of the software: the Arduino promises to send
these fields, and everything downstream promises to expect exactly these fields.

A "frame" is one complete snapshot of every instrument at one instant: all six
photodiodes, all six lux sensors, the magnetometer, the colour sensor, the six
temperatures, plus a sequence number and a checksum. Roughly ten of these
arrive every second while the satellite is streaming.

Two classes live here:

    SensorFrame    a reading that arrived intact and can be processed
    RejectedFrame  a payload that arrived corrupted and must not be processed

Keeping those separate is the important design choice. A frame with a failed
checksum is not "a frame with a small problem"; its numbers cannot be trusted at
all. Making it a different type means no code can accidentally feed a corrupt
reading into the estimator, because the estimator only accepts SensorFrame.

WHERE IT SITS IN THE FLOW
    telemetry/json_frame.py  decodes raw text into one of these two types
    pipeline.py              takes a SensorFrame and produces a record
    sim/sensors.py           fabricates SensorFrames for Virtual mode

Virtual mode builds the exact same SensorFrame type real hardware does, which is
why one pipeline serves both, and why the simulator is a genuine test of the
real code path rather than a separate mock.

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# dataclass: a decorator that writes the boring setup code for a class that
# mostly just holds fields (primer section 12).
# field: needed for the `received_at` default, explained where it is used.
from dataclasses import dataclass, field
# datetime: Python's date-and-time type. timezone: lets us stamp times as UTC.
from datetime import datetime, timezone
# Optional[X] is a type hint meaning "an X, or None" (primer sections 6 and 8).
from typing import Optional

from tetralux.constants import FACE_NAMES


# The leading underscore marks this as internal to this file (primer 12).
#
# WHY UTC: the ground station, the satellite and any future collaborator may sit
# in different time zones. Recording local time would make two logs impossible
# to line up. UTC is the single worldwide reference, so every timestamp in this
# project is UTC and comparisons always work.
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# @dataclass generates the constructor automatically. Because of it you can
# write SensorFrame(seq=1, timestamp_ms=500, ...) and each value is stored on
# the object, without hand-writing an __init__ that assigns eleven fields.
@dataclass
class SensorFrame:
    """One fully-populated sensor sample from all instruments."""

    # Each line below declares one FIELD: a piece of data every SensorFrame
    # carries. The part after the colon is its type hint.
    #
    # The first nine have no default value, so they are REQUIRED: creating a
    # SensorFrame without them is an error. That is intentional. A frame missing
    # its checksum is not a frame, and failing loudly at creation is far better
    # than discovering the gap later inside a calculation.
    seq: int                              # sequence counter (dimensionless index)
    timestamp_ms: int                     # device time since boot (ms)
    photodiodes: list                     # 6x S1223 raw ADC counts (0-1023)
    lux: list                             # 6x BH1750 illuminance (lx)
    magnetometer: dict                    # QMC5883L {"x","y","z"} raw int
    opt: list                             # 4x OPT4048 {"X","Y","Z","lux"}
    temperatures: list                    # 6x DS18B20 degC (None if missing)
    flags: int                            # uint8 status bitfield
    checksum: int                         # transmitted 8-bit checksum (0-255)
    #
    # Notes on the less obvious ones:
    #
    # seq counts packets: 1, 2, 3. A gap in this sequence is how the ground
    #   station knows packets were dropped in transit - a packet that never
    #   arrives leaves no other trace.
    # timestamp_ms is the satellite's own clock, milliseconds since it powered
    #   on. Not a wall-clock date, and meaningless across a reboot.
    # photodiodes holds six raw ADC counts in FACE_NAMES order: the primary
    #   measurement the whole sun estimate is built from.
    # flags is a "bitfield": one integer whose individual binary digits each
    #   carry a separate yes/no status, a compact way to send several booleans
    #   in one byte.
    # checksum is the integrity check. The firmware XORs every byte of the
    #   message and sends the result; the ground station recomputes it and
    #   compares. A mismatch means the data was corrupted in transit.

    # These last two DO have defaults, so a caller may omit them.
    #
    # received_at uses field(default_factory=...) rather than a plain default,
    # and the reason is a genuine Python trap. Writing `received_at = _utcnow()`
    # would call the function ONCE, when Python first reads this class, so every
    # frame created for the rest of the program would share that one frozen
    # timestamp. default_factory says "call _utcnow fresh for each new frame".
    # Note `_utcnow` with no brackets: the function itself is passed, not the
    # result of calling it.
    #
    # It is also deliberately distinct from timestamp_ms above. That one is when
    # the satellite took the reading; this is when it landed here. Comparing the
    # two reveals transmission delay.
    received_at: datetime = field(default_factory=_utcnow)
    # Records where the frame came from, so the dashboard can label a reading
    # honestly rather than presenting simulated data as measured.
    source: str = "real"                  # "real" | "virtual"

    # A function defined inside a class is a METHOD (primer section 12).
    # `self` is the particular SensorFrame it was called on. You never pass it:
    # `frame.photodiode_map()` gives Python self automatically.
    #
    # PARAMETERS: none besides self. It needs no inputs because everything it
    #   works on is already stored on the frame.
    # RETURNS: a dict mapping face name to that face's reading.
    #
    # WHY THIS EXISTS: the wire format is a bare list, [812, 0, 455, ...], which
    # is compact to transmit but easy to misread; photodiodes[3] tells you
    # nothing about which face that is. This converts to the labelled form
    # {"+x": 812, "-x": 0, ...} that the rest of the code uses, so the
    # position-to-name mapping happens in exactly one place.
    def photodiode_map(self) -> dict:
        """Photodiode readings keyed by face name."""
        # A dict comprehension (primer section 10). enumerate walks FACE_NAMES
        # and gives both position and name, so i is 0,1,2... while f is
        # "+x","-x","+y"... Each pass adds one `name: reading` pair.
        return {f: self.photodiodes[i] for i, f in enumerate(FACE_NAMES)}

    # Same idea for the BH1750 illuminance sensors, in lux.
    #
    # The photodiodes and the lux sensors measure overlapping things by
    # different means: photodiodes are fast and raw, the BH1750 is calibrated
    # into real physical units. Keeping both lets the ground station
    # cross-check one against the other.
    def lux_map(self) -> dict:
        """Lux readings keyed by face name."""
        return {f: self.lux[i] for i, f in enumerate(FACE_NAMES)}


@dataclass
class RejectedFrame:
    """A raw payload that failed to decode (bad JSON, structure, or checksum)."""

    # A separate type from SensorFrame, on purpose: this holds no usable
    # measurements, so it must be impossible to feed into the estimator. The
    # type system enforces that for free.
    #
    # seq is Optional[int], meaning "an int or None" (primer 8). If the payload
    # was mangled badly enough, there is no readable sequence number at all, and
    # None says so honestly rather than guessing 0.
    seq: Optional[int]
    # Why it was rejected, in plain words, so a person debugging a flaky radio
    # link can tell a checksum failure from malformed JSON.
    reason: str
    # The original text exactly as received. Kept so the failure can be examined
    # afterwards; a discarded bad packet teaches nothing.
    raw: str
    # Same fresh-timestamp mechanism as SensorFrame. Rejections cluster in time
    # when a link degrades, so when they arrived is diagnostic information.
    received_at: datetime = field(default_factory=_utcnow)
