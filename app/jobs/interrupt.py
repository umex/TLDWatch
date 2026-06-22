"""Boot interrupted-job sweep -- mark ingesting/transcribing as failed (plan 04-02).

On a backend restart, jobs that were actively processing
(``status IN ('ingesting','transcribing')``) when the process died are
stuck: their worker thread is gone, but the DB row still says "active".
D-03 says: do NOT auto-resume them (D-02 forbids mid-transcription
checkpointing; a partial transcript is not reusable). Instead mark them
``failed`` with ``error="interrupted (backend restarted)"`` so the user
can re-submit from scratch.

Queued jobs are NOT swept (D-03): they re-join the FIFO and the worker
picks them up normally on the next boot.

Codex MEDIUM (T-04-05): the sweep updates BOTH the DB row AND the
manifest. ``reconcile_all`` (which runs BEFORE this sweep in the lifespan
-- Task 4) projects the DB row from the manifest; if the sweep only
touched the DB, the next boot's ``reconcile_all`` would see the manifest
still says ``transcribing`` and revert the DB row back to active. Writing
the manifest to ``failed`` first makes the change idempotent across boots.

``mark_failed`` (cleanup) keeps the folder -- source data may be intact
and the operator / a future re-submit can inspect it. No rmtree here.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.cleanup import mark_failed
from app.jobs.manifest import read_manifest
from app.models.settings import Settings
from app.storage.atomic import atomic_write_json
from app.storage.fs import manifest_path

_log = logging.getLogger(__name__)

_INTERRUPTED_ERROR = "interrupted (backend restarted)"


async def mark_interrupted_failed(
    session,
    settings: Settings,
    session_factory: async_sessionmaker,
) -> int:
    """Mark ingesting/transcribing jobs failed in BOTH DB and manifest.

    Runs AFTER :func:`app.jobs.reconcile.reconcile_all` and BEFORE
    :func:`app.jobs.queue.run_worker` (Task 4 lifespan wiring). Selects
    only ``status IN ('ingesting','transcribing')`` (NOT ``queued`` --
    D-03: queued re-join FIFO). For each id:

    1. ``await mark_failed(session, id, _INTERRUPTED_ERROR)`` -- DB row
       flipped to ``failed`` with the error string. Keeps the folder.
    2. Atomically rewrite the manifest with ``status='failed'``,
       ``current_stage='failed'``, ``error=_INTERRUPTED_ERROR`` so a
       subsequent ``reconcile_all`` does not revert (Codex MEDIUM). The
       manifest is the source of truth (D-03); the DB row is the
       projection.

    Returns the number of jobs swept.

    Implementation note on the manifest path: :func:`update_stage` cannot
    be used here because ``stage_to_status("failed", manifest)`` falls
    through to the defensive ``"queued"`` mapping (the stage map only
    covers the active processing stages; the terminal ``failed`` /
    ``cancelled`` statuses are set directly by :func:`mark_failed` /
    :func:`cancel_job`, never via ``update_stage``). Calling
    ``update_stage("failed", ...)`` would set the manifest status to
    ``queued`` -- wrong. So the sweep writes the manifest directly via
    :func:`atomic_write_json` (the same primitive ``write_manifest`` uses)
    with the terminal fields set explicitly. This is the documented
    fallback path from the 04-02 plan ("If -- and only if -- update_stage
    rejects 'failed' ... fall back to atomic_write_json").
    """
    result = await session.execute(
        text(
            "SELECT id FROM jobs WHERE status IN ('ingesting','transcribing')"
        )
    )
    ids = [row[0] for row in result.fetchall()]
    swept = 0
    for job_id in ids:
        # 1. DB row -> failed (keeps the folder; no rmtree).
        await mark_failed(session, job_id, _INTERRUPTED_ERROR)

        # 2. Manifest -> failed so reconcile_all does not revert.
        try:
            manifest = await read_manifest(settings, job_id)
            payload = manifest.model_dump(mode="json")
            payload["status"] = "failed"
            payload["current_stage"] = "failed"
            payload["error"] = _INTERRUPTED_ERROR
            await atomic_write_json(manifest_path(settings, job_id), payload)
        except FileNotFoundError:
            # No manifest on disk (the folder was removed but the DB row
            # lingered -- a rare crash window). The DB row is already
            # failed; nothing to reconcile against. Log and continue.
            _log.warning(
                "mark_interrupted_failed: no manifest for %s; DB row only",
                job_id,
            )
        swept += 1
    if swept:
        await session.commit()
    _log.info("mark_interrupted_failed: swept %d interrupted jobs", swept)
    return swept


__all__ = ["mark_interrupted_failed"]