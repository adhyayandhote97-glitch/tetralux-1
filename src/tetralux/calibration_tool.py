"""Guided calibration procedure (Phase 10).

WHAT THIS FILE CONTRIBUTES
--------------------------
calibration.py holds the three per-face numbers that make six photodiodes
comparable. This file MEASURES them from a real prototype, by walking an
operator through a physical procedure:

    python -m tetralux.calibration_tool --port 8000 --out calibration.json

THE PROCEDURE, EIGHT STEPS
    1.    "dark"      Cover everything. Whatever the sensors still read is their
                      dark offset, D_i.
    2-7.  "gain:+x"   Aim the reference light dead-on at each face in turn. Gain
          ... "gain:-z"  is whatever factor makes that face report the target
                      reading, so all six end up on a common scale.
    8.    "max"       Present the brightest exposure the satellite will meet.
                      The peak each face reaches is its V_max, the denominator
                      of formula 5.

WHY IT MUST BE RUN. The defaults in calibration.py came from a different
prototype. Using them on this board means every measurement is quietly scaled
wrong, and the sun estimate carries a permanent lean that shows up as bias_deg.

THE BUG THAT SHAPED THIS FILE. A real device streams continuously, including
while the operator is repositioning the lamp between steps. Those frames pile up
in the queue, so when sampling for "gain:-x" began, the frames at the front of
the queue were still from "gain:+x" conditions and got averaged in as if they
belonged to the new step. The recovered gains were wrong and nothing indicated
why. `_flush_queue` below is the fix, and in live testing it discarded 11 to 22
stale frames per step.

SEPARATION OF MATHS FROM PROMPTING. The top half of this file is pure functions
that take frames and return numbers, testable with fabricated data and no
hardware. The bottom half handles queues, prompts and printing. That split is
why the calibration arithmetic has real tests.

This is one of the three files that use print(), because it is a command-line
tool a person watches (see docs/python-primer.md, section 2).

WHERE IT SITS IN THE FLOW
    ingest/          supplies the live telemetry this samples
    calibration.py   defines the Calibration this produces and saves
    groundstation.py loads the resulting file with --calibration

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import argparse
import queue
import time
from typing import Callable, Sequence


from tetralux.calibration import Calibration
from tetralux.constants import FACE_NAMES
from tetralux.frames import RejectedFrame, SensorFrame

# What a fully lit face should read after calibration. Every face's gain is
# solved to hit this number, which is what puts all six on one scale. Below the
# 1023 ADC ceiling so a slightly brighter source does not immediately saturate.
DEFAULT_TARGET_READING = 1000.0
# How many frames to average per step. Averaging suppresses noise; 30 frames at
# about 10 Hz is roughly three seconds of holding still.
DEFAULT_N_SAMPLES = 30


# --- Averaging helper, used by two of the three steps ---
#
# PARAMETER
#   frames - the SensorFrames captured during one step.
# RETURNS
#   a dict of mean raw readings, one per face.
#
# Raises ValueError on an empty list rather than dividing by zero. Zero frames
# means the telemetry stream is dead, and saying so plainly beats a
# ZeroDivisionError from three functions deeper.
def average_photodiodes(frames: Sequence[SensorFrame]) -> dict:
    """Per-face mean raw photodiode reading across ``frames``."""
    if not frames:
        raise ValueError("no frames captured - check the telemetry stream")
    # A running total per face, starting at zero.
    sums = {f: 0.0 for f in FACE_NAMES}
    for fr in frames:
        pd = fr.photodiode_map()
        for f in FACE_NAMES:
            sums[f] += pd[f]
    # Divide each total by the number of frames to get the mean.
    return {f: sums[f] / len(frames) for f in FACE_NAMES}


# --- Step 1: the dark offset ---
#
# PARAMETER
#   dark_frames - frames captured with everything covered.
# RETURNS
#   D_i per face, the reading each photodiode gives with no light.
#
# A one-line wrapper around the averaging helper, and worth having anyway: the
# NAME states what the measurement means. `capture_dark_offsets(frames)` says
# what is happening at the call site in a way `average_photodiodes(frames)` does
# not.
def capture_dark_offsets(dark_frames: Sequence[SensorFrame]) -> dict:
    """Dark offset D_i per face: the average reading with no light."""
    return average_photodiodes(dark_frames)


# --- Steps 2 to 7: the gain for one face ---
#
# PARAMETERS
#   face           - which face is being calibrated, e.g. "+x".
#   lit_frames     - frames captured with the reference light aimed at it.
#   dark           - the dark offsets from step 1. Needed because the offset
#                    must be removed before the true signal is known.
#   target_reading - what a fully lit face should report, 1000.0 by default.
# RETURNS
#   G_i, this face's gain.
#
# THE ARITHMETIC IS FORMULA 1 SOLVED BACKWARDS. Formula 1 says
# R = (V - D) * G. Calibration knows what R should be, the target, and measures
# V and D, so it rearranges to G = target / (V - D).
#
# A face reading 800 above dark gets gain 1.25; one reading 1200 gets 0.83.
# Under identical light they then both report 1000, which is the entire purpose.
def capture_gain(face: str, lit_frames: Sequence[SensorFrame], dark: dict,
                 target_reading: float = DEFAULT_TARGET_READING) -> float:
    """Solve gain G_i for one face so it reads ``target_reading`` when lit."""
    avg = average_photodiodes(lit_frames)[face]
    signal = avg - dark[face]
    # A zero or negative signal means this face saw no more light than it does
    # in darkness, so dividing by it would give infinity or a negative gain.
    #
    # The message names the likely physical cause rather than the mathematical
    # one, because the person reading it is standing at a bench holding a lamp.
    # This is the single most common mistake in the procedure: aiming at the
    # wrong face, since "+x" is not labelled on the hardware.
    if signal <= 0:
        raise ValueError(
            f"face {face}: dark-subtracted signal is {signal:.2f} (<= 0) - "
            "is the reference light actually aimed at this face?"
        )
    return target_reading / signal


# --- Step 8: the maximum each face can expect ---
#
# PARAMETER
#   bright_frames - frames captured under the brightest expected exposure.
# RETURNS
#   V_max per face, the largest reading observed.
#
# NOTE THIS TAKES THE MAXIMUM, NOT THE AVERAGE, which is the one place the
# pattern differs. V_max is the denominator of formula 5, defining what "fully
# lit" means for that face. Averaging would place it below the true peak, so
# genuinely bright readings would divide out above 1.0 and get clamped, losing
# information at exactly the brightest and most important moments.
def capture_max_illumination(bright_frames: Sequence[SensorFrame]) -> dict:
    """Max raw reading observed per face (brightest expected exposure)."""
    if not bright_frames:
        raise ValueError("no frames captured - check the telemetry stream")
    out = {f: 0.0 for f in FACE_NAMES}
    for fr in bright_frames:
        pd = fr.photodiode_map()
        for f in FACE_NAMES:
            # Keep the larger of the running maximum and this frame's reading.
            out[f] = max(out[f], float(pd[f]))
    return out


# --- The full procedure ---
#
# PARAMETERS
#   collect            - A FUNCTION, passed in. Given a step name such as "dark"
#                        or "gain:+x", it returns the frames captured for that
#                        step.
#
#                        THIS IS WHAT MAKES THE PROCEDURE TESTABLE. In real use
#                        main() supplies a version that prompts an operator and
#                        drains a live queue. A test supplies one that returns
#                        fabricated frames, and the entire eight-step sequence
#                        runs in milliseconds with no hardware, no prompts and a
#                        known correct answer to check against.
#   target_reading     - what a lit face should report.
#   lab_scaling_factor - the bench-lamp to sunlight ratio (see calibration.py).
# RETURNS
#   a complete Calibration, ready to save.
def run_guided_calibration(
    collect: Callable[[str], Sequence[SensorFrame]],
    target_reading: float = DEFAULT_TARGET_READING,
    lab_scaling_factor: float = 0.1,
) -> Calibration:
    """Drive the full dark -> gain -> max procedure and return a Calibration."""
    # Dark FIRST, and the order is not arbitrary: capture_gain needs the dark
    # offsets to isolate the true signal, so this cannot be reordered.
    dark = capture_dark_offsets(collect("dark"))

    gain = {}
    for face in FACE_NAMES:
        # The step name encodes which face, e.g. "gain:+y", so `collect` can
        # print the right instruction. step_prompt below splits it back apart.
        frames = collect(f"gain:{face}")
        gain[face] = capture_gain(face, frames, dark, target_reading)

    max_illum = capture_max_illumination(collect("max"))

    return Calibration(dark=dark, gain=gain, max_illumination=max_illum,
                       lab_scaling_factor=lab_scaling_factor)


# ---------------------------------------------------------------------------
# Live CLI: drains a running ingest queue, prompting the operator at each step.
# ---------------------------------------------------------------------------
# Everything below this line deals with hardware, queues and the human. The
# functions above deal only with numbers.


# PARAMETER
#   step - "dark", "max", or "gain:<face>".
# RETURNS
#   the instruction to show the operator.
#
# THIS FUNCTION EXISTS BECAUSE OF A REAL BUG. It was originally a dict lookup
# with a computed default:
#
#     prompts.get(step, f"...{step.split(':')[1]}...")
#
# which looks reasonable and is not. Python must BUILD the default before it can
# hand it to .get(), even when the key is found, so for "dark" and "max", which
# contain no colon, `step.split(':')[1]` raised IndexError before the lookup
# ever happened (see docs/python-primer.md, section 4).
#
# Rewritten as if/elif, the split only runs on the branch that reaches it. The
# extraction into a named function also made it directly testable, and there is
# now a regression test covering exactly this.
def step_prompt(step: str) -> str:
    """The operator-facing instruction for a given collection step."""
    if step == "dark":
        return "Cover all sensors / turn off all light, then press Enter…"
    if step == "max":
        return "Present the brightest expected exposure to all faces, then press Enter…"
    # Only reached for "gain:<face>", where the colon is guaranteed present.
    # .split(":")[1] takes the part after the colon: "gain:+x" gives "+x".
    face = step.split(":")[1]
    return f"Aim the reference light dead-on at face {face}, then press Enter…"


# --- The stale-frame fix ---
#
# PARAMETER
#   frame_queue - the live queue of raw telemetry strings.
# RETURNS
#   how many frames were discarded, so the operator can see it working.
#
# THE PROBLEM THIS SOLVES, restated because it is the subtlest thing in the
# file. The device never stops transmitting. While the operator moves the lamp
# from +x to -x, perhaps twenty frames arrive showing +x conditions and sit in
# the queue. Sampling for the -x step then reads those first, and the gain
# computed for -x is really a measurement of +x.
#
# Nothing about that failure is visible: the frames are valid, the checksums
# pass, the averages compute. Only the final gains are wrong.
#
# So the queue is emptied at the exact moment the operator presses Enter,
# guaranteeing every sampled frame arrived after the setup was ready.
#
# `while True` with a `return` inside is the idiom for "loop until the exit
# condition", here an empty queue. get_nowait raises immediately rather than
# waiting, which is what makes draining fast.
def _flush_queue(frame_queue: "queue.Queue") -> int:
    """Discard everything currently queued (non-blocking)."""
    dropped = 0
    while True:
        try:
            frame_queue.get_nowait()
            dropped += 1
        except queue.Empty:
            return dropped


# --- Collect n good frames from the live stream ---
#
# PARAMETERS
#   frame_queue - the live queue of raw strings.
#   n           - how many valid frames are wanted.
#   timeout_s   - give up after this long.
# RETURNS
#   a list of decoded SensorFrames, possibly fewer than n if time ran out.
#
# THE TIMEOUT MATTERS. Without it, a disconnected device would leave the tool
# waiting forever with no explanation. With it, the step ends and the operator
# sees "captured 0 frames", which points at the actual problem.
def _drain_live(frame_queue: "queue.Queue", n: int, timeout_s: float = 15.0):
    """Decode up to ``n`` valid frames from a raw-string queue, skipping rejects."""
    from tetralux.telemetry.json_frame import decode_json_frame

    frames = []
    # An absolute deadline computed once, rather than a countdown. Simpler and
    # not subject to drift accumulating across loop passes.
    deadline = time.time() + timeout_s
    # Two exit conditions: enough frames, or out of time.
    while len(frames) < n and time.time() < deadline:
        try:
            raw = frame_queue.get(timeout=0.5)
        except queue.Empty:
            # A quiet half-second. Loop around and re-check the deadline.
            continue
        result = decode_json_frame(raw)
        # Corrupt frames are skipped, not counted. Averaging a corrupt reading
        # into a calibration constant would bake that corruption into every
        # future measurement, so it is worth waiting for clean data.
        if isinstance(result, RejectedFrame):
            continue
        frames.append(result)
    return frames


# --- The interactive entry point ---
#
# PARAMETERS: none; it reads the command line.
# RETURNS: None.
def main() -> None:
    """Interactive CLI: connect to a running ground station and calibrate it."""
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

    # This tool runs its OWN ingest server rather than connecting to a running
    # ground station, so calibration works standalone with only the device
    # powered on.
    if args.serial:
        from tetralux.ingest.serial_reader import SerialReader

        reader = SerialReader(frame_queue.put_nowait, args.serial)
        reader.start()
    else:
        import threading

        from tetralux.ingest.http_server import run_ingest_server

        # kwargs={...} passes arguments by name to the function the thread will
        # run, which is how a threaded call supplies keyword arguments.
        # daemon=True lets the program exit without waiting for it.
        server_thread = threading.Thread(
            target=run_ingest_server,
            kwargs={"on_frame": frame_queue.put_nowait, "port": args.port},
            daemon=True,
        )
        server_thread.start()
        print(f"[calibration] listening on http://0.0.0.0:{args.port}/ingest")

    # THE CALLBACK run_guided_calibration WILL USE. Nested inside main() so it
    # can see frame_queue and args without them being passed in.
    #
    # PARAMETER
    #   step - the step name, e.g. "gain:+z".
    # RETURNS
    #   the frames captured for that step.
    def collect(step: str):
        # input() prints a prompt and WAITS for the operator to press Enter.
        # That pause is the whole synchronisation mechanism between the software
        # and the physical setup. The \n is a blank line for readability.
        input(f"\n[{step}] {step_prompt(step)} ")
        # Discard any backlog from before the operator was ready - otherwise
        # frames still queued from the *previous* step's conditions would be
        # sampled as if they belonged to this one (see _flush_queue docstring).
        #
        # Placed immediately after input() and before sampling: that exact
        # position is what makes it correct.
        stale = _flush_queue(frame_queue)
        if stale:
            print(f"  discarded {stale} stale frame(s) queued before this step")
        print(f"  sampling {args.samples} frames…")
        frames = _drain_live(frame_queue, args.samples)
        # Reporting the count lets the operator notice a short capture, which
        # means the link is struggling and the step should be repeated.
        print(f"  captured {len(frames)} frames")
        return frames

    # Hand the collector to the procedure. Everything above runs from here.
    cal = run_guided_calibration(collect, target_reading=args.target_reading)
    cal.save(args.out)
    print(f"\nSaved calibration to {args.out}")
    # Print the result as well as saving it, so the operator can sanity-check
    # the numbers immediately. Gains far from 1.0, or dark offsets in the
    # hundreds, mean something went wrong and are obvious on sight.
    print(cal.to_json())

    if reader is not None:
        reader.stop()
    # The HTTP server thread needs no cleanup: daemon=True means it disappears
    # when the program exits.


# Only run main() when this file is executed directly, not when imported (see
# groundstation.py for the full explanation of this guard).
if __name__ == "__main__":
    main()
