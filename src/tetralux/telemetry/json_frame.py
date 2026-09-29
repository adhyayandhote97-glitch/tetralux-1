"""Real-hardware JSON telemetry codec (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
This is the border between the satellite and the ground station. The Arduino
sends one line of text per reading; this file turns that text into a SensorFrame
and back again.

A "codec" is a coder plus decoder. The two halves must agree exactly, byte for
byte, or nothing works:

    encode_json_frame  SensorFrame  ->  the exact text the firmware transmits
    decode_json_frame  text         ->  SensorFrame or RejectedFrame

THE WIRE FORMAT looks like this, all on one line:

    {"seq":1,"ts":5000,"pd":[812,0,455,0,210,0],"lux":[...],"mag":{...},
     "opt":[...],"temp":[...],"flags":1,"chk":173}

WHY A CHECKSUM. Data crossing a radio link gets corrupted: a bit flips and 812
becomes 940. That still parses as valid JSON, so nothing complains and a wrong
reading enters the estimate looking exactly like a right one. The firmware
therefore XORs every byte it sends and appends the result as "chk"; the ground
station recomputes it and compares. A mismatch means corruption, and the packet
is rejected rather than trusted.

THE BYTE-EXACT SUBTLETY, WHICH IS THE HARDEST THING IN THIS FILE. The checksum
must be computed over the ORIGINAL TRANSMITTED CHARACTERS, not over a
re-serialized version of the parsed data. Parse and re-serialize and Python may
write 25.0 where the firmware wrote 25.00, or reorder the keys, and every
checksum then fails on perfectly good data. An earlier version of this project
did exactly that. So decode_json_frame finds the checksum marker by searching
the raw TEXT and hashes the characters that came in.

WHERE IT SITS IN THE FLOW
    frames.py       defines the two output types
    ingest/         receives raw text over HTTP or serial and calls decode
    sim/sensors.py  round-trips virtual frames through both halves

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Union

from tetralux.constants import ADC_MAX, FACE_NAMES
from tetralux.frames import RejectedFrame, SensorFrame

# The exact text that marks where the checksum field begins. Everything BEFORE
# this point is what gets hashed, on both sides. Written with the quotes
# included so it cannot accidentally match a value somewhere else in the packet.
_CHK_MARKER = ',"chk"'
# Derived from FACE_NAMES rather than typed as 6, so if the geometry ever
# changed the validation would follow automatically.
_N_FACES = len(FACE_NAMES)
_N_OPT = 4


# --- The integrity check ---
#
# PARAMETER
#   data - the text or bytes to hash. Accepts both because it is called with
#          text when encoding and with raw bytes off the wire when decoding.
# RETURNS
#   a single number from 0 to 255.
#
# HOW XOR WORKS. Exclusive-or compares two numbers bit by bit and gives 1 where
# they differ, 0 where they match. Applied across every byte in turn, it
# produces one number that depends on all of them: flip any single bit anywhere
# in the packet and the result changes, which is exactly the property needed.
#
# It is chosen because the firmware side must run on an 8-bit microcontroller,
# where a real cryptographic hash would be far too slow. XOR is a handful of CPU
# instructions and catches the single-bit errors that radio links actually
# produce. It is not secure against deliberate tampering, and does not need to
# be.
def xor_checksum(data: Union[str, bytes]) -> int:
    """8-bit XOR checksum over ASCII bytes (matches the firmware)."""
    # .encode turns text into bytes. "replace" substitutes a placeholder for any
    # character that is not ASCII rather than raising, so a corrupted packet
    # full of noise still produces a checksum, which then simply fails to match.
    if isinstance(data, str):
        data = data.encode("ascii", "replace")
    acc = 0
    # Iterating over bytes gives each one as a number 0 to 255.
    for byte in data:
        # `^=` is "XOR with, and store back", the same shorthand as `+=`.
        acc ^= byte
    # `& 0xFF` keeps only the lowest 8 bits. Redundant here since XOR of bytes
    # cannot exceed 255, but it states the contract: this is an 8-BIT checksum,
    # matching the uint8_t the firmware uses.
    return acc & 0xFF


# --- Building the wire string ---
#
# PARAMETER
#   frame - the SensorFrame to serialize.
# RETURNS
#   one line of text, exactly as the firmware would transmit it.
#
# WHY THIS IS BUILT BY HAND WITH f-STRINGS INSTEAD OF json.dumps. The checksum
# must match what the Arduino computes, so the text must match the Arduino's
# output character for character: same key order, same number of decimal places,
# same absence of spaces. json.dumps makes its own formatting choices, and any
# one of them differing would break every checksum. Building the string
# explicitly is the only way to control it exactly.
#
# Each `:.1f` or `:.3f` is a decimal-place count that MIRRORS THE FIRMWARE. Do
# not adjust them without changing the firmware to match.
def encode_json_frame(frame: SensorFrame) -> str:
    """Serialize a :class:`SensorFrame` to the firmware's exact wire string."""
    # ",".join(...) glues a sequence of strings together with commas between.
    pd = ",".join(str(int(v)) for v in frame.photodiodes)
    lux = ",".join(f"{float(v):.1f}" for v in frame.lux)
    m = frame.magnetometer
    # Inside an f-string, `{{` and `}}` produce one literal brace, since a
    # single brace would start a substitution.
    mag = f'{{"x":{int(m["x"])},"y":{int(m["y"])},"z":{int(m["z"])}}}'
    opt = ",".join(
        f'{{"X":{float(o["X"]):.3f},"Y":{float(o["Y"]):.3f},'
        f'"Z":{float(o["Z"]):.3f},"lux":{float(o["lux"]):.1f}}}'
        for o in frame.opt
    )
    # A missing temperature sensor becomes the literal text `null`, which is how
    # JSON spells None. Distinct from 0.00, which would claim a reading of zero
    # degrees.
    temp = ",".join("null" if t is None else f"{float(t):.2f}" for t in frame.temperatures)

    # Body up to (not including) the checksum field - this is what gets XOR'd.
    #
    # Building the body separately is the crux of the design: the exact same
    # character sequence is hashed here and located by the decoder, so both
    # sides hash identical input.
    body = (
        f'{{"seq":{int(frame.seq)},"ts":{int(frame.timestamp_ms)},'
        f'"pd":[{pd}],"lux":[{lux}],"mag":{mag},"opt":[{opt}],'
        f'"temp":[{temp}],"flags":{int(frame.flags)}'
    )
    # Append the checksum and the closing brace. Note the frame's own `checksum`
    # field is ignored: the value transmitted is always freshly computed from
    # the body, so it cannot be stale or wrong.
    return f'{body},"chk":{xor_checksum(body)}}}'


