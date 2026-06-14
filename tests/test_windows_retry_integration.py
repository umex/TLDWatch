"""End-to-end Windows-retry integration tests for cancel and update_stage.

The ``os.replace`` step in :func:`app.storage.atomic.atomic_write_bytes`
and the ``shutil.rmtree`` step in :func:`app.jobs.cleanup.cancel_job`
are both wrapped in :func:`app.storage.retry.retry_windows`. This test
file drives a real ``cancel_job`` and a real ``update_stage`` with the
underlying filesystem calls mocked to raise ``PermissionError`` twice
then succeed; the call must complete and the DB / manifest must reflect
the new state.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.api import dependencies as deps_module
from app.jobs.cleanup import cancel_job
from app.jobs.manifest import update_stage
from app.jobs.service import get_job
from app.models.job import ManifestPatch
from app.models.settings import Settings


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(data_dir=str(tmp_data_dir / "data"))


def _session_factory():
    sf = deps_module.session_factory
    assert sf is not None, "session factory not configured"
    return sf


@pytest.mark.asyncio
async def test_cancel_with_rmtree_permission_error(
    client: httpx.AsyncClient, tmp_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """cancel_job with shutil.rmtree raising PermissionError twice then
    succeed completes and the folder is gone."""
    import logging

    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

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
        with caplog.at_level(logging.WARNING):
            async with sf() as session:
                ok = await cancel_job(session, s, job_id)
    assert ok is True
    assert len(calls) == 3  # two failures, then success
    # Folder is gone (real rmtree ran on the third call).
    assert not (tmp_data_dir / "data" / "jobs" / job_id).exists()

    # DB row is marked cancelled.
    async with sf() as session:
        refreshed = await get_job(session, job_id)
    assert refreshed is not None
    assert refreshed.status == "cancelled"


@pytest.mark.asyncio
async def test_update_stage_with_replace_permission_error(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """update_stage with os.replace raising PermissionError twice then
    succeed completes; the manifest on disk has the new current_stage
    and the DB row matches."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    import os as _os

    real_replace = _os.replace
    calls: list[int] = []

    def flaky_replace(src, dst, *args, **kwargs):  # noqa: ANN001
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "locked")
        return real_replace(src, dst, *args, **kwargs)

    sf = _session_factory()
    with patch("app.storage.atomic.os.replace", side_effect=flaky_replace):
        async with sf() as session:
            manifest = await update_stage(
                s,
                session,
                job_id,
                "transcribed",
                ManifestPatch(source_type="local"),
            )
    assert manifest.current_stage == "transcribed"
    assert manifest.source_type == "local"
    assert len(calls) == 3

    # Manifest on disk has the new value.
    on_disk = json.loads(
        (tmp_data_dir / "data" / "jobs" / job_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["current_stage"] == "transcribed"
    assert on_disk["source_type"] == "local"

    # DB row matches.
    async with sf() as session:
        refreshed = await get_job(session, job_id)
    assert refreshed is not None
    assert refreshed.current_stage == "transcribed"
