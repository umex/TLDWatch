"""WebSocket progress tests -- plan 04-03.

Uses ``starlette.testclient.TestClient.websocket_connect`` (httpx CANNOT
do WebSocket -- Pitfall 6 from 04-RESEARCH.md). Tests drive the worker
manually via ``settings.run_worker=False`` (the ``tmp_data_dir`` fixture
already writes that).

These are the RED-gate tests for plan 04-03 Task 2 (the WS endpoint +
SubscriberRegistry + snapshot from progress.json -- Fix 9). Task 2
turns them GREEN.

Fix 9 contract: the on-connect snapshot is sourced from the job row +
manifest AND 04-01's ``progress.json`` (so a reconnecting client mid-
transcription sees a nonzero percent instead of 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def ws_client(tmp_data_dir: Path) -> "object":  # noqa: ANN202
    """A sync Starlette ``TestClient`` that runs the app lifespan.

    httpx's ``AsyncClient`` cannot do WebSocket; the Starlette TestClient
    drives the ASGI app via a portal so ``websocket_connect`` works. The
    lifespan runs on entry (so ``app.state.bus`` / ``app.state.subscribers``
    / ``app.state.settings`` / ``app.state.session_factory`` are set) and
    tears down on exit.
    """
    from starlette.testclient import TestClient

    from app.main import app

    # base_url=http://localhost so HTTP POST /jobs passes the
    # TrustedHostMiddleware (allow-list of localhost / 127.0.0.1 /
    # 0.0.0.0). The Starlette TestClient's websocket_connect does NOT
    # carry base_url's host into the WS handshake Host header (it sends
    # "testserver"), so the WS tests pass an explicit host header via
    # the ``_ws`` helper below.
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def _ws(ws_client: "object", url: str) -> "object":
    """Wrap ``websocket_connect`` with a localhost Host header.

    The TrustedHostMiddleware rejects the TestClient's default
    "testserver" Host on the WS handshake; passing the header explicitly
    makes the middleware accept the upgrade. HTTP requests already use
    base_url=http://localhost so they do not need this.
    """
    return ws_client.websocket_connect(url, headers={"host": "localhost"})


# --- Helpers ----------------------------------------------------------------


def _job_dir(job_id: str) -> Path:
    from app.main import app
    from app.storage.fs import job_dir

    return job_dir(app.state.settings, job_id)


def _write_progress_json(job_id: str, payload: dict) -> None:
    """Write a progress.json snapshot into the job dir (Fix 9 source)."""
    p = _job_dir(job_id) / "progress.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _make_job(ws_client: "object") -> str:
    r = ws_client.post("/jobs", json={})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- Tests (RED until Task 2 lands routes_ws.py) ----------------------------


def test_snapshot_on_connect(ws_client: "object") -> None:
    """The first WS message is a snapshot sourced from job row + progress.json.

    Fix 9 -- a reconnecting client mid-transcription sees a NONZERO percent
    because the snapshot reads 04-01's ``progress.json`` (not just the DB
    row, which has no percent field).
    """
    job_id = _make_job(ws_client)
    _write_progress_json(
        job_id,
        {
            "chunks_done": 5,
            "chunks_total": 10,
            "percent": 50.0,
            "eta_s": 120.5,
            "updated_at": "2026-06-22T00:00:00",
        },
    )
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["job_id"] == job_id
    assert msg["percent"] == 50.0
    assert msg["eta"] == 120.5
    assert "stage" in msg
    assert "status" in msg


def test_snapshot_queued_job_no_progress_json(ws_client: "object") -> None:
    """A queued job with no progress.json yields a snapshot with percent=0, eta=None."""
    job_id = _make_job(ws_client)
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    assert msg["job_id"] == job_id
    assert msg["percent"] == 0
    assert msg["eta"] is None


def test_live_progress_events(ws_client: "object") -> None:
    """Live progress events from the EventBus are relayed to the WS client as-is."""
    from app.main import app

    job_id = _make_job(ws_client)
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        # Consume the snapshot first (always sent on connect).
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        # Publish a progress event to the bus (04-01 schema: percent + eta_s).
        app.state.bus.publish(
            job_id,
            {
                "type": "progress",
                "chunks_done": 3,
                "chunks_total": 10,
                "percent": 30.0,
                "eta_s": 120.5,
                "chunk_start_s": 0.0,
            },
        )
        msg = ws.receive_json()
    assert msg["type"] == "progress"
    assert msg["chunks_done"] == 3
    assert msg["chunks_total"] == 10
    assert msg["percent"] == 30.0
    assert msg["eta_s"] == 120.5


def test_done_event_relay(ws_client: "object") -> None:
    """A ``done`` event published to the bus is relayed verbatim."""
    from app.main import app

    job_id = _make_job(ws_client)
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        ws.receive_json()  # snapshot
        app.state.bus.publish(job_id, {"type": "done"})
        msg = ws.receive_json()
    assert msg["type"] == "done"


def test_subscriber_cap(ws_client: "object") -> None:
    """A 3rd subscriber when cap=2 is rejected with an error close (T-04-02)."""
    from app.main import app

    app.state.settings.ws_subscriber_cap = 2
    try:
        job_id = _make_job(ws_client)
        with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws1:
            assert ws1.receive_json()["type"] == "snapshot"
            with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws2:
                assert ws2.receive_json()["type"] == "snapshot"
                # 3rd subscriber: rejected with an error message.
                with _ws(ws_client, 
                    f"/ws/jobs/{job_id}/events"
                ) as ws3:
                    msg = ws3.receive_json()
                assert msg["type"] == "error"
                assert msg["code"] == "subscriber_cap"
    finally:
        app.state.settings.ws_subscriber_cap = 16


def test_disconnect_removes_subscriber(ws_client: "object") -> None:
    """After the WS closes, the SubscriberRegistry count returns to 0."""
    from app.main import app

    job_id = _make_job(ws_client)
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        ws.receive_json()  # snapshot
    # The finally block in the WS handler removes the subscriber on close.
    assert app.state.subscribers.count(job_id) == 0


def test_eta_null_below_threshold(ws_client: "object") -> None:
    """A progress event with eta_s=null is relayed faithfully (04-01 hides ETA < 2 chunks).

    04-03 does NOT re-compute ETA -- it relays what the bus publishes. This
    test verifies the relay carries the explicit ``eta_s`` key (null or
    float), not a missing key.
    """
    from app.main import app

    job_id = _make_job(ws_client)
    with _ws(ws_client, f"/ws/jobs/{job_id}/events") as ws:
        ws.receive_json()  # snapshot
        app.state.bus.publish(
            job_id,
            {
                "type": "progress",
                "chunks_done": 1,
                "chunks_total": 10,
                "percent": 10.0,
                "eta_s": None,
                "chunk_start_s": 0.0,
            },
        )
        msg = ws.receive_json()
    assert msg["type"] == "progress"
    assert "eta_s" in msg  # explicit key, not missing
    assert msg["eta_s"] is None


def test_snapshot_not_found(ws_client: "object") -> None:
    """A WS connect to a non-existent job sends an error and closes (1008)."""
    with _ws(ws_client, 
        "/ws/jobs/00000000-0000-0000-0000-000000000000/events"
    ) as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "not_found"