# --- Schema validation ---
#
# PARAMETER
#   obj - a parsed JSON object, already known to be a dict.
# RETURNS
#   a reason string if something is wrong, or None if the structure is valid.
#
# RETURNING None FOR SUCCESS is a deliberate shape: the caller writes
# `if err is not None`, and every failure carries its own explanation rather
# than collapsing into a bare False that says nothing about what was wrong.
#
# WHY VALIDATE AT ALL WHEN THERE IS A CHECKSUM. The checksum proves the packet
# arrived UNCORRUPTED; it says nothing about whether it was correct when sent.
# Firmware with a bug can transmit five photodiode values with a perfectly valid
# checksum. This catches structural nonsense before it reaches code that assumes
# six of everything and would fail with a confusing IndexError deep in the
# pipeline.
def _structure_error(obj: dict) -> Union[str, None]:
    """Return a reason string if ``obj`` violates the packet schema, else None."""
    required = ("seq", "ts", "pd", "lux", "mag", "opt", "temp", "flags", "chk")
    for key in required:
        if key not in obj:
            return f"missing field '{key}'"

    # Photodiodes get the strictest checks, because they are the measurement
    # everything else is built on.
    pd = obj["pd"]
    if not isinstance(pd, list) or len(pd) != _N_FACES:
        return f"pd must have {_N_FACES} items"
    for v in pd:
        # Chained comparison: 0 <= v <= ADC_MAX. A value outside the ADC's
        # physical range is impossible from working hardware, so it means a
        # firmware bug or a spoofed packet.
        if not isinstance(v, int) or not (0 <= v <= ADC_MAX):
            # `!r` formats the value with quotes and type visible, so a string
            # "812" is distinguishable from the number 812 in the message.
            return f"pd value out of range 0-{ADC_MAX}: {v!r}"

    if not isinstance(obj["lux"], list) or len(obj["lux"]) != _N_FACES:
        return f"lux must have {_N_FACES} items"

    mag = obj["mag"]
    # any(...) is True if at least one key is missing.
    if not isinstance(mag, dict) or any(k not in mag for k in ("x", "y", "z")):
        return "mag must have x, y, z"

    opt = obj["opt"]
    if not isinstance(opt, list) or len(opt) != _N_OPT:
        return f"opt must have {_N_OPT} items"
    for o in opt:
        if not isinstance(o, dict) or any(k not in o for k in ("X", "Y", "Z", "lux")):
            return "opt items must have X, Y, Z, lux"

    temp = obj["temp"]
    # Length is checked but values are not, because None is legitimate here: a
    # DS18B20 that failed to respond reports null, and thermal/analysis.py
    # handles that.
    if not isinstance(temp, list) or len(temp) != _N_FACES:
        return f"temp must have {_N_FACES} items"

    # 0xFF is 255, the largest 8-bit value.
    if not isinstance(obj["chk"], int) or not (0 <= obj["chk"] <= 0xFF):
        return "chk must be an int 0-255"
    return None


