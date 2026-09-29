"""Serial (USB) telemetry reader (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
The second way to receive telemetry: a USB cable instead of WiFi. Same packets,
same decoder, different transport.

WHY BOTH EXIST. WiFi is how the satellite would really operate, but it adds a
router, an IP address and a network stack between you and the problem. During
bring-up, when nothing works yet and you need to know whether the firmware is
even transmitting, a cable removes all of that. It is also more reliable for
calibration, where dropped packets would corrupt a measurement.

THE HARD PART: SERIAL DOES NOT HAVE MESSAGES. A network request arrives as a
complete unit. A serial port is a raw stream of bytes with no boundaries at all:
read from it and you might get half a packet, or two and a half packets, or
three bytes. The firmware marks the end of each packet with a newline, and the
`_loop` method below is entirely about reassembling whole lines from arbitrary
chunks. That buffering is the reason this file exists rather than being three
lines inline somewhere.

THREADS. Reading a serial port blocks: the code sits and waits for bytes. Doing
that on the main thread would freeze the whole program. So the read loop runs on
a background THREAD, a separate line of execution running at the same time as
the main one. This is the project's alternative to `async` (see
ingest/http_server.py); threads suit a continuous read loop, async suits a
request-response server.

WHERE IT SITS IN THE FLOW
    groundstation.py         creates one of these when given --serial
    telemetry/json_frame.py  decodes the lines this produces
    ingest/monitor.py        counts what arrives

New to Python? Read docs/python-primer.md first.
"""

from __future__ import annotations

# threading: Python's tools for running code in the background.
import threading
from typing import Callable, Optional


class SerialReader:
    """Threaded line reader for a serial telemetry link."""

    # PARAMETERS
    #   on_frame - the per-line callback, exactly the same contract as
    #              http_server.create_ingest_app uses. Because both transports
    #              call the same kind of function, groundstation.py can hand the
    #              identical callback to either and everything downstream is
    #              unchanged.
    #   port     - the device path, such as "/dev/tty.usbmodem14201" on a Mac or
    #              "COM3" on Windows. Found with `ls /dev/tty.*` or in the
    #              Arduino IDE.
    #   baud     - the speed in bits per second. 115200 is the default and MUST
    #              match the firmware's Serial.begin() exactly. A mismatch does
    #              not produce an error; it produces a stream of plausible
    #              garbage, which is why nothing here can detect it.
    # RETURNS
    #   None; a constructor sets the object up.
    def __init__(self, on_frame: Callable[[str], None], port: str,
                 baud: int = 115200) -> None:
        self._on_frame = on_frame
        self._port = port
        self._baud = baud
        # An EVENT is a thread-safe flag: one thread sets it, another checks it.
        # This is how the main thread asks the background loop to finish. A
        # plain boolean would work most of the time and occasionally not, since
        # two threads touching the same variable without coordination can miss
        # each other's writes.
        self._stop = threading.Event()
        # The thread and the port do not exist until start() is called, so both
        # begin as None.
        self._thread: Optional[threading.Thread] = None
        self._serial = None

    # Open the port and launch the background reader.
    #
    # RETURNS
    #   None, and it returns IMMEDIATELY. The reading continues in the
    #   background, which is the whole point.
    def start(self) -> None:
        """Open the port and begin reading in a background thread."""
        # Lazy import: pyserial is an optional dependency (see
        # ingest/http_server.py for the full reasoning).
        import serial  # lazy import (optional dep)

        # timeout=0.5 means a read gives up after half a second and returns
        # whatever it has, possibly nothing. That is what makes stopping
        # possible: without a timeout, a read on a silent port would block
        # forever and never reach the loop's stop check again.
        self._serial = serial.Serial(self._port, self._baud, timeout=0.5)
        self._stop.clear()
        # target=self._loop names the function the thread will run. Note NO
        # brackets: the function itself is passed, not the result of calling it.
        # With brackets, _loop would run right here on the main thread and block
        # forever.
        #
        # daemon=True means Python will not wait for this thread when the
        # program exits. Without it, a forgotten reader would keep the process
        # alive after the user pressed Ctrl-C.
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # The background loop. Internal (leading underscore): never called
    # directly, only by the thread that start() creates.
    def _loop(self) -> None:
        # The reassembly buffer. `b""` is an empty BYTES string, distinct from
        # an empty text string: bytes are raw numbers off the wire, and text is
        # bytes that have been interpreted as characters. Decoding happens only
        # once a complete line is in hand, because a chunk could split a
        # multi-byte character in half.
        buffer = b""
        while not self._stop.is_set():
            try:
                # Read up to 256 bytes. May return fewer, or none if the timeout
                # expires. There is no guarantee this is a whole line, or only
                # one line.
                chunk = self._serial.read(256)
            except Exception:  # port error / disconnect
                # A broad except, unusual in this project and justified here:
                # pyserial raises several different types when a cable is
                # unplugged, and every one means the same thing. `break` exits
                # the loop so the thread ends cleanly rather than spinning on a
                # dead port.
                break
            # Nothing arrived within the timeout. Go around again, which is also
            # what re-checks the stop flag.
            if not chunk:
                continue
            # Append to whatever partial data is already held.
            buffer += chunk
            # REASSEMBLY. `while`, not `if`: one chunk may contain several
            # complete lines, and all of them must be processed before reading
            # more.
            while b"\n" in buffer:
                # split with a limit of 1 cuts at the FIRST newline only, giving
                # the completed line and everything after it. That remainder
                # stays in the buffer as the start of the next line, which is
                # exactly how a packet split across two chunks gets rejoined.
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip()
                # A cheap sanity filter. Arduino sketches print boot messages
                # and debug output on the same port, and only JSON packets start
                # with a brace. Without this, every "Connecting to WiFi..." line
                # would reach the decoder and be logged as a rejected frame,
                # burying real corruption in noise.
                if text.startswith("{"):
                    self._on_frame(text)

    # Ask the background thread to finish and close the port.
    def stop(self) -> None:
        """Stop reading and close the port."""
        # Set the flag. The loop notices on its next pass, within about half a
        # second thanks to the read timeout.
        self._stop.set()
        if self._thread is not None:
            # join() waits for the thread to actually finish. The 1.0 second
            # timeout means a wedged thread cannot hang the program forever;
            # daemon=True ensures it dies with the process regardless.
            self._thread.join(timeout=1.0)
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                # `pass` does nothing. Deliberate here: this is cleanup, and if
                # the port is already gone, because the cable was pulled, the
                # close was going to happen anyway. Complaining about failing to
                # close an already-closed port helps nobody.
                pass
