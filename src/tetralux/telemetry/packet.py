"""Phase 4 — fixed-length binary telemetry packet codec.

Concrete framing built on the Phase 3 integrity primitives
(:mod:`tetralux.faults.packets`). Every packet is exactly :data:`PACKET_LEN`
bytes, big-endian:

    offset  size  field
    0       1     SYNC byte (0xAA) — frame start / resync marker
    1       2     seq — uint16 sequence counter (wraps at 65535)
    3       12    6 x uint16 face readings, in FACE_NAMES order (ADC counts)
    15      1     saturation bitfield — bit i set == FACE_NAMES[i] saturated
    16      1     8-bit additive checksum over bytes 0..15

Readings are quantized to 16-bit ADC counts (clamped to [0, 65535]); this is the
realistic lossy step a real analog-to-digital front end would introduce. The
per-face ``saturated`` flags survive losslessly in the bitfield.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import Optional

from tetralux.constants import FACE_NAMES
from tetralux.faults.packets import PacketFault, checksum8, validate_packet

SYNC_BYTE: int = 0xAA
ADC_MAX: int = 0xFFFF

# sync(B) + seq(H) + 6 readings(6H) + flags(B) = 16-byte payload; +1 checksum.
_STRUCT = struct.Struct(">BH6HB")
PACKET_LEN: int = _STRUCT.size + 1  # 17

# Nominal telemetry rate for the CubeSat link (~10-20 Hz).
DEFAULT_RATE_HZ: float = 10.0


class PacketError(Exception):
    """Raised when raw bytes cannot be decoded into a valid packet."""

    def __init__(self, message: str, fault: Optional[PacketFault] = None) -> None:
        super().__init__(message)
        self.fault = fault


def _quantize(reading: float) -> int:
    """Quantize a float reading to a 16-bit ADC count, clamped to range."""
    return int(min(ADC_MAX, max(0, round(float(reading)))))


def encode_packet(seq: int, face_readings: Mapping[str, Mapping[str, object]]) -> bytes:
    """Encode one sensor frame into a fixed-length packet.

    Args:
        seq: Sequence counter; only the low 16 bits are transmitted (wraps).
        face_readings: ``simulate_faces``-style mapping (raw reading + saturated).

    Returns:
        Exactly :data:`PACKET_LEN` bytes.
    """
    counts = [_quantize(float(face_readings[f]["reading"])) for f in FACE_NAMES]
    flags = 0
    for i, f in enumerate(FACE_NAMES):
        if bool(face_readings[f].get("saturated", False)):
            flags |= 1 << i
    payload = _STRUCT.pack(SYNC_BYTE, seq & 0xFFFF, *counts, flags)
    return payload + bytes([checksum8(payload)])


def decode_packet(raw: bytes) -> dict:
    """Decode and validate a single fixed-length packet.

    Args:
        raw: The received bytes (must be exactly :data:`PACKET_LEN`).

    Returns:
        ``{"seq": int, "readings": {face: count}, "saturated": {face: bool}}``.

    Raises:
        PacketError: on wrong length, bad sync byte, or checksum mismatch.
    """
    if len(raw) != PACKET_LEN:
        fault = PacketFault.TRUNCATED if len(raw) < PACKET_LEN else PacketFault.OVERSIZE
        raise PacketError(f"expected {PACKET_LEN} bytes, got {len(raw)}", fault)
    if raw[0] != SYNC_BYTE:
        raise PacketError(f"bad sync byte 0x{raw[0]:02x} (expected 0x{SYNC_BYTE:02x})")

    ok, faults = validate_packet(raw, PACKET_LEN)
    if not ok:
        raise PacketError(f"integrity check failed: {faults[0].value}", faults[0])

    sync, seq, *rest = _STRUCT.unpack(raw[: _STRUCT.size])
    counts, flags = rest[:6], rest[6]
    readings = {f: counts[i] for i, f in enumerate(FACE_NAMES)}
    saturated = {f: bool(flags >> i & 1) for i, f in enumerate(FACE_NAMES)}
    return {"seq": seq, "readings": readings, "saturated": saturated}


def iter_packets(stream: bytes):
    """Yield decoded packets from a byte stream, resyncing past corruption.

    Scans for the SYNC byte and attempts to decode a full packet there. On a bad
    checksum or a false sync the scanner advances one byte and keeps looking, so
    a corrupted or truncated packet is skipped rather than derailing the stream.

    Yields:
        The dicts returned by :func:`decode_packet`, in stream order.
    """
    i, n = 0, len(stream)
    while i <= n - PACKET_LEN:
        if stream[i] != SYNC_BYTE:
            i += 1
            continue
        try:
            frame = decode_packet(stream[i : i + PACKET_LEN])
        except PacketError:
            i += 1  # false sync or corruption; resync
            continue
        yield frame
        i += PACKET_LEN
