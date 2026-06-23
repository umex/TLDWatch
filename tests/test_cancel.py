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


# --- Plan 04-06 (WR-04 gap closure) ----------------------------------------
#
# Three API integration tests that drive ``POST /jobs/{id}/cancel`` via the
# httpx ``client`` fixture (FastAPI app under test). They reuse the
# ``_settings`` / ``_session_factory`` / ``_make_local_job`` / ``_set_status``
# helpers above. The ``client`` fixture's lifespan writes
# ``data_dir=str(tmp_data_dir/"data")`` to settings.json, and
# ``_settings(tmp_data_dir)`` builds a Settings pointing at the same
# ``data_dir`` -- so a job created via ``_make_local_job`` is visible to the
# API route (same SQLite DB). The httpx pattern mirrors
# ``test_post_jobs_201_response.py``.


@pytest.mark.asyncio
async def test_cancel_queued_via_api(tmp_data_dir: Path, client: "object") -> None:
    """POST /jobs/{id}/cancel on a queued job -> 200 + cancelled + folder removed.

    WR-04: the route must call ``queue.cancel`` (cooperative path), which for a
    queued job runs ``cancel_job`` (DB-first + rmtree) + ``_work_signal.set``.
    """
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    # Status is ``queued`` from create_job; folder exists.
    assert job_dir(s, job_id).exists()

    resp = await client.post(f"/jobs/{job_id}/cancel")

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    # Folder removed by cancel_job (DB-first + rmtree).
    assert not job_dir(s, job_id).exists()
    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_running_via_api(tmp_data_dir: Path, client: "object") -> None:
    """POST /jobs/{id}/cancel on a running job -> flag set, no partial transcript.

    WR-04 contract: the API does NOT rmtree out from under the orchestrator.
    ``queue.cancel`` only sets the ``_running`` threading.Event cancel flag for
    running jobs; the orchestrator's own ``JobCancelled`` path does the
    ``cancel_job`` + rmtree at the next chunk boundary. This test simulates the
    orchestrator's path completing (calling ``cancel_job``) to confirm the end
    state is correct and there is no double-rmtree.
    """
    import threading

    import httpx
    from app.jobs.orchestrator import _running

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    await _set_status(sf, job_id, "transcribing")

    # Register a cancel flag as if run_job were in-flight (mirrors
    # test_cancel_running's setup).
    flag = threading.Event()
    _running[job_id] = flag

    try:
        resp = await client.post(f"/jobs/{job_id}/cancel")

        assert resp.status_code == 200, resp.text
        # The cooperative path set the cancel flag (the chunker would observe
        # it at the next chunk boundary and raise JobCancelled).
        assert flag.is_set()
        # No partial transcript.json is left on disk (cancel does not write
        # one; atomic_write_json fires only after the whole transcribe
        # returns).
        assert not transcript_path(s, job_id).exists()
        # The folder is NOT removed by the API (cooperative -- the orchestrator
        # does the rmtree); it is still on disk until the orchestrator's
        # JobCancelled path fires.
        assert job_dir(s, job_id).exists()

        # Simulate the orchestrator's JobCancelled path completing: the chunker
        # raised JobCancelled -> the orchestrator's except clause calls
        # cancel_job. This is the single cancel_job call (no double-rmtree).
        from app.jobs.cleanup import cancel_job

        async with sf() as session:
            ok = await cancel_job(session, s, job_id)
        assert ok is True  # the row was still active -- no double-rmtree conflict
        async with sf() as session:
            row = await get_job(session, job_id)
        assert row is not None
        assert row.status == "cancelled"
        assert not job_dir(s, job_id).exists()
    finally:
        _running.pop(job_id, None)


@pytest.mark.asyncio
async def test_cancel_terminal_via_api_idempotent(
    tmp_data_dir: Path, client: "object"
) -> None:
    """POST /jobs/{id}/cancel on a terminal job is a no-op returning 200 (D-06).

    A terminal job (``cancelled`` here) returns 200 with the unchanged row --
    NOT 404 (cancel_job's ``False`` return for terminal rows used to map to
    404; ``queue.cancel`` returns the row as a no-op). A SECOND cancel is
    idempotent: 200 with the cancelled row, no error. The folder is untouched
    (terminal no-op does not rmtree).
    """
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)
    job_id = await _make_local_job(s, sf)
    await _set_status(sf, job_id, "cancelled")  # terminal
    assert job_dir(s, job_id).exists()

    resp1 = await client.post(f"/jobs/{job_id}/cancel")
    assert resp1.status_code == 200, resp1.text
    assert resp1.json()["status"] == "cancelled"

    # Second cancel is idempotent (D-06) -- 200, no error, still cancelled.
    resp2 = await client.post(f"/jobs/{job_id}/cancel")
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["status"] == "cancelled"

    # Terminal no-op does not rmtree the folder.
    assert job_dir(s, job_id).exists()