"""Tests for :mod:`app.jobs.manifest`: read / write / update_stage.

Plan 01-03 truth statements covered here:

- ``read_manifest`` round-trips with ``write_manifest``.
- ``read_manifest`` raises :class:`FileNotFoundError` (not a generic
  Exception) for a missing job.
- ``update_stage`` writes the manifest BEFORE updating the DB
  (write-manifest-first, commit-DB-last ordering per Codex HIGH #1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text

from app.jobs.manifest import (
    empty_manifest,
    manifest_mtime,
    read_manifest,
    update_stage,
    write_manifest,
)
from app.models.job import ManifestPatch
from app.models.manifest import JobManifest
from app.models.settings import Settings


@pytest.mark.asyncio
async def test_roundtrip(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """POST /jobs writes a manifest; read_manifest returns the same model."""
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    settings = Settings(data_dir=str(tmp_data_dir / "data"))
    manifest = await read_manifest(settings, job_id)
    assert manifest.job_id == job_id
    assert manifest.status == "queued"
    assert manifest.schema_version == 1
    # Round-trip: model_dump of the deserialised model must equal the
    # raw JSON on disk (modulo any field normalisation Pydantic v2
    # applies; the canonical form is ``model_dump(mode="json")``).
    on_disk = json.loads(
        (tmp_data_dir / "data" / "jobs" / job_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest.model_dump(mode="json") == on_disk


@pytest.mark.asyncio
async def test_missing_raises_filenotfound(tmp_data_dir: Path) -> None:
    """read_manifest raises FileNotFoundError for a job that has no manifest."""
    settings = Settings(data_dir=str(tmp_data_dir / "data"))
    with pytest.raises(FileNotFoundError) as excinfo:
        await read_manifest(settings, "00000000-0000-0000-0000-000000000000")
    assert "00000000-0000-0000-0000-000000000000" in str(excinfo.value)


def test_manifest_mtime_returns_none_for_missing(tmp_data_dir: Path) -> None:
    settings = Settings(data_dir=str(tmp_data_dir / "data"))
    assert manifest_mtime(settings, "no-such-id") is None


@pytest.mark.asyncio
async def test_update_stage_writes_manifest_first(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """When the DB UPDATE raises, the manifest on disk is still authoritative.

    Codex HIGH #1: write-manifest-first, commit-DB-last. The
    scenario tested here is a partial write where the manifest
    landed on disk but the DB write then raised. The manifest
    on disk must still reflect the new value (the next boot's
    reconcile_all will heal the DB).
    """
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201
    job_id = resp.json()["id"]
    settings = Settings(data_dir=str(tmp_data_dir / "data"))

    # Get a session via the app's session factory.
    from app.api.dependencies import get_session
    from app.main import app
    from app.storage.db import make_sessionmaker

    # Use a real session to drive update_stage, but patch the
    # ``session.execute`` to raise on the UPDATE so we can prove
    # the manifest write happened first.
    from app.api.dependencies import session_factory as configured_factory

    assert configured_factory is not None
    real_execute = None

    async def fake_execute(stmt, params=None):  # noqa: ANN001
        if real_execute is None:
            raise RuntimeError("setup error")
        sql = str(stmt)
        # Plan 01-04 H3+H4: the UPDATE SQL was extended to project
        # ``status`` and the full metadata columns. The new statement
        # starts ``UPDATE jobs SET status = :status, current_stage = ...``;
        # match on the unique ``UPDATE jobs SET status = :status,
        # current_stage`` prefix so this guard catches the new SQL too.
        if "UPDATE jobs SET status = :status, current_stage" in sql:
            raise AssertionError("DB UPDATE blocked for the test")
        return await real_execute(stmt, params)

    async with configured_factory() as session:
        real_execute = session.execute
        session.execute = fake_execute  # type: ignore[assignment]
        with pytest.raises(AssertionError, match="DB UPDATE blocked"):
            await update_stage(
                settings,
                session,
                job_id,
                "transcribed",
                ManifestPatch(source_type="local"),
            )

    # Manifest on disk still has the new current_stage and the
    # patched source_type, even though the DB write failed.
    on_disk = json.loads(
        (tmp_data_dir / "data" / "jobs" / job_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["current_stage"] == "transcribed"
    assert on_disk["source_type"] == "local"
    assert on_disk["stage_timestamps"]["transcribed"] is not None


@pytest.mark.asyncio
async def test_update_stage_projects_status_and_metadata(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """Plan 01-04 H3+H4: update_stage projects ``status`` AND the
    full metadata set (``language``, ``duration_s``, ``summary_kinds_json``)
    in the same UPDATE."""
    from app.api import dependencies as deps_module
    from app.jobs.manifest import update_stage

    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    settings = Settings(data_dir=str(tmp_data_dir / "data"))
    sf = deps_module.session_factory
    assert sf is not None

    async with sf() as session:
        await update_stage(
            settings,
            session,
            job_id,
            "transcribed",
            ManifestPatch(language="en", duration_s=12.5, summary_kinds=["meeting"]),
        )

    async with sf() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, language, duration_s, summary_kinds_json "
                    "FROM jobs WHERE id = :id"
                ),
                {"id": job_id},
            )
        ).fetchone()
    assert row is not None
    assert row[0] == "transcribing"
    assert row[1] == "en"
    assert row[2] == 12.5
    assert json.loads(row[3]) == ["meeting"]
