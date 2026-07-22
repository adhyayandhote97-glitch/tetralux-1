"""Guided calibration procedure (Phase 10).

Measures *this* prototype's actual dark offset, per-face gain, and max
illumination — replacing the hardcoded v0 lab placeholders in
``calibration.py`` with values captured from the real sensors.

The capture math (:func:`capture_dark_offsets`, :func:`capture_gain`,
:func:`capture_max_illumination`, :func:`run_guided_calibration`) is pure:
it consumes lists/streams of :class:`SensorFrame` and has no knowledge of where
they came from, so it can be exercised against the simulated device feed with
no hardware, or driven live by :func:`main` against a running ingest queue.

Procedure (see docs/bringup.md step 6):
1. **Dark** — cover all sensors / lights off -> average raw reading per face = D_i.
2. **Gain** — aim a known reference light dead-on at each face in turn -> solve
   G_i so the corrected reading hits ``target_reading``.
3. **Max illumination** — brightest expected exposure per face -> V_max_i.
"""

from __future__ import annotations

import argparse
import queue
import time
from typing import Callable, Sequence

import numpy as np

from tetralux.calibration import Calibration
from tetralux.constants import FACE_NAMES
from tetralux.frames import RejectedFrame, SensorFrame

DEFAULT_TARGET_READING = 1000.0
DEFAULT_N_SAMPLES = 30


def average_photodiodes(frames: Sequence[SensorFrame]) -> dict:
    """Per-face mean raw photodiode reading across ``frames``.

    Raises:
        ValueError: if ``frames`` is empty.
    """
    if not frames:
        raise ValueError("no frames captured — check the telemetry stream")
    sums = {f: 0.0 for f in FACE_NAMES}
    for fr in frames:
        pd = fr.photodiode_map()
        for f in FACE_NAMES:
            sums[f] += pd[f]
    return {f: sums[f] / len(frames) for f in FACE_NAMES}


def capture_dark_offsets(dark_frames: Sequence[SensorFrame]) -> dict:
    """Dark offset D_i per face: the average reading with no light."""
    return average_photodiodes(dark_frames)


def capture_gain(face: str, lit_frames: Sequence[SensorFrame], dark: dict,
                 target_reading: float = DEFAULT_TARGET_READING) -> float:
    """Solve gain G_i for one face so it reads ``target_reading`` when lit.

    ``R_i = (V_i - D_i) * G_i = target`` => ``G_i = target / (V_i - D_i)``.

    Raises:
        ValueError: if the dark-subtracted signal isn't positive (face wasn't
            actually illuminated, or dark offset was captured incorrectly).
    """
    avg = average_photodiodes(lit_frames)[face]
    signal = avg - dark[face]
    if signal <= 0:
        raise ValueError(
            f"face {face}: dark-subtracted signal is {signal:.2f} (<= 0) — "
            "is the reference light actually aimed at this face?"
        )
    return target_reading / signal


def capture_max_illumination(bright_frames: Sequence[SensorFrame]) -> dict:
    """Max raw reading observed per face (brightest expected exposure)."""
    if not bright_frames:
        raise ValueError("no frames captured — check the telemetry stream")
    out = {f: 0.0 for f in FACE_NAMES}
    for fr in bright_frames:
        pd = fr.photodiode_map()
        for f in FACE_NAMES:
            out[f] = max(out[f], float(pd[f]))
    return out


def run_guided_calibration(
    collect: Callable[[str], Sequence[SensorFrame]],
    target_reading: float = DEFAULT_TARGET_READING,
    lab_scaling_factor: float = 0.1,
) -> Calibration:
    """Drive the full dark -> gain -> max procedure and return a Calibration.

    Args:
        collect: Called with a step label (``"dark"``, ``"gain:<face>"``,
            ``"max"``) and must return the frames captured for that step
            (e.g. after prompting the operator and sampling the live stream).
        target_reading: Reference corrected-reading target for gain solving.
        lab_scaling_factor: Carried through to the resulting Calibration as-is
            (this procedure does not measure it).

    Returns:
        A fully populated :class:`Calibration`.
    """
    dark = capture_dark_offsets(collect("dark"))

    gain = {}
    for face in FACE_NAMES:
        frames = collect(f"gain:{face}")
        gain[face] = capture_gain(face, frames, dark, target_reading)

    max_illum = capture_max_illumination(collect("max"))

    return Calibration(dark=dark, gain=gain, max_illumination=max_illum,
                       lab_scaling_factor=lab_scaling_factor)


