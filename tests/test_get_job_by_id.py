"""Tests for ``GET /jobs/{id}``.

404 with ``{"detail": "job not found"}`` for a missing id, the
matching job for a present id.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_returns_job(client: httpx.AsyncClient) -> None:
    create = await client.post("/jobs", json={})
    job_id = create.json()["id"]

    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == job_id
    assert body["status"] == "queued"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_get_missing_returns_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/jobs/no-such-id")
    assert resp.status_code == 404
    body = resp.json()
    assert body == {"detail": "job not found"}
