"""End-to-end tests for ``POST /jobs``."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.models.manifest import JobManifest


@pytest.mark.asyncio
async def test_post_jobs_creates_job_end_to_end(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # UUIDv4 and status=queued
    parsed = uuid.UUID(body["id"])
    assert parsed.version == 4
    assert body["status"] == "queued"
    assert "created_at" in body
    assert body["created_at"].endswith("+00:00")

    job_id = body["id"]
    manifest_file = tmp_data_dir / "data" / "jobs" / job_id / "manifest.json"
    assert manifest_file.exists(), f"manifest missing at {manifest_file}"

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["job_id"] == job_id
    assert manifest["status"] == "queued"
    assert manifest["schema_version"] == 1
    assert "stage_timestamps" in manifest
    assert manifest["stage_timestamps"]["queued"].endswith("+00:00")


@pytest.mark.asyncio
async def test_post_jobs_rejects_unknown_field(client: httpx.AsyncClient) -> None:
    resp = await client.post("/jobs", json={"unknown": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_jobs_manifest_is_valid_pydantic(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201
    job_id = resp.json()["id"]
    manifest_file = tmp_data_dir / "data" / "jobs" / job_id / "manifest.json"
    assert manifest_file.exists()
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    # Pydantic validation is the round-trip test: the file we wrote
    # must deserialise back into the typed model.
    m = JobManifest.model_validate(payload)
    assert m.job_id == job_id
    assert m.schema_version == 1
    assert m.status == "queued"


# --- Plan 01-04 H5: create_job compensates DB row on folder/manifest fail -


@pytest.mark.asyncio
async def test_create_job_compensates_on_folder_failure(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    """If ensure_job_dir raises, the DB row is DELETED before the
    exception propagates (no orphan row)."""
    import sqlite3 as _sqlite3
    from unittest.mock import patch

    from app.api import dependencies as deps_module
    from app.jobs import service as jobs_service
    from app.models.diagnostics import GpuBackend
    from app.models.settings import Settings

    settings = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    sf = deps_module.session_factory
    assert sf is not None

    # Pre-count rows.
    db_path = tmp_data_dir / "data" / "app.db"
    con = _sqlite3.connect(db_path)
    before = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    con.close()

    with patch.object(
        jobs_service, "ensure_job_dir", side_effect=OSError(28, "no space")
    ):
        with pytest.raises(OSError):
            async with sf() as session:
                await jobs_service.create_job(session, settings)

    con = _sqlite3.connect(db_path)
    after = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    con.close()
    assert after == before, (before, after)


@pytest.mark.asyncio
async def test_create_job_compensates_on_manifest_failure(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    """If write_manifest raises, the DB row is DELETED (no orphan)."""
    import sqlite3 as _sqlite3
    from unittest.mock import patch

    from app.api import dependencies as deps_module
    from app.jobs import service as jobs_service
    from app.models.diagnostics import GpuBackend
    from app.models.settings import Settings

    settings = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    sf = deps_module.session_factory
    assert sf is not None

    db_path = tmp_data_dir / "data" / "app.db"
    con = _sqlite3.connect(db_path)
    before = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    con.close()

    with patch.object(
        jobs_service, "write_manifest", side_effect=OSError(28, "no space")
    ):
        with pytest.raises(OSError):
            async with sf() as session:
                await jobs_service.create_job(session, settings)

    con = _sqlite3.connect(db_path)
    after = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    con.close()
    assert after == before, (before, after)
