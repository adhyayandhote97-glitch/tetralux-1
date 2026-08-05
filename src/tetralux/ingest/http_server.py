"""HTTP ingest endpoint (Phase 6)."""

# NOTE: deliberately no `from __future__ import annotations` here - FastAPI must
# see the real ``Request`` class (a lazy local import) to treat it specially;
# stringized annotations would resolve against module globals and fail.

from typing import Callable


def create_ingest_app(on_frame: Callable[[str], None], monitor=None):
    """Build the ingest FastAPI app."""
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
