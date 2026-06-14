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
    }
    assert expected.issubset(set(props.keys())), (
        f"missing fields: {expected - set(props.keys())}"
    )
