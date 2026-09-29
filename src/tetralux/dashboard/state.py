"""Dashboard runtime state (Phase 9).

WHAT THIS FILE CONTRIBUTES
--------------------------
Everything the dashboard REMEMBERS lives here: the current mode, the slider
positions, the buffer of recent frames, the background threads, the recording
session. app.py builds the page and handles clicks; this file holds the state
those clicks act on.

Separating them matters because Dash callbacks are stateless. Each one runs,
returns some HTML and forgets everything. Any information that must survive
between clicks has to be held somewhere else, and this is that somewhere.

THE TWO MODES ARE FUNDAMENTALLY DIFFERENT, which shapes the whole file.

VIRTUAL is instantaneous and synchronous. Move a slider, and compute_virtual
runs the entire pipeline right there and returns a record. No threads, no
buffer, no waiting; the answer exists before the callback returns.

REAL is continuous and asynchronous. Frames arrive on their own schedule from
the network, so a background thread pulls them off a queue, processes them, and
appends to a rolling buffer. The page then polls that buffer on a timer. The
data arrives whether or not anyone is looking.

THE LOCK IS THE CONSEQUENCE. Two threads touch the buffer: the processing thread
appends, and the browser's polling reads. A lock ensures they never do so at the
same instant, because reading a list while another thread modifies it can return
corrupted results.

THE SIMULATED DEVICE FEED deserves note. start_sim_device runs the simulator in
a background thread and pushes frames through the REAL path: encoded to JSON,
into the queue, decoded, checksum-verified, processed. It is not a shortcut past
the real code, it is the real code with a synthetic transmitter, which is what
makes it a genuine demonstration of Real mode without hardware.

WHERE IT SITS IN THE FLOW
    dashboard/app.py    reads this on every page refresh
    pipeline.py         the processing this drives
    store/session.py    the recording this gates

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

from tetralux.calibration import Calibration
from tetralux.estimation.estimator import angles_to_vector
from tetralux.frames import RejectedFrame
from tetralux.ingest.monitor import StreamMonitor
from tetralux.ingest.queue import create_frame_queue
from tetralux.pipeline import PipelineContext, make_streaming_context, process
from tetralux.sim.sensors import frame_from_angles
from tetralux.store.session import SessionController
from tetralux.telemetry.json_frame import decode_json_frame, encode_json_frame
from tetralux.thermal.analysis import TemperatureAnalyzer
from tetralux.validation.rolling import burst_metrics


class AppState:
    """All mutable runtime state for one dashboard instance."""

    # PARAMETERS
    #   base_dir     - where recording sessions are written.
    #   online_store - a Firebase store, or None.
    #   buffer_size  - how many recent records to keep in memory. 1500 at about
    #                  10 Hz is roughly the last two and a half minutes, enough
    #                  for the time-series charts without unbounded growth.
    #   rate_hz      - the target frame rate.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, base_dir: str = "data/logs", online_store=None,
                 buffer_size: int = 1500, rate_hz: float = 100.0) -> None:
        # Public settings, read and written directly by app.py's callbacks.
        self.mode = "virtual"
        self.rate_hz = rate_hz
        self.virtual_az = 0.0
        self.virtual_el = 30.0

        self.monitor = StreamMonitor(timeout_s=1.0)
        self.session = SessionController(base_dir, online_store)
        self.stream_ctx = None  # created on start_real
        self.calibration: Optional[Calibration] = None
        self.calibration_path: Optional[str] = None

        # A self-limiting deque again: at 1500 records the oldest drops
        # automatically, so a session left running overnight cannot exhaust
        # memory (see validation/rolling.py).
        self._buffer: deque = deque(maxlen=buffer_size)
        self._queue = create_frame_queue()
        # THE LOCK. Only one thread at a time may hold it, so buffer reads and
        # writes cannot interleave. See its use in _process_loop and latest().
        self._lock = threading.Lock()

        # Two background threads, each with its own stop flag, so the simulated
        # device can be stopped without stopping the processing loop.
        self._proc_thread: Optional[threading.Thread] = None
        self._proc_stop = threading.Event()
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop = threading.Event()

        # Persistent virtual context so temperatures/rolling stats accumulate as
        # the user moves the sliders over time (drift needs successive samples).
        #
        # Kept on the object rather than created per call, deliberately. A fresh
        # context each time would have no history, so thermal drift would be
        # permanently NaN. This one accumulates across slider moves.
        self._virtual_ctx = PipelineContext(thermal_analyzer=TemperatureAnalyzer())
        self._virtual_ts = 0

    # ---------- virtual (instantaneous) ----------
    # PARAMETERS
    #   az, el      - the slider positions in degrees, the true sun direction.
    #   burst_noise - noise level for the repeatability burst below.
    #   n_burst     - how many noisy samples to take for that burst.
    # RETURNS
    #   one GroundStationRecord for this slider position.
    def compute_virtual(self, az: float, el: float, burst_noise: float = 6.0,
                        n_burst: int = 25):
        """One instantaneous pipeline pass for the slider position."""
        # The sliders define the TRUTH, which is what makes angular error
        # computable here and not on real hardware.
        light = angles_to_vector(az, el)
        self._virtual_ts += 100  # advance device time so thermal drift is defined
        # Without advancing the clock, two successive frames would share a
        # timestamp, dt would be zero, and the drift rate would stay NaN forever
        # (see thermal/analysis.py).
        frame = frame_from_angles(az, el, timestamp_ms=self._virtual_ts)
        rec = process(frame, self._virtual_ctx, reference=light)

        # Deterministic burst seed per slider position -> stable metrics (no jitter).
        #
        # THIS IS A REAL UI PROBLEM SOLVED WITH A SEED. Repeatability is measured
        # by taking many noisy samples, which is inherently random. With a fresh
        # random source each time, the displayed number would flicker on every
        # page refresh even with the sliders untouched, making it look broken.
        #
        # Deriving the seed FROM the slider position means the same position
        # always produces the same "random" noise, so the metric is stable while
        # the sliders are still and changes only when they move. `^` is XOR,
        # combining the two angles into one seed; abs() and the +90 keep both
        # inputs positive, since a seed must be non-negative.
        rng = np.random.default_rng(abs(int(az * 1000)) ^ abs(int((el + 90) * 1000)))

        # A NESTED FUNCTION passed to burst_metrics as its sampler (see
        # validation/rolling.py). It sees az, el, rng and light directly.
        #
        # RETURNS one noisy estimate, or None if that sample was too dark.
        def sample():
            f = frame_from_angles(az, el, noise_std=burst_noise, rng=rng)
            # A FRESH PipelineContext per sample, deliberately: each is an
            # independent measurement, and sharing history between them would
            # let the rolling validator smooth away the very scatter being
            # measured.
            r = process(f, PipelineContext(), reference=light)
            return np.asarray(r.sun_vector, dtype=float) if r.sun_vector else None

        bm = burst_metrics(sample, light, n=n_burst)
        # Overwrite the record's bias and repeatability with the burst results.
        # The single frame above cannot supply them, since one sample has no
        # spread; the burst is what makes those two fields meaningful in
        # Virtual mode.
        rec.bias_deg = bm["bias_deg"]
        rec.repeatability_deg = bm["repeatability_deg"]
        return rec

    # ---------- real (streaming) ----------
    # PARAMETER
    #   raw - one raw telemetry line.
    # RETURNS
    #   None.
    #
    # The single entry point for incoming data, whatever its source: HTTP,
    # serial, or the simulated device. It only enqueues, so a slow pipeline can
    # never block whatever is receiving.
    def feed_raw(self, raw: str) -> None:
        """Ingest sink used by HTTP/serial/sim-device (enqueue-only)."""
        try:
            self._queue.put_nowait(raw)
        except queue.Full:
            # `pass` does nothing, and here that is the right call. A full queue
            # means processing has fallen behind. Blocking would stall the
            # receiver and lose data at the network level instead; dropping the
            # newest frame keeps everything else running. The monitor's counters
            # still reveal that frames went missing.
            pass

    # Start the background processing loop.
    #
    # IDEMPOTENT: calling it twice does nothing the second time. Necessary
    # because the dashboard has several buttons that need the loop running, and
    # each can be clicked at any moment.
    def start_real(self) -> None:
        """Start the processing loop (idempotent)."""
        if self._proc_thread is not None and self._proc_thread.is_alive():
            return
        # A streaming context, so bias, repeatability and thermal drift are
        # populated (see pipeline.py).
        self.stream_ctx = make_streaming_context(monitor=self.monitor,
                                                 calibration=self.calibration)
        self._proc_stop.clear()
        self._proc_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._proc_thread.start()

    # PARAMETER
    #   path - a calibration.json from calibration_tool.py.
    # RETURNS
    #   the loaded Calibration.
    #
    # Rebuilds the streaming context so the new values take effect on the next
    # frame, WITHOUT restarting the dashboard. That matters during bring-up: run
    # the calibration tool, load the file, and see the improvement immediately.
    # Note the rebuild also resets the rolling validator, which is correct, since
    # errors measured under the old calibration no longer describe the system.
    def load_calibration(self, path: str) -> Calibration:
        """Load a calibration file and apply it to the real-mode stream context."""
        cal = Calibration.load(path)
        self.calibration = cal
        self.calibration_path = path
        self.stream_ctx = make_streaming_context(monitor=self.monitor, calibration=cal)
        return cal

    # The background consumer. Structurally identical to groundstation.py's
    # loop, which is deliberate: both are the real path, so both behave the
    # same.
    def _process_loop(self) -> None:
        while not self._proc_stop.is_set():
            try:
                # The timeout is what allows shutdown; without it this would
                # block forever on a silent link (see ingest/serial_reader.py).
                raw = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            result = decode_json_frame(raw, source="real")
            if isinstance(result, RejectedFrame):
                self.monitor.record_rejected(result)
                continue
            self.monitor.record_accepted(result)
            rec = process(result, self.stream_ctx)
            # THE LOCK IN USE. `with` acquires it, appends, and releases it even
            # if something goes wrong inside. The block is kept as short as
            # possible, holding it only for the append and not for the
            # processing above, so the browser's reads are never made to wait on
            # the pipeline.
            with self._lock:
                self._buffer.append(rec)
            self.session.record(rec)  # no-op unless a session is active

    # PARAMETERS
    #   rate_hz   - frames per second to generate, or None for the default.
    #   noise_std - how noisy to make them.
    # RETURNS
    #   None.
    #
    # Demonstrates Real mode with no hardware attached. Note it calls
    # start_real() FIRST: there is no point generating frames with nothing
    # consuming them.
    def start_sim_device(self, rate_hz: Optional[float] = None,
                         noise_std: float = 6.0) -> None:
        """Feed synthesized frames into the ingest queue, as a real device would."""
        self.start_real()
        if self._sim_thread is not None and self._sim_thread.is_alive():
            return
        self._sim_stop.clear()
        rate = min(rate_hz or self.rate_hz, 30.0)  # cap for a smooth thread cadence
        # The cap exists because time.sleep is not precise enough to pace a
        # thread reliably above about 30 Hz; asking for 100 would produce
        # uneven timing rather than a faster stream.
        self._sim_thread = threading.Thread(
            # args=(...) passes positional arguments to the threaded function.
            target=self._sim_loop, args=(rate, noise_std), daemon=True)
        self._sim_thread.start()

    # The synthetic transmitter.
    def _sim_loop(self, rate: float, noise_std: float) -> None:
        dt = 1.0 / rate
        # A FIXED seed, so a demo looks the same every time it is run.
        rng = np.random.default_rng(0)
        seq = 0
        t0 = time.time()
        while not self._sim_stop.is_set():
            elapsed = time.time() - t0
            # A MOVING sun rather than a static one, which is what makes the
            # demo worth watching: the vector rotates and the time-series charts
            # show real variation. `% 360.0` wraps around after a full circle.
            az = (elapsed * 20.0) % 360.0   # sun sweeps 20 deg/s
            frame = frame_from_angles(az, 30.0, seq=seq, timestamp_ms=int(elapsed * 1000),
                                      noise_std=noise_std, rng=rng)
            # ENCODED TO JSON, then fed in as raw text. This is the key line:
            # the frame goes through the real wire format and will be decoded
            # and checksum-verified on the way back in, exactly as hardware
            # data would be. Handing the SensorFrame over directly would bypass
            # the codec and prove far less.
            self.feed_raw(encode_json_frame(frame))
            # An incrementing sequence number, so the monitor's gap detection
            # sees a well-formed stream.
            seq += 1
            time.sleep(dt)

    def stop_sim_device(self) -> None:
        self._sim_stop.set()
        if self._sim_thread is not None:
            # Wait for it to actually finish, with a timeout so a wedged thread
            # cannot hang the dashboard.
            self._sim_thread.join(timeout=1.0)
        # Cleared so start_sim_device's is_alive check sees a clean slate.
        self._sim_thread = None

    # Stops the simulated device FIRST, then the processor. That order matters:
    # stopping the consumer first would leave the producer filling a queue
    # nothing is draining.
    def stop_real(self) -> None:
        self.stop_sim_device()
        self._proc_stop.set()
        if self._proc_thread is not None:
            self._proc_thread.join(timeout=1.0)
        self._proc_thread = None

    # ---------- readers ----------
    # Called from the browser's polling thread, which is why the lock is needed:
    # the processing thread may be appending at the same moment.
    #
    # RETURNS the most recent record, or None if none has arrived.
    def latest(self):
        with self._lock:
            # [-1] is the last item. The `if self._buffer` guard avoids
            # IndexError on an empty buffer, which is the normal state before
            # the first frame.
            return self._buffer[-1] if self._buffer else None

    # PARAMETER
    #   n - how many recent records to return.
    # RETURNS
    #   up to n records, oldest first, for the time-series charts.
    def history(self, n: int = 400):
        with self._lock:
            # list(...) COPIES inside the lock, so the caller works on a
            # snapshot that cannot change underneath it. Returning the deque
            # itself would hand out a live object the processing thread is still
            # modifying. [-n:] then takes the last n items.
            return list(self._buffer)[-n:]

    def connection(self) -> dict:
        return self.monitor.stats()

    # A property, so app.py can write `state.sim_running` as a plain fact rather
    # than calling a method.
    @property
    def sim_running(self) -> bool:
        # is_alive() asks the thread itself, rather than trusting a flag that
        # could be stale if the thread died unexpectedly.
        return self._sim_thread is not None and self._sim_thread.is_alive()
