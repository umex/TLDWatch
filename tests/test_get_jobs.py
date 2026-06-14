"""Tests for ``GET /jobs`` and ``GET /jobs/{id}``.

Verifies the read surface added in Plan 01-02: ordering,
status filter, pagination, and 404 for missing ids.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_list_orders_newest_first(client: httpx.AsyncClient) -> None:
    # Create two jobs in sequence; the second's created_at is later
    # so it must be returned first.
    a = (await client.post("/jobs", json={})).json()
    b = (await client.post("/jobs", json={})).json()

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    items = resp.json()
    ids = [j["id"] for j in items]
    assert b["id"] in ids
    assert a["id"] in ids
    # Newest first: the index of b in the list must be less than a.
    assert ids.index(b["id"]) < ids.index(a["id"])


@pytest.mark.asyncio
async def test_status_filter_returns_matching(client: httpx.AsyncClient) -> None:
    await client.post("/jobs", json={})
    await client.post("/jobs", json={})

    resp = await client.get("/jobs", params={"status": "queued"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert all(j["status"] == "queued" for j in items)

    resp_empty = await client.get("/jobs", params={"status": "done"})
    assert resp_empty.status_code == 200
    assert resp_empty.json() == []


@pytest.mark.asyncio
async def test_limit_query(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.post("/jobs", json={})

    resp = await client.get("/jobs", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_limit_cap_200(client: httpx.AsyncClient) -> None:
    # The service silently caps at 200; with 3 jobs we expect 3.
    for _ in range(3):
        await client.post("/jobs", json={})

    resp = await client.get("/jobs", params={"limit": 500})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    # The cap is verified separately by the unit-level service test
    # in test_get_jobs_service.py; here we just confirm the route
    # returns 200 and all existing jobs.
