"""Original-filename persistence tests -- plan 05-04 Task 1.

Closes UAT test-4 gap A: history rows showed ``source.<ext>`` instead of
the dropped filename because the upload route discarded ``X-Filename``
after extension validation.

Round-trip + null case:
- ``test_upload_persists_original_filename``: POST /jobs/upload with
  ``X-Filename: "my great video.mp4"`` -> GET /jobs/{id} returns
  ``original_filename == "my great video.mp4"``; the on-disk manifest
  carries the same value; ``source_path`` still ends with ``source.mp4``
  (D-04 unchanged).
- ``test_create_job_without_upload_has_null_original_filename``: a job
  created via POST /jobs (the JSON route, no upload) has
  ``original_filename is None`` on GET /jobs/{id}.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_upload_persists_original_filename(
    client: httpx.AsyncClient,
) -> None:
    """POST /jobs/upload persists X-Filename as original_filename."""
    headers = {
        "Idempotency-Key": "orig-name-1",
        "X-Filename": "my great video.mp4",
        "Content-Type": "application/octet-stream",
    }
    resp = await client.post(
        "/jobs/upload", content=b"\x00" * 1024, headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["id"]

    # Immediate GET /jobs/{id} returns the persisted original_filename
    # (the upload route writes the DB column before enqueue).
    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200, got.text
    got_body = got.json()
    assert got_body["original_filename"] == "my great video.mp4", got_body

    # The on-disk manifest carries original_filename.
    from app.jobs.manifest import read_manifest
    from app.main import app

    settings = app.state.settings
    manifest = await read_manifest(settings, job_id)
    assert manifest.original_filename == "my great video.mp4", manifest
    # D-04 unchanged: source_path still points at source.<ext>.
    assert manifest.source_path is not None
    assert manifest.source_path.endswith("source.mp4"), manifest.source_path

    # The DB original_filename column was written at upload time so an
    # immediate GET returns it without waiting for the orchestrator's
    # update_stage re-projection. (source_path is NOT projected to the DB
    # at upload time -- the orchestrator's update_stage("ingested") does
    # that, and the worker is off in this test, so the DB source_path
    # column is still NULL here. The D-04 invariant is checked via the
    # on-disk manifest + the source.<ext> file existence below.)
    factory = app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT source_path, original_filename FROM jobs "
                    "WHERE id = :id"
                ),
                {"id": job_id},
            )
        ).fetchone()
    assert row is not None
    assert row.original_filename == "my great video.mp4", row

    # Sanity: the in-job-dir source.<ext> file actually exists (D-04
    # unchanged -- source_path on the manifest points at this file).
    job_dir = Path(settings.data_dir) / "jobs" / job_id
    assert (job_dir / "source.mp4").exists(), list(job_dir.iterdir())


@pytest.mark.asyncio
async def test_create_job_without_upload_has_null_original_filename(
    client: httpx.AsyncClient,
) -> None:
    """POST /jobs (no upload) leaves original_filename == null."""
    resp = await client.post("/jobs", json={"source_type": "local"})
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200, got.text
    assert got.json()["original_filename"] is None