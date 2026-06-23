"""Boot interrupted-job sweep -- mark starting/ingesting/transcribing jobs (plan 04-02 + 04-05).

On a backend restart, jobs that were actively processing
(``status IN ('starting','ingesting','transcribing')`` -- CR-01 widened
the filter to include the transient ``starting`` set by pull_next's
atomic claim) when the process died are stuck: their worker thread is
gone, but the DB row still says "active". D-03 says: do NOT auto-resume
them (D-02 forbids mid-transcription checkpointing; a partial transcript
is not reusable). Instead mark them ``failed`` with ``error="interrupted
(backend restarted)"`` so the user can re-submit from scratch.

CR-02: before failing, the sweep consults ``infer_resume_point`` per swept
job. If the resume walker says the job's stages are file-complete
(``resume_point is None or resume_point == "done"`` -- e.g. transcript.json
on disk + manifest.current_stage="transcribed" but the derived done
transition was never recorded), the sweep ADVANCES the job to ``done``
via ``update_stage`` INSTEAD of failing it. The user's completed
transcription is preserved (no rmtree). A ``starting`` job has no stage
output, so ``infer_resume_point`` returns ``"ingested"`` (not None, not
"done") and the sweep proceeds to ``mark_failed`` -- the starting job is
correctly FAILED, not advanced.

Queued jobs are NOT swept (D-03): they re-join the FIFO and the worker
picks them up normally on the next boot.

Codex MEDIUM (T-04-05): the sweep updates BOTH the DB row AND the
manifest. ``reconcile_all`` (which runs BEFORE this sweep in the lifespan
-- Task 4) projects the DB row from the manifest; if the sweep only
touched the DB, the next boot's ``reconcile_all`` would see the manifest
still says ``transcribing`` and revert the DB row back to active. Writing
the manifest to ``failed`` first makes the change idempotent across boots.
(The CR-02 advance path uses ``update_stage`` which writes the manifest
first and commits the DB last -- the SAME ordering the orchestrator happy
path uses, so reconcile_all stays consistent for the advanced row too.)

``mark_failed`` (cleanup) keeps the folder -- source data may be intact
and the operator / a future re-submit can inspect it. No rmtree here.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.cleanup import mark_failed
from app.jobs.manifest import read_manifest, update_stage
from app.jobs.resume import infer_resume_point
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
    ``status IN ('starting','ingesting','transcribing')`` (CR-01 -- the
    transient ``starting`` set by pull_next's atomic claim is now swept
    too; NOT ``queued`` -- D-03: queued re-join FIFO). For each id:

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
            "SELECT id FROM jobs WHERE status IN ('starting','ingesting','transcribing')"
        )
    )
    ids = [row[0] for row in result.fetchall()]
    swept = 0
    for job_id in ids:
        # CR-02: consult infer_resume_point BEFORE mark_failed. Read the
        # manifest first; on success, ask the resume walker whether the
        # job's stages are actually complete. If resume_point is None
        # (all applicable stages complete) or "done" (only the derived
        # done transition is missing), advance the job to done via
        # update_stage -- the user's completed transcription is preserved
        # (no rmtree, no failed-manifest write). Otherwise (a real
        # incomplete stage like "ingested" / "transcribed") fall through
        # to mark_failed + the failed-manifest write as today.
        try:
            manifest = await read_manifest(settings, job_id)
        except FileNotFoundError:
            # No manifest on disk (the folder was removed but the DB row
            # lingered -- a rare crash window). No resume consultation is
            # possible (infer_resume_point requires a manifest). Fail the
            # DB row and continue -- nothing to reconcile against.
            _log.warning(
                "mark_interrupted_failed: no manifest for %s; DB row only",
                job_id,
            )
            await mark_failed(session, job_id, _INTERRUPTED_ERROR)
            swept += 1
            continue

        resume_point = infer_resume_point(settings, job_id, manifest)
        if resume_point is None or resume_point == "done":
            # CR-02: the job's stages are file-complete (e.g. transcript.json
            # on disk + manifest.current_stage="transcribed"); only the
            # derived done transition is missing. Advance to done via
            # update_stage -- write-manifest-first / commit-DB-last, the
            # SAME call the orchestrator happy path makes. The user's
            # completed transcription is preserved (update_stage does not
            # touch the folder).
            await update_stage(settings, session, job_id, "done")
            _log.info(
                "mark_interrupted_failed: job %s advanced to done via "
                "resume (resume_point=%r)",
                job_id,
                resume_point,
            )
            swept += 1
            continue

        # resume_point is a real incomplete stage ("ingested" /
        # "transcribed" / etc.) -- the job has genuine unfinished work.
        # Fail it as today: DB row -> failed (keeps the folder; no rmtree).
        await mark_failed(session, job_id, _INTERRUPTED_ERROR)

        # Manifest -> failed so reconcile_all does not revert.
        payload = manifest.model_dump(mode="json")
        payload["status"] = "failed"
        payload["current_stage"] = "failed"
        payload["error"] = _INTERRUPTED_ERROR
        await atomic_write_json(manifest_path(settings, job_id), payload)
        swept += 1
    if swept:
        await session.commit()
    _log.info("mark_interrupted_failed: swept %d interrupted jobs", swept)
    return swept


__all__ = ["mark_interrupted_failed"]