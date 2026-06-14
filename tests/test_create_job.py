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
