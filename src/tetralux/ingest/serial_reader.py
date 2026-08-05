"""Serial (USB) telemetry reader (Phase 6)."""

from __future__ import annotations

import threading
from typing import Callable, Optional


class SerialReader:
    """Threaded line reader for a serial telemetry link."""

    def __init__(self, on_frame: Callable[[str], None], port: str,
                 baud: int = 115200) -> None:
        self._on_frame = on_frame
        self._port = port
        self._baud = baud
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial = None

    def start(self) -> None:
        """Open the port and begin reading in a background thread."""
        import serial  # lazy import (optional dep)

        self._serial = serial.Serial(self._port, self._baud, timeout=0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = self._serial.read(256)
            except Exception:  # port error / disconnect
                break
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("{"):
                    self._on_frame(text)

    def stop(self) -> None:
        """Stop reading and close the port."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
