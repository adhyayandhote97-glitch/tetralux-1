"""HTTP ingest endpoint (Phase 6).

WHAT THIS FILE CONTRIBUTES
--------------------------
This is how the satellite talks to the ground station over WiFi. It starts a
small web server with two addresses:

    POST /ingest   the Arduino sends one telemetry packet here, about ten times
                   a second
    GET  /health   a human or a monitoring script asks "is the link alive?"

It is the only file in the project that uses `async def`, so this is where that
concept is worth understanding.

WHY async HERE AND NOWHERE ELSE. Ordinary Python does one thing at a time: if a
line takes two seconds, everything waits two seconds. A web server cannot work
that way. While waiting for one packet's bytes to finish arriving over the
network, it must stay free to accept the next connection. `async def` marks a
function that can PAUSE at an `await` and let other work run while it waits, and
`await` marks the point where that pause happens.

The rest of the project has no reason for this. Concurrency elsewhere uses
threads instead (ingest/serial_reader.py, dashboard/state.py), which suit
long-running background loops better than a request-response server does.

TWO DESIGN CHOICES WORTH READING BEFORE EDITING. The missing future import is
explained immediately below, and the lazy imports inside the functions are
explained at their first use. Both look like something to tidy up, and both
would break things if tidied.

WHERE IT SITS IN THE FLOW
    groundstation.py         starts this server and supplies the on_frame callback
    telemetry/json_frame.py  decodes the text this receives
    ingest/monitor.py        supplies the link statistics /health reports

New to Python? Read docs/python-primer.md first.
"""

# NOTE: deliberately no `from __future__ import annotations` here - FastAPI must
# see the real ``Request`` class (a lazy local import) to treat it specially;
# stringized annotations would resolve against module globals and fail.
#
# THE BUG THIS PREVENTS, because the note above is terse and the failure was
# genuinely confusing. That future import makes Python store every type hint as
# TEXT instead of as the actual class. Most tools do not care. FastAPI does: it
# READS the hints at runtime to decide what each parameter is. With the import
# on, it saw the string "Request", tried to look that name up among this
# module's globals, did not find it (because Request is imported inside the
# function, not at the top), and fell back to assuming it was a URL query
# parameter. Every packet the Arduino posted came back 422 Unprocessable Entity.
#
# Nothing about the error pointed at an import line. Leave it out.

from typing import Callable


# --- Build the web application ---
#
# PARAMETERS
#   on_frame - A FUNCTION, passed in as a value. Called with the raw text of
#              each packet that arrives. Callable[[str], None] is the hint:
#              takes one string, returns nothing.
#
#              This is a CALLBACK, and it is what keeps this file focused. The
#              server's only job is receiving bytes; it knows nothing about
#              checksums, estimation or logging. groundstation.py passes in a
#              function that does all that. So this server can be tested with a
#              function that just collects strings in a list, and reused
#              anywhere without dragging the pipeline along.
#   monitor  - a StreamMonitor for link statistics, or None. Optional because
#              the server works fine without one; /health simply reports less.
# RETURNS
#   a configured FastAPI application, not yet running.
#
# Returning the app rather than starting it lets tests exercise the endpoints in
# memory, with no port opened and no network involved.
def create_ingest_app(on_frame: Callable[[str], None], monitor=None):
    """Build the ingest FastAPI app."""
    # A LAZY IMPORT: inside the function rather than at the top of the file.
    #
    # FastAPI is an optional dependency, installed only with the `ingest` extra.
    # At the top of the file, this import would run whenever anything in the
    # project imported this module, so someone who only wanted the estimator
    # would hit ImportError for a web framework they never asked for. Here it
    # runs only when someone actually starts the server, which is the only
    # moment FastAPI is genuinely required.
    from fastapi import FastAPI, Request  # lazy import (optional dep)

    app = FastAPI(title="Tetralux-1 Ingest", version="1.0")

    # A DECORATOR (primer 12): the `@` line modifies the function beneath it.
    # This one registers `ingest` as the handler for HTTP POST requests to the
    # /ingest path. The function is never called by name anywhere in this
    # project; FastAPI calls it when a request arrives.
    #
    # POST rather than GET because the satellite is SENDING data. GET is for
    # retrieving, POST for submitting, and a GET carries its data in the URL,
    # where a full telemetry packet does not belong.
    @app.post("/ingest")
    # `async def` (see the file header). This handler can pause while the
    # request body arrives, so the server keeps accepting other packets
    # meanwhile.
    #
    # PARAMETER
    #   request - the incoming HTTP request. FastAPI supplies it automatically
    #             because of the `: Request` type hint, which is exactly the
    #             hint the missing future import protects.
    async def ingest(request: Request):
        # `await` pauses here until the body has fully arrived, releasing the
        # server to handle other work in the meantime. Without await this would
        # return an unfinished placeholder rather than the actual bytes.
        body = await request.body()
        # Hand the raw text to the callback. "replace" substitutes a placeholder
        # for any undecodable byte instead of raising, so a corrupted packet
        # still reaches the decoder, which will reject it properly on its
        # checksum rather than crashing the server here.
        on_frame(body.decode("utf-8", "replace"))
        # FastAPI converts this dict into a JSON response. The satellite does
        # not need a detailed reply, only confirmation that the packet landed.
        return {"ok": True}

    # GET, because this one RETRIEVES information rather than submitting any.
    @app.get("/health")
    # No parameters: this handler needs nothing from the request. Still `async
    # def` for consistency with FastAPI's model, though it never awaits.
    async def health():
        # `monitor.stats() if monitor else None` guards the optional monitor.
        # Useful for confirming the server is up before the satellite is
        # powered, and for watching packet rate during a session.
        return {"status": "ok", "stream": monitor.stats() if monitor else None}

    # Return the app itself. The two handlers above are attached to it, so they
    # travel with it even though nothing here holds a reference to them by name.
    return app


# --- Actually run the server ---
#
# PARAMETERS
#   on_frame - the same per-packet callback.
#   host     - which network interface to listen on. "0.0.0.0" means ALL of
#              them, which is what allows the Arduino to connect from elsewhere
#              on the WiFi network. "127.0.0.1" would accept only connections
#              from this machine, which would make the server useless here.
#   port     - the TCP port, 8000 by default. The firmware's secrets.h must
#              point at the same number.
#   monitor  - optional StreamMonitor.
# RETURNS
#   None, and only when the server stops. "Blocking" in the docstring means this
#   call does not return while the server runs, so groundstation.py runs it on
#   its own thread.
def run_ingest_server(on_frame: Callable[[str], None], host: str = "0.0.0.0",
                      port: int = 8000, monitor=None) -> None:
    """Blocking helper: serve the ingest app with uvicorn (real deployment)."""
    # Lazy again, for the same optional-dependency reason. uvicorn is the actual
    # web server; FastAPI only describes what the endpoints do, and something
    # has to open the socket and manage connections.
    import uvicorn  # lazy import

    # log_level="warning" silences uvicorn's per-request logging. At ten packets
    # a second it would print ten lines a second forever, burying the
    # ground station's own output. Warnings and errors still appear.
    uvicorn.run(create_ingest_app(on_frame, monitor), host=host, port=port,
                log_level="warning")
