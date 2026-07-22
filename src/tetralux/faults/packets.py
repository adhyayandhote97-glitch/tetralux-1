"""Phase 3 — packet-integrity primitives (corrupted / truncated telemetry).

Format-agnostic building blocks for the "corrupted/truncated packets" failure
mode. They operate on raw ``bytes`` so Phase 4's fixed-length binary packet
layer can build its concrete framing on top without re-deriving the checks.

The checksum here is an 8-bit additive checksum (sum of payload bytes mod 256),
the common meaning of "8-bit checksum". Phase 4 may pin a specific variant.
"""

from __future__ import annotations

import enum


class PacketFault(enum.Enum):
    """Why a raw packet failed integrity validation."""

    TRUNCATED = "truncated"          # fewer bytes than the fixed length
    OVERSIZE = "oversize"            # more bytes than the fixed length
    BAD_CHECKSUM = "bad_checksum"    # payload checksum mismatch


def checksum8(payload: bytes) -> int:
    """8-bit additive checksum: ``sum(payload) & 0xFF``."""
    return sum(payload) & 0xFF


def verify_checksum(payload: bytes, expected: int) -> bool:
    """True if ``checksum8(payload)`` equals ``expected`` (low 8 bits)."""
    return checksum8(payload) == (expected & 0xFF)


def is_truncated(raw: bytes, expected_len: int) -> bool:
    """True if ``raw`` is shorter than a full fixed-length packet."""
    return len(raw) < expected_len


def validate_packet(raw: bytes, expected_len: int) -> tuple[bool, tuple[PacketFault, ...]]:
    """Validate a fixed-length packet whose last byte is its 8-bit checksum.

    Layout assumed: ``payload = raw[:-1]``, ``checksum = raw[-1]``.

    Args:
        raw: The received bytes.
        expected_len: The fixed total packet length (payload + 1 checksum byte).

    Returns:
        ``(ok, faults)`` where ``ok`` is True only when the length matches and
        the checksum verifies. Length faults short-circuit the checksum check
        (a truncated packet has no trustworthy checksum byte).
    """
    if len(raw) < expected_len:
        return False, (PacketFault.TRUNCATED,)
    if len(raw) > expected_len:
        return False, (PacketFault.OVERSIZE,)

    payload, checksum = raw[:-1], raw[-1]
    if not verify_checksum(payload, checksum):
        return False, (PacketFault.BAD_CHECKSUM,)
    return True, ()
