"""WebSocket progress endpoint -- plan 04-03.

Per-job WebSocket endpoint ``/ws/jobs/{job_id}/events`` (D-08) that:

1. On connect, sends a STATE SNAPSHOT first (before subscribing to the
   EventBus). The snapshot is sourced from the job row (``get_job``),
   the manifest (``read_manifest``), AND 04-01's ``progress.json``
   (Fix 9 -- the key change: a reconnecting client mid-transcription
   sees a NONZERO percent instead of 0, because the DB row has no
   percent field but progress.json carries the last-published
   ``percent`` / ``eta_s`` from the orchestrator).
2. Rejects a 3rd+ subscriber beyond ``settings.ws_subscriber_cap``
   (T-04-02 DoS guard) with an error close (code 1008).
3. Subscribes to the 04-01 EventBus (``app.state.bus``) and relays live
   events (``stage_changed``, ``progress`` with ``percent`` + ``eta_s``,
   ``done``, ``failed``, ``cancelled``) as-is. 04-03 does NOT re-compute
   ETA, does NOT re-enrich, does NOT transform the event types -- the
   orchestrator already publishes enriched events; 04-03 just relays.
4. On disconnect, removes the subscriber from the registry AND the bus
   so neither leaks.

The :class:`SubscriberRegistry` is a class on ``app.state.subscribers``
(Codex MEDIUM -- NOT a module-level dict) so tests and app instances are
isolated. The registry caps per-job subscribers (T-04-02).

IMPORTANT -- do NOT duplicate 04-01's work:

- 04-01's orchestrator computes ETA + publishes progress events with
  ``percent`` + ``eta_s`` (hiding ETA until ``chunks_done >= 2``).
  04-03 RELAYS these. No ETA computation, no ETA sample threshold, and
  no progress-emit interval config live in this module -- 04-01 owns all
  three.
- 04-01's EventBus already has ``Queue(maxsize=32)`` + drop-oldest.
  04-03 does NOT re-implement backpressure.
- 04-01 writes ``progress.json``. 04-03 READS it for the snapshot. No
  writes here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.jobs.manifest import read_manifest
from app.jobs.progress import EventBus
from app.jobs.service import get_job
from app.storage.fs import job_dir

_log = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


class SubscriberRegistry:
    """Per-job WebSocket subscriber registry (Codex MEDIUM -- class on app.state).

    NOT a module-level dict -- a per-app instance so tests and app
    instances are isolated. The registry caps per-job subscribers at
    ``ws_subscriber_cap`` (T-04-02 DoS guard): extra subscribers are
    rejected by ``add`` returning False (the WS handler sends an error
    close).

    Methods are sync (called from the WS handler in the asyncio loop).
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}

    def add(self, job_id: str, ws: WebSocket, cap: int) -> bool:
        """Register ``ws`` as a subscriber for ``job_id``.

        Returns False if adding would exceed ``cap`` (the caller sends an
        error close). Returns True on success. Idempotent on the cap
        check: a re-add of an already-registered ws is a no-op success
        (defensive -- the connect path only calls this once per ws).
        """
        subs = self._subs.setdefault(job_id, set())
        if ws not in subs and len(subs) >= cap:
            return False
        subs.add(ws)
        return True

    def remove(self, job_id: str, ws: WebSocket) -> None:
        """Idempotently remove ``ws`` from ``job_id``'s subscribers.

        ``set.discard`` is idempotent (safe to call twice). The empty
        set is deleted from the registry so the registry does not grow
        unboundedly with finished jobs.
        """
        subs = self._subs.get(job_id)
        if subs is None:
            return
        subs.discard(ws)
        if not subs:
            self._subs.pop(job_id, None)

    def count(self, job_id: str) -> int:
        """Return the current subscriber count for ``job_id`` (test hook)."""
        return len(self._subs.get(job_id, set()))


def _read_progress_snapshot(settings: Any, job_id: str) -> tuple[float, float | None]:
    """Read percent + eta from 04-01's ``progress.json`` (Fix 9).

    Returns ``(0.0, None)`` if the file does not exist (a queued job
    that has not started transcribing has no progress.json yet). The
    orchestrator writes this file atomically with ``chunks_done``,
    ``chunks_total``, ``percent``, ``eta_s``, ``updated_at``.
    """
    p = job_dir(settings, job_id) / "progress.json"
    if not p.exists():
        return 0.0, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        _log.warning("progress.json parse failed for %s", job_id, exc_info=True)
        return 0.0, None
    percent = float(data.get("percent", 0.0))
    eta_s = data.get("eta_s")
    if eta_s is not None:
        try:
            eta_s = float(eta_s)
        except (TypeError, ValueError):
            eta_s = None
    return percent, eta_s


@router.websocket("/ws/jobs/{job_id}/events")
async def job_events(websocket: WebSocket) -> None:
    """Stream per-job progress events to the connected WS client.

    On connect: send a state snapshot (job row + manifest + progress.json
    [Fix 9]); reject a 3rd+ subscriber beyond the cap; then relay live
    EventBus events as-is until the client disconnects.
    """
    await websocket.accept()
    job_id = websocket.path_params.get("job_id", "")
    settings = websocket.app.state.settings
    bus: EventBus = websocket.app.state.bus
    registry: SubscriberRegistry = websocket.app.state.subscribers
    session_factory = websocket.app.state.session_factory

    # --- Look up the job row (snapshot source for status + stage) ---
    try:
        async with session_factory() as session:
            job = await get_job(session, job_id)
    except Exception:
        _log.exception("ws snapshot: get_job failed for %s", job_id)
        await websocket.send_json({"type": "error", "code": "internal_error"})
        await websocket.close(code=1008)
        return

    if job is None:
        await websocket.send_json({"type": "error", "code": "not_found"})
        await websocket.close(code=1008)
        return

    # --- Subscriber cap (T-04-02) ---
    if not registry.add(job_id, websocket, settings.ws_subscriber_cap):
        await websocket.send_json({"type": "error", "code": "subscriber_cap"})
        await websocket.close(code=1008)
        return

    # --- State snapshot (Fix 9: percent + eta from progress.json) ---
    stage: str | None = job.current_stage
    try:
        manifest = await read_manifest(settings, job_id)
        if manifest.current_stage is not None:
            stage = manifest.current_stage
    except FileNotFoundError:
        # Manifest missing -- fall back to the DB row's current_stage.
        pass
    except Exception:
        _log.warning("ws snapshot: read_manifest failed for %s", job_id, exc_info=True)

    percent, eta = _read_progress_snapshot(settings, job_id)
    snapshot = {
        "type": "snapshot",
        "job_id": job_id,
        "stage": stage,
        "percent": percent,
        "eta": eta,
        "status": job.status,
    }
    await websocket.send_json(snapshot)

    # --- Live relay loop (04-01 EventBus -> WS client) ---
    queue = bus.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        # Client closed -- the finally block cleans up.
        pass
    except Exception:
        # A send failure (client gone mid-stream) -- log + clean up.
        _log.info("ws relay ended for %s", job_id, exc_info=True)
    finally:
        registry.remove(job_id, websocket)
        bus.unsubscribe(job_id, queue)


__all__ = ["SubscriberRegistry", "router"]