# ---------------------------------------------------------------------------
# Live CLI: drains a running ingest queue, prompting the operator at each step.
# ---------------------------------------------------------------------------
def step_prompt(step: str) -> str:
    """The operator-facing instruction for a given collection step.

    Args:
        step: ``"dark"``, ``"max"``, or ``"gain:<face>"``.
    """
    if step == "dark":
        return "Cover all sensors / turn off all light, then press Enter…"
    if step == "max":
        return "Present the brightest expected exposure to all faces, then press Enter…"
    face = step.split(":")[1]
    return f"Aim the reference light dead-on at face {face}, then press Enter…"


def _flush_queue(frame_queue: "queue.Queue") -> int:
    """Discard everything currently queued (non-blocking). Returns count dropped.

    A live device streams continuously between prompts; without this, frames
    posted *before* the operator finished repositioning the light (still
    reflecting the previous step's conditions) would sit at the front of the
    FIFO and get consumed as if they belonged to the new step. Call this right
    after the operator confirms readiness, before sampling.
    """
    dropped = 0
    while True:
        try:
            frame_queue.get_nowait()
            dropped += 1
        except queue.Empty:
            return dropped


def _drain_live(frame_queue: "queue.Queue", n: int, timeout_s: float = 15.0):
    """Decode up to ``n`` valid frames from a raw-string queue, skipping rejects."""
    from tetralux.telemetry.json_frame import decode_json_frame

    frames = []
    deadline = time.time() + timeout_s
    while len(frames) < n and time.time() < deadline:
        try:
            raw = frame_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        result = decode_json_frame(raw)
        if isinstance(result, RejectedFrame):
            continue
        frames.append(result)
    return frames


def main() -> None:
    """Interactive CLI: connect to a running ground station and calibrate it.

    Requires a ground-station ingest server or serial reader already running
    and feeding the same process's queue is impractical across processes, so
    this CLI runs its own lightweight ingest (HTTP by default, or serial) just
    for the calibration session.
    """
    ap = argparse.ArgumentParser(description="Tetralux-1 guided calibration")
    ap.add_argument("--port", type=int, default=8000, help="HTTP ingest port")
    ap.add_argument("--serial", default=None, help="serial port instead of HTTP")
    ap.add_argument("--samples", type=int, default=DEFAULT_N_SAMPLES)
    ap.add_argument("--target-reading", type=float, default=DEFAULT_TARGET_READING)
    ap.add_argument("--out", default="calibration.json")
    args = ap.parse_args()

    from tetralux.ingest.queue import create_frame_queue

    frame_queue = create_frame_queue()
    reader = None
    server_thread = None

    if args.serial:
        from tetralux.ingest.serial_reader import SerialReader

        reader = SerialReader(frame_queue.put_nowait, args.serial)
        reader.start()
    else:
        import threading

        from tetralux.ingest.http_server import run_ingest_server

        server_thread = threading.Thread(
            target=run_ingest_server,
            kwargs={"on_frame": frame_queue.put_nowait, "port": args.port},
            daemon=True,
        )
        server_thread.start()
        print(f"[calibration] listening on http://0.0.0.0:{args.port}/ingest")

    def collect(step: str):
        input(f"\n[{step}] {step_prompt(step)} ")
        # Discard any backlog from before the operator was ready — otherwise
        # frames still queued from the *previous* step's conditions would be
        # sampled as if they belonged to this one (see _flush_queue docstring).
        stale = _flush_queue(frame_queue)
        if stale:
            print(f"  discarded {stale} stale frame(s) queued before this step")
        print(f"  sampling {args.samples} frames…")
        frames = _drain_live(frame_queue, args.samples)
        print(f"  captured {len(frames)} frames")
        return frames

    cal = run_guided_calibration(collect, target_reading=args.target_reading)
    cal.save(args.out)
    print(f"\nSaved calibration to {args.out}")
    print(cal.to_json())

    if reader is not None:
        reader.stop()


if __name__ == "__main__":
    main()
