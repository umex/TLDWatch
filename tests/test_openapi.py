"""OpenAPI schema tests."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_openapi_paths(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "/health" in data["paths"]
    assert "/jobs" in data["paths"]


@pytest.mark.asyncio
async def test_openapi_manifest_schema(client: httpx.AsyncClient) -> None:
    """``JobManifest`` is registered in ``components.schemas`` with the D-05 fields."""
    resp = await client.get("/openapi.json")
    data = resp.json()
    schemas = data.get("components", {}).get("schemas", {})
    assert "JobManifest" in schemas, list(schemas.keys())

    manifest = schemas["JobManifest"]
    props = manifest.get("properties", {})
    expected = {
        "job_id",
        "schema_version",
        "current_stage",
        "stage_timestamps",
        "status",
        "error",
        "summary_kinds",
        "source_type",
        "source_path",
        "source_sha256",
        "duration_s",
        "language",
        "diarization_enabled",
    }
    assert expected.issubset(set(props.keys())), (
        f"missing fields: {expected - set(props.keys())}"
    )


@pytest.mark.asyncio
async def test_openapi_internal_control_schemas(client: httpx.AsyncClient) -> None:
    """Plan 01-03: ManifestPatch, StageUpdateRequest, StaleCheckResponse are
    registered in components.schemas for the openapi-typescript consumers
    in Phase 5."""
    resp = await client.get("/openapi.json")
    data = resp.json()
    schemas = data.get("components", {}).get("schemas", {})
    for name in (
        "ManifestPatch",
        "StageUpdateRequest",
        "StaleCheckRequest",
        "StaleCheckResponse",
    ):
        assert name in schemas, f"{name} missing from components.schemas"

    # ManifestPatch does NOT carry the protected fields.
    patch_props = set(schemas["ManifestPatch"].get("properties", {}).keys())
    for protected in (
        "current_stage",
        "job_id",
        "schema_version",
        "stage_timestamps",
        "status",
        "error",
    ):
        assert protected not in patch_props, (
            f"protected field {protected!r} leaked into ManifestPatch"
        )
