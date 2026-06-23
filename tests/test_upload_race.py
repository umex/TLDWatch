"""Streaming upload worker-race test -- plan 05-01 Task 2 (INGEST-01, Pitfall 1, T-05-03).

Unit + integration test asserting the Phase 4 worker's ``pull_next``
(which selects only ``status='queued'`` rows) never picks up a job that
is mid-upload (``status='uploading'``). After the upload route calls
``enqueue``, the row flips to ``'queued'`` and ``pull_next`` returns it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.jobs.manifest import empty_manifest, write_manifest
from app.jobs.queue import enqueue, pull_next
from app.jobs.service import create_upload_job
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


@pytest.mark.asyncio
async def test_worker_invisible_to_uploading_job(tmp_data_dir: Path) -> None:
    """A job in ``status='uploading'`` is invisible to ``pull_next`` (Pitfall 1).

    ``pull_next`` selects only ``status='queued'`` rows, so a mid-upload
    job is never picked up. After the upload route calls ``enqueue`` the
    status flips to ``'queued'`` and ``pull_next`` returns the job id.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    # Create a job in the pre-queued 'uploading' state (mirrors what the
    # upload route does via create_upload_job before the file lands).
    async with sf() as session:
        job = await create_upload_job(session, s)
    job_id = job.id
    assert job.status == "uploading"

    # The worker's pull_next selects ONLY status='queued'; an 'uploading'
    # job is invisible (Pitfall 1 -- never picked up mid-upload).
    async with sf() as session:
        claimed = await pull_next(session)
    assert claimed is None, (
        f"pull_next must NOT claim an 'uploading' job; got {claimed!r}"
    )

    # The upload route finishes, calls enqueue -> status flips to 'queued'.
    async with sf() as session:
        await enqueue(job_id, session)

    # Now pull_next claims the job (status is 'queued').
    async with sf() as session:
        claimed = await pull_next(session)
    assert claimed == job_id, (
        f"pull_next must claim the now-queued job; got {claimed!r}"
    )

    # And the claim flipped it to 'starting'.
    async with sf() as session:
        row = await session.execute(
            text("SELECT status FROM jobs WHERE id = :id"),
            {"id": job_id},
        )
        assert row.fetchone()[0] == "starting"