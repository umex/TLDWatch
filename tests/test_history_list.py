"""History list back-end test -- plan 05-01 Task 3 (JOB-03).

Integration test locking the back-end contract the FE history page
consumes: ``GET /jobs?status=done|failed|cancelled`` returns only the
matching terminal jobs, newest-first, and active/queued jobs are
excluded. The existing ``list_jobs`` service already supports
``?status=``; this test locks the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.jobs.manifest import empty_manifest, write_manifest
from app.jobs.service import create_job
from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir


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


async def _make_job(s: Settings, sf) -> str:
    """Create a queued local-source job (the test then forces its status)."""
    async with sf() as session:
        job = await create_job(session, s, source_type="local")
    return job.id


async def _set_status(sf, job_id: str, status: str) -> None:
    """Force a job row to ``status`` (bypasses the state machine -- test only)."""
    async with sf() as session:
        await session.execute(
            text("UPDATE jobs SET status = :s WHERE id = :id"),
            {"s": status, "id": job_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_history_done_newest_first(tmp_data_dir: Path, client: "object") -> None:
    """GET /jobs?status=done returns only done jobs newest-first (JOB-03).

    Creates 3 jobs in sequence, forces them to ``done``, and asserts the
    ``?status=done`` list returns all 3 newest-first (the later-created
    job appears before the earlier one). Active (queued) jobs are excluded.
    """
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    job_ids = []
    for _ in range(3):
        jid = await _make_job(s, sf)
        job_ids.append(jid)
        await _set_status(sf, jid, "done")

    # Also create a queued job that must NOT appear in the done list.
    queued_id = await _make_job(s, sf)
    await _set_status(sf, queued_id, "queued")

    resp = await client.get("/jobs", params={"status": "done"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 3, items
    # All returned rows are done.
    assert all(j["status"] == "done" for j in items), items
    # Newest-first: the later-created job (job_ids[2]) appears before the
    # earlier one (job_ids[0]).
    ids = [j["id"] for j in items]
    assert ids.index(job_ids[2]) < ids.index(job_ids[0]), ids
    # The queued job is excluded.
    assert queued_id not in ids, ids


@pytest.mark.asyncio
async def test_history_failed_filter(tmp_data_dir: Path, client: "object") -> None:
    """GET /jobs?status=failed returns only failed jobs (JOB-03)."""
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    jid1 = await _make_job(s, sf)
    await _set_status(sf, jid1, "failed")
    jid2 = await _make_job(s, sf)
    await _set_status(sf, jid2, "done")
    jid3 = await _make_job(s, sf)
    await _set_status(sf, jid3, "queued")

    resp = await client.get("/jobs", params={"status": "failed"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1, items
    assert items[0]["status"] == "failed"
    assert items[0]["id"] == jid1


@pytest.mark.asyncio
async def test_history_cancelled_filter(tmp_data_dir: Path, client: "object") -> None:
    """GET /jobs?status=cancelled returns only cancelled jobs (JOB-03)."""
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    jid1 = await _make_job(s, sf)
    await _set_status(sf, jid1, "cancelled")
    jid2 = await _make_job(s, sf)
    await _set_status(sf, jid2, "ingesting")

    resp = await client.get("/jobs", params={"status": "cancelled"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1, items
    assert items[0]["status"] == "cancelled"
    assert items[0]["id"] == jid1
    # The ingesting (active) job is excluded.
    assert jid2 not in [j["id"] for j in items], items


@pytest.mark.asyncio
async def test_history_active_excluded_from_done(
    tmp_data_dir: Path, client: "object"
) -> None:
    """Active/queued/ingesting jobs are excluded from the terminal-status lists.

    GET /jobs?status=done returns only done rows -- queued, ingesting,
    transcribing, and starting rows do not leak in.
    """
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    done_id = await _make_job(s, sf)
    await _set_status(sf, done_id, "done")

    for active_status in ("queued", "starting", "ingesting", "transcribing"):
        active_id = await _make_job(s, sf)
        await _set_status(sf, active_id, active_status)

    resp = await client.get("/jobs", params={"status": "done"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1, items
    assert items[0]["id"] == done_id
    assert items[0]["status"] == "done"