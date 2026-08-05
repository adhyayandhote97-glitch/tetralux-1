"""Dashboard runtime state (Phase 9)."""

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

    def __init__(self, base_dir: str = "data/logs", online_store=None,
                 buffer_size: int = 1500, rate_hz: float = 100.0) -> None:
        self.mode = "virtual"
        self.rate_hz = rate_hz
        self.virtual_az = 0.0
        self.virtual_el = 30.0

        self.monitor = StreamMonitor(timeout_s=1.0)
        self.session = SessionController(base_dir, online_store)
        self.stream_ctx = None  # created on start_real
        self.calibration: Optional[Calibration] = None
        self.calibration_path: Optional[str] = None

        self._buffer: deque = deque(maxlen=buffer_size)
        self._queue = create_frame_queue()
        self._lock = threading.Lock()

        self._proc_thread: Optional[threading.Thread] = None
        self._proc_stop = threading.Event()
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop = threading.Event()

        # Persistent virtual context so temperatures/rolling stats accumulate as
        # the user moves the sliders over time (drift needs successive samples).
        self._virtual_ctx = PipelineContext(thermal_analyzer=TemperatureAnalyzer())
        self._virtual_ts = 0

    # ---------- virtual (instantaneous) ----------
    def compute_virtual(self, az: float, el: float, burst_noise: float = 6.0,
                        n_burst: int = 25):
        """One instantaneous pipeline pass for the slider position."""
        light = angles_to_vector(az, el)
        self._virtual_ts += 100  # advance device time so thermal drift is defined
        frame = frame_from_angles(az, el, timestamp_ms=self._virtual_ts)
        rec = process(frame, self._virtual_ctx, reference=light)
        # Deterministic burst seed per slider position -> stable metrics (no jitter).
        rng = np.random.default_rng(abs(int(az * 1000)) ^ abs(int((el + 90) * 1000)))

        def sample():
            f = frame_from_angles(az, el, noise_std=burst_noise, rng=rng)
            r = process(f, PipelineContext(), reference=light)
            return np.asarray(r.sun_vector, dtype=float) if r.sun_vector else None

        bm = burst_metrics(sample, light, n=n_burst)
        rec.bias_deg = bm["bias_deg"]
        rec.repeatability_deg = bm["repeatability_deg"]
        return rec

    # ---------- real (streaming) ----------
    def feed_raw(self, raw: str) -> None:
        """Ingest sink used by HTTP/serial/sim-device (enqueue-only)."""
        try:
            self._queue.put_nowait(raw)
        except queue.Full:
            pass

    def start_real(self) -> None:
        """Start the processing loop (idempotent)."""
        if self._proc_thread is not None and self._proc_thread.is_alive():
            return
        self.stream_ctx = make_streaming_context(monitor=self.monitor,
                                                 calibration=self.calibration)
        self._proc_stop.clear()
        self._proc_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._proc_thread.start()

    def load_calibration(self, path: str) -> Calibration:
        """Load a calibration file and apply it to the real-mode stream context."""
        cal = Calibration.load(path)
        self.calibration = cal
        self.calibration_path = path
        self.stream_ctx = make_streaming_context(monitor=self.monitor, calibration=cal)
        return cal

    def _process_loop(self) -> None:
        while not self._proc_stop.is_set():
            try:
                raw = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            result = decode_json_frame(raw, source="real")
            if isinstance(result, RejectedFrame):
                self.monitor.record_rejected(result)
                continue
            self.monitor.record_accepted(result)
            rec = process(result, self.stream_ctx)
            with self._lock:
                self._buffer.append(rec)
            self.session.record(rec)  # no-op unless a session is active

    def start_sim_device(self, rate_hz: Optional[float] = None,
                         noise_std: float = 6.0) -> None:
        """Feed synthesized frames into the ingest queue, as a real device would."""
        self.start_real()
        if self._sim_thread is not None and self._sim_thread.is_alive():
            return
        self._sim_stop.clear()
        rate = min(rate_hz or self.rate_hz, 30.0)  # cap for a smooth thread cadence
        self._sim_thread = threading.Thread(
            target=self._sim_loop, args=(rate, noise_std), daemon=True)
        self._sim_thread.start()

    def _sim_loop(self, rate: float, noise_std: float) -> None:
        dt = 1.0 / rate
        rng = np.random.default_rng(0)
        seq = 0
        t0 = time.time()
        while not self._sim_stop.is_set():
            elapsed = time.time() - t0
            az = (elapsed * 20.0) % 360.0   # sun sweeps 20 deg/s
            frame = frame_from_angles(az, 30.0, seq=seq, timestamp_ms=int(elapsed * 1000),
                                      noise_std=noise_std, rng=rng)
            self.feed_raw(encode_json_frame(frame))
            seq += 1
            time.sleep(dt)

    def stop_sim_device(self) -> None:
        self._sim_stop.set()
        if self._sim_thread is not None:
            self._sim_thread.join(timeout=1.0)
        self._sim_thread = None

    def stop_real(self) -> None:
        self.stop_sim_device()
        self._proc_stop.set()
        if self._proc_thread is not None:
            self._proc_thread.join(timeout=1.0)
        self._proc_thread = None

    # ---------- readers ----------
    def latest(self):
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def history(self, n: int = 400):
        with self._lock:
            return list(self._buffer)[-n:]

    def connection(self) -> dict:
        return self.monitor.stats()

    @property
    def sim_running(self) -> bool:
        return self._sim_thread is not None and self._sim_thread.is_alive()
