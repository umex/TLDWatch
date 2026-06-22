"""Tests for :mod:`app.jobs.orchestrator` -- the run_job state-machine driver.

Phase 4 plan 04-01. Wave 0 stubs (TDD RED-first):

- ``test_state_machine`` (Task 2 GREEN): a submitted job moves
  ``queued -> ingesting -> transcribing -> done``; the transcript
  exists at ``transcript_path`` and parses as a :class:`Transcript`.
- ``test_restart_rejoin`` (Task 2 GREEN): a job that "crashes" during
  transcribing (no ``transcript.json``) re-enters at transcribing via
  :func:`infer_resume_point` and re-transcribes from scratch (D-02).
- ``test_heartbeat_during_transcribing`` (Task 3 GREEN, Fix 2): a long
  transcription with refreshed ``progress.json`` is NOT marked stale by
  :func:`is_stale` even though wall-clock-equivalent time exceeds the
  10-min threshold -- the watchdog sees the fresh ``progress.json``
  mtime because ``_STAGE_FILE_NAMES`` now includes it.
- ``test_progress_snapshot_persisted`` (Task 3 GREEN, Fix 9): after a
  run_job, ``progress.json`` exists at ``job_dir/progress.json`` and
  contains ``chunks_done`` / ``chunks_total`` / ``percent`` / ``eta_s``
  / ``updated_at``.

These stubs import from ``app.jobs.orchestrator`` which does not exist
yet -- Task 2 creates ``run_job``. Until then pytest collection fails
RED on the import (the TDD RED gate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jobs.errors import JobCancelled  # noqa: F401  (Task 1a contract)
from app.jobs.manifest import empty_manifest, write_manifest
from app.jobs.orchestrator import run_job  # RED until Task 2
from app.jobs.progress import EventBus
from app.jobs.resume import infer_resume_point
from app.jobs.service import create_job, get_job
from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.models.transcript import Transcript
from app.storage.fs import ensure_job_dir, job_dir, transcript_path
from tests._stt_fake import FakeAdapter


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_data_dir / "data"),
        backend=GpuBackend.CPU,
        run_worker=False,
    )


async def _session_factory(settings: Settings):
    """Build a session factory against the project's engine + migrations.

    Mirrors the lifespan's ``make_engine`` / ``make_sessionmaker`` +
    ``apply_migrations`` path so the orchestrator tests get a real
    ``jobs`` table without spinning up the whole FastAPI app.
    """
    from app.storage.db import apply_migrations, make_engine, make_sessionmaker

    engine = make_engine(settings)
    await apply_migrations(engine)
    return make_sessionmaker(engine)


@pytest.mark.asyncio
async def test_state_machine(tmp_data_dir: Path) -> None:
    """A submitted job moves queued -> ingesting -> transcribing -> done.

    A FakeAdapter returning a 2-segment Transcript is wired through
    ``run_job``; after the call the DB row's ``status == "done"``,
    ``current_stage == "done"``, and ``transcript.json`` exists at
    ``transcript_path`` and parses as a :class:`Transcript`.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    # Create a local-source job (D-04 reference-in-place -- no copy).
    async with sf() as session:
        # Write a real source file the orchestrator validates.
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        # Patch the manifest to carry a source_path pointing at a real
        # non-empty file in the job dir (D-04: reference in place).
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        # Reflect source_path on the DB row so get_job sees it.
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # FakeAdapter: 2-segment transcript (fast path, single call).
    fake = FakeAdapter()
    bus = EventBus()

    await run_job(s, sf, job_id, bus=bus, adapter=fake)

    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "done"
    assert row.current_stage == "done"

    tpath = transcript_path(s, job_id)
    assert tpath.exists(), "transcript.json must exist after run_job"
    transcript = Transcript.model_validate_json(tpath.read_text(encoding="utf-8"))
    assert transcript.job_id == job_id
    assert len(transcript.segments) >= 1


