"""Phase 4: fake telemetry — fixed-length binary packets, 8-bit checksum, ~10-20 Hz.

Packet codec lives in :mod:`tetralux.telemetry.packet`; the stream generator in
:mod:`tetralux.telemetry.generator`.
"""

from tetralux.telemetry.generator import generate_telemetry, pack_stream
from tetralux.telemetry.packet import (
    ADC_MAX,
    DEFAULT_RATE_HZ,
    PACKET_LEN,
    SYNC_BYTE,
    PacketError,
    decode_packet,
    encode_packet,
    iter_packets,
)

__all__ = [
    "encode_packet",
    "decode_packet",
    "iter_packets",
    "PacketError",
    "PACKET_LEN",
    "SYNC_BYTE",
    "ADC_MAX",
    "DEFAULT_RATE_HZ",
    "generate_telemetry",
    "pack_stream",
]
