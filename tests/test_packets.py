"""Tests for the Phase 3 packet-integrity primitives."""

from tetralux.faults.packets import (
    PacketFault,
    checksum8,
    is_truncated,
    validate_packet,
    verify_checksum,
)


def test_checksum8_sum_and_wraparound():
    assert checksum8(bytes([1, 2, 3])) == 6
    assert checksum8(bytes([200, 100])) == 300 & 0xFF  # wraps: 44


def test_verify_checksum():
    payload = bytes([0x10, 0x20, 0x30])
    assert verify_checksum(payload, checksum8(payload))
    assert not verify_checksum(payload, checksum8(payload) ^ 0xFF)


def test_is_truncated():
    assert is_truncated(b"123", 5)
    assert not is_truncated(b"12345", 5)


def test_validate_packet_accepts_good_packet():
    payload = bytes([0x10, 0x20, 0x30])
    raw = payload + bytes([checksum8(payload)])
    ok, faults = validate_packet(raw, expected_len=len(raw))
    assert ok
    assert faults == ()


def test_validate_packet_detects_truncation():
    payload = bytes([0x10, 0x20, 0x30])
    raw = payload + bytes([checksum8(payload)])
    ok, faults = validate_packet(raw[:2], expected_len=len(raw))
    assert not ok
    assert faults == (PacketFault.TRUNCATED,)


def test_validate_packet_detects_oversize():
    payload = bytes([0x10, 0x20, 0x30])
    raw = payload + bytes([checksum8(payload)])
    ok, faults = validate_packet(raw + b"\x00", expected_len=len(raw))
    assert not ok
    assert faults == (PacketFault.OVERSIZE,)


def test_validate_packet_detects_bad_checksum():
    payload = bytes([0x10, 0x20, 0x30])
    raw = payload + bytes([(checksum8(payload) + 1) & 0xFF])  # wrong checksum byte
    ok, faults = validate_packet(raw, expected_len=len(raw))
    assert not ok
    assert faults == (PacketFault.BAD_CHECKSUM,)
