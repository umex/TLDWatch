"""Tests for cooperative cancel (queued / running / terminal) -- plan 04-02.

Phase 4 plan 04-02 Task 3 (TDD RED-first). Three cancel flows (D-06):

- ``test_cancel_queued``: cancelling a queued job flips the DB row to
  ``cancelled``, removes the per-job folder, and returns the row. The
  worker must not pick the job up afterwards (the atomic claim in
  ``pull_next`` only claims rows whose status is still ``queued``).
- ``test_cancel_running``: cancelling an ingesting / transcribing job
  sets the 04-01 ``threading.Event`` cancel flag; the chunker stops at
  the next chunk boundary (raises ``JobCancelled``); the orchestrator's
  ``JobCancelled`` path runs ``cancel_job`` (DB + rmtree). No partial
  ``transcript.json`` is left on disk (``atomic_write_json`` only fires
  after the whole transcribe returns -- Pitfall 4).
- ``test_cancel_terminal``: cancelling a ``done`` / ``failed`` /
  ``cancelled`` job is a no-op that returns the current row unchanged
  (D-06 idempotent).

These are xfail until Task 3 lands the ``cancel`` function in
:mod:`app.jobs.queue`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.jobs.errors import JobCancelled  # noqa: F401  (04-01 contract)
from app.jobs.manifest import empty_manifest, write_manifest
from app.jobs.service import create_job, get_job
from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir, job_dir, transcript_path

# Wave-0 import guards: queue.cancel lands in Task 3. Import lazily inside the
# tests so collection succeeds before Task 3 (the xfail markers handle the
# actual unimplemented path).


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_data_dir / "data"),
        backend=GpuBackend.CPU,
        run_worker=False,
    )


async def _session_factory(settings: Settings):
    from app.storage.db import apply_migrations, make_engine, make_sessionmaker

    engine = make_engine(settings)
    await apply_migrations(engine)
    return make_sessionmaker(engine)


async def _make_local_job(s: Settings, sf) -> str:
    """Create a local-source job with a real non-empty source file (D-04)."""
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
        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()
    return job_id


async def _set_status(sf, job_id: str, status: str) -> None:
    """Force a job row to ``status`` (bypasses the state machine -- test only)."""
    async with sf() as session:
        await session.execute(
            text("UPDATE jobs SET status = :s WHERE id = :id"),
            {"s": status, "id": job_id},
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["done", "failed", "cancelled"])
async def test_cancel_terminal(tmp_data_dir: Path, terminal: str) -> None:
    """Cancelling a terminal job is a no-op returning the current row (D-06).

    A job in ``done`` / ``failed`` / ``cancelled`` must NOT be touched: no
    DB UPDATE, no rmtree, no signal. The function returns the unchanged row.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    await _set_status(sf, job_id, terminal)

    from app.jobs.queue import cancel

    async with sf() as session:
        row = await cancel(job_id, session, s)

    assert row is not None
    assert row["status"] == terminal
    # The folder is untouched.
    assert job_dir(s, job_id).exists()


@pytest.mark.asyncio
async def test_cancel_queued(tmp_data_dir: Path) -> None:
    """Cancelling a queued job -> row ``cancelled``, folder removed, row returned."""
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    # Status is already ``queued`` from create_job.
    assert job_dir(s, job_id).exists()

    from app.jobs.queue import cancel

    async with sf() as session:
        row = await cancel(job_id, session, s)

    assert row is not None
    assert row["status"] == "cancelled"
    # The folder was removed by cancel_job (DB-first + rmtree).
    assert not job_dir(s, job_id).exists()


@pytest.mark.asyncio
async def test_cancel_running(tmp_data_dir: Path) -> None:
    """Cancelling a running job sets the cancel_flag; no partial transcript.json.

    The test forces the row to ``transcribing`` and registers a cancel flag in
    the orchestrator's ``_running`` registry (mirroring what 04-01's run_job
    does at the top of its body). ``cancel`` looks up the flag and sets it;
    the 04-01 orchestrator's ``JobCancelled`` path runs ``cancel_job`` itself
    (so ``cancel`` does NOT double-call ``cancel_job``).
    """
    import threading

    from app.jobs.orchestrator import _running

    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    await _set_status(sf, job_id, "transcribing")

    # Register a cancel flag as if run_job were in-flight.
    flag = threading.Event()
    _running[job_id] = flag

    try:
        from app.jobs.queue import cancel

        async with sf() as session:
            row = await cancel(job_id, session, s)

        # The cancel flag was set (the chunker would observe it at the next
        # chunk boundary and raise JobCancelled).
        assert flag.is_set()
        # cancel returns the current row (still ``transcribing`` -- the
        # orchestrator's JobCancelled path flips it to ``cancelled`` via
        # cancel_job; cancel() itself does not double-call cancel_job).
        assert row is not None
        assert row["status"] == "transcribing"
        # No partial transcript.json is left (cancel does not write one;
        # atomic_write_json fires only after the whole transcribe returns).
        assert not transcript_path(s, job_id).exists()
    finally:
        _running.pop(job_id, None)