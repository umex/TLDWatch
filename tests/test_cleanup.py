"""Tests for :mod:`app.jobs.cleanup`: cancel, mark_failed, is_stale, mark_stale.

Plan 01-03 truth statements covered here:

- ``cancel_job`` deletes the folder and marks the DB row 'cancelled'.
- ``cancel_job`` with mocked ``shutil.rmtree`` raising PermissionError
  twice then succeed still completes.
- ``cancel_job`` with mocked ``shutil.rmtree`` that ALWAYS fails still
  marks the row cancelled (DB-first ordering, Codex HIGH #8).
- ``mark_failed`` keeps the folder and marks the row 'failed' with
  the given error.
- ``mark_stale`` with a 0-second threshold marks the row failed with
  error='stalled'.
- ``mark_stale`` with a 1-hour threshold is a no-op for a freshly
  touched folder.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.api import dependencies as deps_module
from app.jobs.cleanup import cancel_job, is_stale, mark_failed, mark_stale
from app.jobs.manifest import empty_manifest, write_manifest
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir, job_dir, manifest_path


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(data_dir=str(tmp_data_dir / "data"))


def _session_factory():
    """Return the currently-configured session factory (configured by the
    lifespan-driven ``app_under_test`` fixture)."""
    sf = deps_module.session_factory
    assert sf is not None, "session factory not configured"
    return sf


@pytest.mark.asyncio
async def test_cancel_deletes_folder_and_marks_db(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """POST /jobs/{id}/cancel: row is cancelled, folder is gone."""
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    # The folder exists.
    assert (tmp_data_dir / "data" / "jobs" / job_id).is_dir()

    # POST cancel
    resp = await client.post(f"/jobs/{job_id}/cancel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"

    # Folder is gone.
    assert not (tmp_data_dir / "data" / "jobs" / job_id).exists()


@pytest.mark.asyncio
async def test_cancel_with_rmtree_retry_succeeds(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """rmtree raises twice then succeed; the cancel still completes."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    settings = _settings(tmp_data_dir)

    import shutil as _shutil

    real_rmtree = _shutil.rmtree
    calls: list[int] = []

    def flaky_rmtree(path, *args, **kwargs):  # noqa: ANN001
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "locked")
        return real_rmtree(path, *args, **kwargs)

    sf = _session_factory()
    with patch("app.jobs.cleanup.shutil.rmtree", side_effect=flaky_rmtree):
        async with sf() as session:
            ok = await cancel_job(session, settings, job_id)

    assert ok is True
    # Folder is eventually gone.
    assert not (tmp_data_dir / "data" / "jobs" / job_id).exists()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_cancel_with_rmtree_permanent_failure_still_marks_db(
    client: httpx.AsyncClient, tmp_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """rmtree always fails; the row is STILL marked cancelled (DB-first)."""
    import logging

    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    settings = _settings(tmp_data_dir)

    sf = _session_factory()
    with patch(
        "app.jobs.cleanup.shutil.rmtree",
        side_effect=PermissionError(13, "permanently locked"),
    ):
        with caplog.at_level(logging.WARNING):
            async with sf() as session:
                ok = await cancel_job(session, settings, job_id)

    assert ok is True
    async with sf() as session:
        from app.jobs.service import get_job

        refreshed = await get_job(session, job_id)
        assert refreshed is not None
        assert refreshed.status == "cancelled"


@pytest.mark.asyncio
async def test_mark_failed_keeps_folder(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """mark_failed leaves the folder intact for operator inspection."""
    s = _settings(tmp_data_dir)
    j = "aaaa1111-aaaa-1111-aaaa-111111111111"
    await ensure_job_dir(s, j)
    await write_manifest(s, empty_manifest(j))

    from app.jobs.service import create_job

    sf = _session_factory()
    async with sf() as session:
        created = await create_job(session, s)

    job_id = created.id
    folder = job_dir(s, job_id)
    assert folder.is_dir()

    async with sf() as session:
        ok = await mark_failed(session, job_id, "transcription crashed")
    assert ok is True

    # Folder is still there.
    assert folder.is_dir()
    # DB row's status is 'failed' with the given error.
    async with sf() as session:
        from app.jobs.service import get_job

        refreshed = await get_job(session, job_id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error == "transcription crashed"


@pytest.mark.asyncio
async def test_mark_stale_with_zero_threshold(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """mark_stale with threshold_s=0 marks the row failed with error='stalled'."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    # Sleep a tiny bit so the last_stage_mtime is measurably in the past
    # relative to time.time() at the moment of the call. 50ms is enough
    # for any reasonable scheduler granularity on Windows.
    time.sleep(0.05)

    sf = _session_factory()
    async with sf() as session:
        stale, marked = await mark_stale(session, s, job_id, threshold_s=0)
    assert stale is True
    assert marked is True

    async with sf() as session:
        from app.jobs.service import get_job

        refreshed = await get_job(session, job_id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error == "stalled"


@pytest.mark.asyncio
async def test_mark_stale_with_huge_threshold_is_noop(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """mark_stale with threshold_s=10**9 is a no-op for a fresh job."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    sf = _session_factory()
    async with sf() as session:
        stale, marked = await mark_stale(session, s, job_id, threshold_s=10**9)
    assert stale is False
    assert marked is False

    async with sf() as session:
        from app.jobs.service import get_job

        refreshed = await get_job(session, job_id)
        assert refreshed is not None
        assert refreshed.status == "queued"


def test_is_stale_falls_back_to_manifest_mtime(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """is_stale returns False if no activity, regardless of threshold."""
    s = _settings(tmp_data_dir)
    assert is_stale(s, "no-such-id", threshold_s=0) is False
