"""Tests for the HTTP ingest endpoint (Phase 6). Needs the `ingest` extra."""

import pytest


def test_ingest_enqueues_raw_body():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from tetralux.ingest.http_server import create_ingest_app
    from tetralux.ingest.monitor import StreamMonitor

    sink = []
    monitor = StreamMonitor()
    client = TestClient(create_ingest_app(sink.append, monitor=monitor))

    payload = '{"seq":1,"ts":2,"pd":[0,0,0,0,0,0],"flags":0,"chk":0}'
    resp = client.post("/ingest", content=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert sink == [payload]  # enqueue-only, raw body preserved

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["stream"]["total_received"] == 0  # ingest does no parsing
