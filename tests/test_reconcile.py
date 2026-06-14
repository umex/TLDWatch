"""Tests for :mod:`app.jobs.reconcile` — startup reconciliation (Codex HIGH #1).

Plan 01-03 truth statements covered here:

- A drifted DB row (DB says 'queued', manifest says 'transcribed')
  is healed by ``reconcile_all``: the DB row reflects the manifest.
- A matching row (DB == manifest) is left alone: no UPDATE issued,
  ``updated`` count is 0.
- A folder with no manifest is recorded in ``missing_manifests``;
  the folder is NOT auto-removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.api import dependencies as deps_module
from app.jobs.manifest import empty_manifest, read_manifest, write_manifest
from app.jobs.reconcile import reconcile_all
from app.jobs.service import create_job
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir, job_dir, manifest_path


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(data_dir=str(tmp_data_dir / "data"))


def _session_factory():
    sf = deps_module.session_factory
    assert sf is not None, "session factory not configured"
    return sf


@pytest.mark.asyncio
async def test_reconcile_heals_drift(client, tmp_data_dir: Path) -> None:
    """A DB row that lags the manifest is updated by reconcile_all.

    Scenario: the manifest is written to disk with current_stage =
    'transcribed', but the DB row's current_stage is still 'queued'
    (the crashed-before-DB-write window). reconcile_all must bring
    the DB row back in sync.
    """
    # Create a job normally (so the DB row + manifest are consistent).
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    # Manually advance the manifest to 'transcribed' WITHOUT updating
    # the DB row (simulating the crash window).
    from app.util.time import utcnow_iso

    manifest = await read_manifest(s, job_id)
    new_ts = manifest.stage_timestamps.model_copy(
        update={"transcribed": utcnow_iso()}
    )
    advanced = manifest.model_copy(
        update={
            "current_stage": "transcribed",
            "stage_timestamps": new_ts,
        }
    )
    await write_manifest(s, advanced)

    # Confirm the drift: DB current_stage is still NULL (create_job
    # sets it to None until update_stage is called).
    sf = _session_factory()
    async with sf() as session:
        from sqlalchemy import text

        result = await session.execute(
            text("SELECT current_stage FROM jobs WHERE id = :id"),
            {"id": job_id},
        )
        assert result.scalar() is None

    # Run reconcile. updated will be >= 1 because the row had NULL
    # stage_timestamps_json and is also drifted in current_stage.
    summary = await reconcile_all(s, sf)
    assert summary["scanned"] == 1
    assert summary["updated"] >= 1
    assert summary["missing_manifests"] == []

    # DB row now reflects the manifest.
    async with sf() as session:
        from app.jobs.service import get_job

        refreshed = await get_job(session, job_id)
        assert refreshed is not None
        assert refreshed.current_stage == "transcribed"

    # A second reconcile is a no-op.
    second = await reconcile_all(s, sf)
    assert second["updated"] == 0


@pytest.mark.asyncio
async def test_reconcile_no_op_for_matching(client, tmp_data_dir: Path) -> None:
    """A consistent DB+manifest pair is left alone by reconcile_all.

    After the first reconcile heals the initial ``stage_timestamps_json``
    NULL (the row was INSERTed before the column was populated in
    Plan 01-02), a second reconcile is a no-op.
    """
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)
    sf = _session_factory()

    # First reconcile: heals the stage_timestamps_json NULL drift that
    # create_job leaves behind (the manifest has a queued timestamp;
    # the row has NULL).
    first = await reconcile_all(s, sf)
    assert first["updated"] == 1
    # Second reconcile: now DB matches manifest, no-op.
    second = await reconcile_all(s, sf)
    assert second["scanned"] == 1
    assert second["updated"] == 0


@pytest.mark.asyncio
async def test_reconcile_logs_missing_manifest(client, tmp_data_dir: Path) -> None:
    """A folder without a manifest is recorded in missing_manifests;
    the folder itself is NOT auto-removed (a leftover from a crash
    that the operator may need to inspect)."""
    s = _settings(tmp_data_dir)
    sf = _session_factory()

    # Create an empty per-job folder (no manifest inside).
    job_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    folder = job_dir(s, job_id)
    folder.mkdir(parents=True)
    assert folder.is_dir()

    summary = await reconcile_all(s, sf)
    assert summary["scanned"] == 1
    assert summary["updated"] == 0
    assert "cccccccc-cccc-cccc-cccc-cccccccccccc" in summary["missing_manifests"]
    # Folder is still there.
    assert folder.is_dir()