@pytest.mark.asyncio
async def test_restart_rejoin(tmp_data_dir: Path) -> None:
    """A crashed transcribe (no transcript.json) re-transcribes from scratch (D-02).

    Run run_job to ingesting, "crash" by raising before transcribing,
    re-invoke run_job -- infer_resume_point re-enters at transcribing
    and the job completes (no transcript.json -> re-transcribes whole).
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # First run: use a fake that raises mid-transcribing (after ingesting
    # recorded, before transcript.json is written). The simplest way to
    # "crash during transcribing" is to pass an adapter whose transcribe
    # raises -- run_job marks failed, but we then re-invoke with a
    # healthy adapter and the resume walker re-enters at transcribing
    # (no transcript.json on disk).
    crashing = FakeAdapter()
    crashing.transcribe_side_effect = RuntimeError("simulated crash mid-transcribe")

    with pytest.raises(RuntimeError, match="simulated crash"):
        await run_job(s, sf, job_id, bus=EventBus(), adapter=crashing)

    # No transcript.json was written -> infer_resume_point re-enters at
    # transcribing (ingested is already complete because the source file
    # validated and update_stage("ingested") ran).
    from app.jobs.manifest import read_manifest

    manifest = await read_manifest(s, job_id)
    resume = infer_resume_point(s, job_id, manifest)
    assert resume == "transcribed"

    # Re-invoke with a healthy adapter -- re-transcribes from scratch.
    healthy = FakeAdapter()
    await run_job(s, sf, job_id, bus=EventBus(), adapter=healthy)

    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "done"
    assert transcript_path(s, job_id).exists()


@pytest.mark.asyncio
async def test_heartbeat_during_transcribing(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A long transcription with refreshed progress.json is NOT stale (Fix 2).

    Simulate a long transcription whose wall-clock-equivalent time
    exceeds the 10-min ``is_stale`` threshold: the throttled
    ``progress.json`` rewrite refreshes its mtime, and because
    ``_STAGE_FILE_NAMES`` now includes ``progress.json``,
    :func:`last_stage_mtime` consults it -- so ``is_stale`` returns
    False (the watchdog does NOT false-positive on active transcription).
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # Drive run_job with a healthy fake (the fast path emits one progress
    # event, which writes progress.json).
    await run_job(s, sf, job_id, bus=EventBus(), adapter=FakeAdapter())

    # Now simulate "a long time has passed" by backdating every stage
    # file EXCEPT progress.json. Before Fix 2, ``last_stage_mtime`` did
    # not consult progress.json, so backdating manifest.json +
    # transcript.json + source.mp4 would make ``is_stale`` true (the
    # watchdog saw only the stale manifest mtime). After Fix 2 the
    # fresh progress.json mtime keeps the job fresh because
    # ``_STAGE_FILE_NAMES`` now includes ``progress.json``.
    import os
    import time

    fresh_mtime = time.time()
    # Backdate EVERY stage file except progress.json to 1 hour ago.
    old_mtime = fresh_mtime - 3600
    for name in ("manifest.json", "transcript.json"):
        p = job_dir(s, job_id) / name
        if p.exists():
            os.utime(p, (old_mtime, old_mtime))
    # Also backdate the source file so the ONLY fresh file left is
    # progress.json -- this isolates the Fix 2 root cause (without
    # Fix 2, last_stage_mtime would return the old source mtime and
    # is_stale would true-positive).
    src_file = job_dir(s, job_id) / "source.mp4"
    if src_file.exists():
        os.utime(src_file, (old_mtime, old_mtime))
    # progress.json was just written by run_job -- its mtime is fresh.
    assert (job_dir(s, job_id) / "progress.json").exists()

    from app.jobs.cleanup import is_stale

    assert is_stale(s, job_id, threshold_s=600) is False


@pytest.mark.asyncio
async def test_progress_snapshot_persisted(tmp_data_dir: Path) -> None:
    """After a run_job, progress.json exists with the required fields (Fix 9).

    ``progress.json`` carries ``chunks_done`` / ``chunks_total`` /
    ``percent`` / ``eta_s`` / ``updated_at`` so a reconnecting WS
    client reads a nonzero snapshot instead of a stale zero.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    await run_job(s, sf, job_id, bus=EventBus(), adapter=FakeAdapter())

    progress_file = job_dir(s, job_id) / "progress.json"
    assert progress_file.exists(), "progress.json must exist after run_job"
    snapshot = json.loads(progress_file.read_text(encoding="utf-8"))
    for field in ("chunks_done", "chunks_total", "percent", "eta_s", "updated_at"):
        assert field in snapshot, f"progress.json missing {field}"
    assert snapshot["chunks_done"] >= 1
    assert snapshot["chunks_total"] >= 1