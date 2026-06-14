"""Tests for the OpenAPI contract of ``POST /jobs`` (Plan 01-04 H2).

The 201 response is ``JobResponse`` (not ``JobManifest``). The
``JobManifest`` schema is still registered in ``components.schemas``
(via ``_EXTRA_OPENAPI_MODELS`` in ``app.main``) because the
openapi-typescript consumer in Phase 5 uses it for the
``/jobs/{id}/stage`` route.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_openapi_201_references_job_response(
    client: httpx.AsyncClient,
) -> None:
    """``POST /jobs`` 201 schema references ``JobResponse``."""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()

    # POST /jobs
    post = data["paths"]["/jobs"]["post"]
    s201 = post["responses"]["201"]["content"]["application/json"]["schema"]
    # Either a $ref to JobResponse, or an inline schema with
    # title: JobResponse. The exact shape is FastAPI's choice —
    # we just need the name to appear.
    import json as _json

    assert "JobResponse" in _json.dumps(s201), s201


@pytest.mark.asyncio
async def test_openapi_job_manifest_is_in_components(
    client: httpx.AsyncClient,
) -> None:
    """``JobManifest`` is still in ``components.schemas`` for
    openapi-typescript consumers (Phase 5)."""
    resp = await client.get("/openapi.json")
    data = resp.json()
    schemas = data.get("components", {}).get("schemas", {})
    assert "JobManifest" in schemas, list(schemas.keys())


@pytest.mark.asyncio
async def test_live_post_jobs_returns_job_response_shape(
    client: httpx.AsyncClient,
) -> None:
    """A real ``POST /jobs`` returns the ``JobResponse`` shape (id, not job_id)."""
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # JobResponse fields
    assert "id" in body
    assert body["status"] == "queued"
    assert "created_at" in body
    assert "current_stage" in body  # nullable; Pydantic emits null
    assert body["current_stage"] is None
    # NOT JobManifest fields
    assert "job_id" not in body
    assert "stage_timestamps" not in body
    assert "schema_version" not in body
