"""Real-hardware JSON telemetry codec (Phase 6).

The firmware transmits one newline-terminated ASCII JSON object per sample:

    {"seq":N,"ts":N,"pd":[6],"lux":[6],"mag":{x,y,z},"opt":[4],"temp":[6],"flags":N,"chk":N}

The 8-bit checksum is an **XOR of the raw ASCII bytes of the body up to (but not
including) `,"chk"`** — the exact bytes on the wire, in transmit order. We
reproduce that byte-for-byte rather than re-serializing the parsed object (the v0
parser's re-serialize approach broke on float formatting, e.g. `25.00` vs
`25.0`). ``encode_json_frame`` emits the identical format so the virtual twin and
the real device share one codec.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Union

from tetralux.constants import ADC_MAX, FACE_NAMES
from tetralux.frames import RejectedFrame, SensorFrame

_CHK_MARKER = ',"chk"'
_N_FACES = len(FACE_NAMES)
_N_OPT = 4


def xor_checksum(data: Union[str, bytes]) -> int:
    """8-bit XOR checksum over ASCII bytes (matches the firmware)."""
    if isinstance(data, str):
        data = data.encode("ascii", "replace")
    acc = 0
    for byte in data:
        acc ^= byte
    return acc & 0xFF


def encode_json_frame(frame: SensorFrame) -> str:
    """Serialize a :class:`SensorFrame` to the firmware's exact wire string.

    Float formats match the firmware (`lux` %.1f, `opt` %.3f, `temp` %.2f, `null`
    for a missing temperature), so the appended checksum verifies on decode.
    """
    pd = ",".join(str(int(v)) for v in frame.photodiodes)
    lux = ",".join(f"{float(v):.1f}" for v in frame.lux)
    m = frame.magnetometer
    mag = f'{{"x":{int(m["x"])},"y":{int(m["y"])},"z":{int(m["z"])}}}'
    opt = ",".join(
        f'{{"X":{float(o["X"]):.3f},"Y":{float(o["Y"]):.3f},'
        f'"Z":{float(o["Z"]):.3f},"lux":{float(o["lux"]):.1f}}}'
        for o in frame.opt
    )
    temp = ",".join("null" if t is None else f"{float(t):.2f}" for t in frame.temperatures)

    # Body up to (not including) the checksum field — this is what gets XOR'd.
    body = (
        f'{{"seq":{int(frame.seq)},"ts":{int(frame.timestamp_ms)},'
        f'"pd":[{pd}],"lux":[{lux}],"mag":{mag},"opt":[{opt}],'
        f'"temp":[{temp}],"flags":{int(frame.flags)}'
    )
    return f'{body},"chk":{xor_checksum(body)}}}'


def _structure_error(obj: dict) -> Union[str, None]:
    """Return a reason string if ``obj`` violates the packet schema, else None."""
    required = ("seq", "ts", "pd", "lux", "mag", "opt", "temp", "flags", "chk")
    for key in required:
        if key not in obj:
            return f"missing field '{key}'"

    pd = obj["pd"]
    if not isinstance(pd, list) or len(pd) != _N_FACES:
        return f"pd must have {_N_FACES} items"
    for v in pd:
        if not isinstance(v, int) or not (0 <= v <= ADC_MAX):
            return f"pd value out of range 0-{ADC_MAX}: {v!r}"

    if not isinstance(obj["lux"], list) or len(obj["lux"]) != _N_FACES:
        return f"lux must have {_N_FACES} items"

    mag = obj["mag"]
    if not isinstance(mag, dict) or any(k not in mag for k in ("x", "y", "z")):
        return "mag must have x, y, z"

    opt = obj["opt"]
    if not isinstance(opt, list) or len(opt) != _N_OPT:
        return f"opt must have {_N_OPT} items"
    for o in opt:
        if not isinstance(o, dict) or any(k not in o for k in ("X", "Y", "Z", "lux")):
            return "opt items must have X, Y, Z, lux"

    temp = obj["temp"]
    if not isinstance(temp, list) or len(temp) != _N_FACES:
        return f"temp must have {_N_FACES} items"

    if not isinstance(obj["chk"], int) or not (0 <= obj["chk"] <= 0xFF):
        return "chk must be an int 0-255"
    return None


def decode_json_frame(
    raw: Union[str, bytes],
    source: str = "real",
    received_at: Union[datetime, None] = None,
) -> Union[SensorFrame, RejectedFrame]:
    """Decode one raw JSON payload into a :class:`SensorFrame` or :class:`RejectedFrame`.

    Validation order: locate checksum region -> JSON parse -> structure/range ->
    byte-exact XOR checksum. Sequence-gap tracking is stateful and lives in
    :class:`tetralux.ingest.monitor.StreamMonitor`, not here.
    """
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
    text = text.strip()

    idx = text.rfind(_CHK_MARKER)
    if idx == -1:
        return RejectedFrame(None, "missing chk field", text, received_at)
    region = text[:idx]

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return RejectedFrame(None, f"JSON decode error: {exc}", text, received_at)
    if not isinstance(obj, dict):
        return RejectedFrame(None, "payload is not a JSON object", text, received_at)

    err = _structure_error(obj)
    if err is not None:
        return RejectedFrame(obj.get("seq"), err, text, received_at)

    expected = xor_checksum(region)
    if expected != int(obj["chk"]):
        return RejectedFrame(
            int(obj["seq"]),
            f"checksum mismatch: transmitted {obj['chk']}, computed {expected}",
            text,
            received_at,
        )

    return SensorFrame(
        seq=int(obj["seq"]),
        timestamp_ms=int(obj["ts"]),
        photodiodes=[int(v) for v in obj["pd"]],
        lux=[float(v) for v in obj["lux"]],
        magnetometer={k: int(obj["mag"][k]) for k in ("x", "y", "z")},
        opt=[{k: float(o[k]) for k in ("X", "Y", "Z", "lux")} for o in obj["opt"]],
        temperatures=[None if t is None else float(t) for t in obj["temp"]],
        flags=int(obj["flags"]),
        checksum=int(obj["chk"]),
        received_at=received_at,
        source=source,
    )
