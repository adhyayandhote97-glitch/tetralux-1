"""HTTP ingest endpoint (Phase 6).

A minimal FastAPI app exposing ``POST /ingest`` that matches the firmware's WiFi
path. The handler does **no parsing** — it hands the raw body to a sink callable
(enqueue-only, for backpressure safety); decoding happens downstream in the
processing loop. ``GET /health`` returns monitor stats.

Requires the ``ingest`` extra (fastapi). Imported lazily so the core stays light.
"""

# NOTE: deliberately no `from __future__ import annotations` here — FastAPI must
# see the real ``Request`` class (a lazy local import) to treat it specially;
# stringized annotations would resolve against module globals and fail.

from typing import Callable, Optional


def create_ingest_app(on_frame: Callable[[str], None], monitor=None):
    """Build the ingest FastAPI app.

    Args:
        on_frame: Called with each raw request body (str). Typically
            ``queue.put_nowait``; a list ``.append`` works for tests.
        monitor: Optional :class:`StreamMonitor` for the health endpoint.

    Returns:
        A configured ``fastapi.FastAPI`` instance.
    """
    from fastapi import FastAPI, Request  # lazy import (optional dep)

    app = FastAPI(title="Tetralux-1 Ingest", version="1.0")

    @app.post("/ingest")
    async def ingest(request: Request):
        body = await request.body()
        on_frame(body.decode("utf-8", "replace"))
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok", "stream": monitor.stats() if monitor else None}

    return app


def run_ingest_server(on_frame: Callable[[str], None], host: str = "0.0.0.0",
                      port: int = 8000, monitor=None) -> None:
    """Blocking helper: serve the ingest app with uvicorn (real deployment)."""
    import uvicorn  # lazy import

    uvicorn.run(create_ingest_app(on_frame, monitor), host=host, port=port,
                log_level="warning")
