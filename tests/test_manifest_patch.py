"""Tests for :class:`app.models.job.ManifestPatch` (Codex HIGH #7).

The patch model is the typed, strict, extra=forbid allowlist of
user-mutable manifest fields. The protected fields
(``current_stage``, ``job_id``, ``schema_version``,
``stage_timestamps``, ``status``, ``error``) are NOT on the model
and cannot be set via the patch.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api import dependencies as deps_module
from app.jobs.manifest import read_manifest, update_stage
from app.jobs.service import get_job
from app.models.diagnostics import GpuBackend
from app.models.job import ManifestPatch, StageUpdateRequest
from app.models.settings import Settings


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)


def _session_factory():
    """Return the lifespan-configured session factory."""
    sf = deps_module.session_factory
    assert sf is not None, "session factory not configured"
    return sf


def test_patch_with_unknown_field_returns_422() -> None:
    """Extra fields are rejected by the strict model."""
    with pytest.raises(ValidationError) as excinfo:
        ManifestPatch(unknown_field="x")
    assert "unknown_field" in str(excinfo.value)


def test_patch_cannot_set_protected_fields() -> None:
    """The protected fields are NOT on the model and are rejected."""
    # current_stage is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(current_stage="fake")
    # job_id is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(job_id="spoofed")
    # status is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(status="done")
    # error is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(error="x")
    # stage_timestamps is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(stage_timestamps={})
    # schema_version is not a ManifestPatch field
    with pytest.raises(ValidationError):
        ManifestPatch(schema_version=99)


def test_stage_update_request_rejects_unknown_stage() -> None:
    """StageUpdateRequest.stage is a Literal; unknown stages are rejected."""
    with pytest.raises(ValidationError):
        StageUpdateRequest(stage="unknown_stage")


def test_patch_with_known_fields_is_valid() -> None:
    """All allowlisted fields are accepted."""
    patch = ManifestPatch(
        source_type="local",
        source_path="/foo/bar.mp4",
        source_sha256="abc",
        duration_s=12.5,
        language="en",
        summary_kinds=["meeting"],
    )
    assert patch.source_type == "local"
    assert patch.language == "en"


@pytest.mark.asyncio
async def test_update_stage_applies_allowlisted_fields(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """update_stage with a patch applies only the allowlisted fields."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    sf = _session_factory()
    async with sf() as session:
        manifest = await update_stage(
            s,
            session,
            job_id,
            "ingested",
            ManifestPatch(source_type="local", language="en"),
        )
    assert manifest.source_type == "local"
    assert manifest.language == "en"
    assert manifest.current_stage == "ingested"

    # On disk, the manifest carries the patched values.
    on_disk = json.loads(
        (tmp_data_dir / "data" / "jobs" / job_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["source_type"] == "local"
    assert on_disk["language"] == "en"
    assert on_disk["current_stage"] == "ingested"

    # DB row reflects the new current_stage.
    async with sf() as session:
        refreshed = await get_job(session, job_id)
    assert refreshed is not None
    assert refreshed.current_stage == "ingested"


@pytest.mark.asyncio
async def test_update_stage_ignores_protected_overrides(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """A patch CANNOT override ``current_stage`` - the helper sets it from
    the ``stage`` argument. Sending a protected key like ``job_id`` in
    the patch is rejected at the model level (extra=forbid)."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]
    s = _settings(tmp_data_dir)

    # Use the HTTP route so the ManifestPatch validation is exercised
    # end-to-end: a payload with a protected field is rejected with 422.
    bad_payload = {
        "stage": "transcribed",
        "manifest_patch": {"current_stage": "fake", "source_type": "local"},
    }
    resp = await client.post(f"/jobs/{job_id}/stage", json=bad_payload)
    assert resp.status_code == 422

    # Now do a clean stage update with a known-good patch.
    resp = await client.post(
        f"/jobs/{job_id}/stage",
        json={"stage": "transcribed", "manifest_patch": {"source_type": "local"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_stage"] == "transcribed"
    assert body["source_type"] == "local"


@pytest.mark.asyncio
async def test_update_stage_protected_fields_not_in_model() -> None:
    """ManifestPatch.model_fields does NOT include the protected keys."""
    fields = set(ManifestPatch.model_fields.keys())
    protected = {
        "current_stage",
        "job_id",
        "schema_version",
        "stage_timestamps",
        "status",
        "error",
    }
    assert fields.isdisjoint(protected), (
        f"protected fields leaked into ManifestPatch: {fields & protected}"
    )


# --- Plan 01-04 H4: stage update projects manifest metadata to DB ----------


@pytest.mark.asyncio
async def test_update_stage_projects_metadata_to_db(
    client: httpx.AsyncClient,
) -> None:
    """A stage update with a manifest_patch projects language, duration_s,
    summary_kinds to the DB row, and GET /jobs/{id} reflects them."""
    resp = await client.post("/jobs", json={})
    job_id = resp.json()["id"]

    resp = await client.post(
        f"/jobs/{job_id}/stage",
        json={
            "stage": "transcribed",
            "manifest_patch": {
                "language": "en",
                "duration_s": 42.5,
                "summary_kinds": ["meeting"],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["language"] == "en"
    assert body["duration_s"] == 42.5
    assert body["summary_kinds"] == ["meeting"]

    # GET /jobs/{id} reflects the same fields.
    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    fetched = resp.json()
    assert fetched["language"] == "en"
    assert fetched["duration_s"] == 42.5
    assert fetched["summary_kinds"] == ["meeting"]
    assert fetched["current_stage"] == "transcribed"
