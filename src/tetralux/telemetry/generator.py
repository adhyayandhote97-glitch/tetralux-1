"""Phase 4 — fake telemetry generator.

Turns a light-direction trajectory into a timed stream of encoded packets, the
software stand-in for the CubeSat's radio downlink. No real-time sleeping: each
frame is stamped with a nominal timestamp derived from the rate, so downstream
code (replay, dashboard) can play it back at any speed.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from tetralux.sim.simulator import simulate_faces
from tetralux.telemetry.packet import DEFAULT_RATE_HZ, encode_packet


def generate_telemetry(
    light_dirs: Iterable[np.ndarray],
    rate_hz: float = DEFAULT_RATE_HZ,
    seq_start: int = 0,
    **sim_kwargs: object,
) -> list[tuple[float, bytes]]:
    """Simulate and encode a packet per light direction.

    Args:
        light_dirs: Sequence of light-direction vectors (one per frame).
        rate_hz: Nominal downlink rate; frame ``i`` is timestamped ``i / rate_hz``.
        seq_start: Sequence counter for the first packet (wraps at 65535).
        **sim_kwargs: Forwarded to :func:`simulate_faces` (intensity, noise_std,
            dark_current, gain, saturation_limit, rng).

    Returns:
        List of ``(timestamp_s, packet_bytes)`` pairs in emission order.

    Raises:
        ValueError: if ``rate_hz`` is not positive.
    """
    if rate_hz <= 0.0:
        raise ValueError(f"rate_hz must be positive, got {rate_hz}")

    dt = 1.0 / rate_hz
    stream: list[tuple[float, bytes]] = []
    seq = seq_start & 0xFFFF
    for i, light_dir in enumerate(light_dirs):
        faces = simulate_faces(light_dir, **sim_kwargs)  # type: ignore[arg-type]
        stream.append((i * dt, encode_packet(seq, faces)))
        seq = (seq + 1) & 0xFFFF
    return stream


def pack_stream(packets: Iterable[bytes]) -> bytes:
    """Concatenate packets into one contiguous byte stream (as a radio would)."""
    return b"".join(packets)