# --- Reading the wire string ---
#
# PARAMETERS
#   raw         - one line of text or bytes as received.
#   source      - "real" or "virtual", recorded on the frame so the dashboard
#                 can label simulated data honestly.
#   received_at - arrival time, or None for now.
# RETURNS
#   a SensorFrame if everything checks out, otherwise a RejectedFrame carrying
#   the reason. NEVER raises: a ground station cannot crash because one packet
#   arrived mangled.
#
# The checks run in a deliberate order, cheapest and most fundamental first, so
# the most specific reason available is the one reported.
def decode_json_frame(
    raw: Union[str, bytes],
    source: str = "real",
    received_at: Union[datetime, None] = None,
) -> Union[SensorFrame, RejectedFrame]:
    """Decode one raw JSON payload into a :class:`SensorFrame` or :class:`RejectedFrame`."""
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
    # .strip() removes the trailing newline the firmware sends as a separator,
    # plus any stray whitespace. It must happen before the checksum region is
    # taken, or the hashed text would differ from what was hashed on the Arduino.
    text = text.strip()

    # CHECK 1: locate the checksum marker in the RAW TEXT.
    #
    # This is the byte-exact design working. rfind searches from the RIGHT,
    # deliberately: if some string value inside the packet happened to contain
    # `,"chk"`, searching forwards would find that one and hash the wrong
    # region. The real checksum field is always last.
    idx = text.rfind(_CHK_MARKER)
    if idx == -1:
        return RejectedFrame(None, "missing chk field", text, received_at)
    # Everything before the marker: the exact characters the firmware hashed.
    region = text[:idx]

    # CHECK 2: is it valid JSON at all? A truncated packet fails here.
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        # seq is None because a packet this broken has no readable sequence
        # number, and guessing one would be a fabrication.
        return RejectedFrame(None, f"JSON decode error: {exc}", text, received_at)
    if not isinstance(obj, dict):
        # Valid JSON can still be a list or a bare number, neither of which is a
        # telemetry packet.
        return RejectedFrame(None, "payload is not a JSON object", text, received_at)

    # CHECK 3: does it have the right shape? Runs BEFORE the checksum so that a
    # structurally broken packet gets a specific complaint rather than the
    # generic "checksum mismatch".
    err = _structure_error(obj)
    if err is not None:
        # By now seq may be readable, so .get retrieves it if present. Knowing
        # WHICH packet failed helps far more than knowing one did.
        return RejectedFrame(obj.get("seq"), err, text, received_at)

    # CHECK 4: integrity. The region hashed is the raw text captured above, not
    # anything re-serialized from obj. That is the whole point.
    expected = xor_checksum(region)
    if expected != int(obj["chk"]):
        return RejectedFrame(
            int(obj["seq"]),
            # Both numbers are reported. Consistently equal values with a fixed
            # offset suggest a firmware formatting mismatch; randomly varying
            # ones suggest a genuinely noisy link. Different problems.
            f"checksum mismatch: transmitted {obj['chk']}, computed {expected}",
            text,
            received_at,
        )

    # Every check passed, so this is a trustworthy reading.
    #
    # Each field is converted to its proper Python type, so downstream code
    # never has to wonder whether a value arrived as a string. This is also
    # where the type contract in frames.py is actually enforced.
    return SensorFrame(
        seq=int(obj["seq"]),
        timestamp_ms=int(obj["ts"]),
        photodiodes=[int(v) for v in obj["pd"]],
        lux=[float(v) for v in obj["lux"]],
        # Rebuilt key by key in a fixed order rather than copied wholesale, so
        # any extra keys the firmware might add are dropped rather than carried
        # into the frame.
        magnetometer={k: int(obj["mag"][k]) for k in ("x", "y", "z")},
        # A comprehension inside a comprehension: the outer walks the four
        # sensors, the inner rebuilds each one's four fields.
        opt=[{k: float(o[k]) for k in ("X", "Y", "Z", "lux")} for o in obj["opt"]],
        # None is preserved as None rather than becoming 0.0, so a dead sensor
        # stays distinguishable from one reading zero degrees.
        temperatures=[None if t is None else float(t) for t in obj["temp"]],
        flags=int(obj["flags"]),
        checksum=int(obj["chk"]),
        received_at=received_at,
        source=source,
    )
