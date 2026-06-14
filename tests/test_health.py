"""Health + middleware behaviour tests."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_trusted_host_rejects_evil_host(client: httpx.AsyncClient) -> None:
    # httpx's ASGI transport passes headers through verbatim, but it
    # also synthesises a Host header from ``base_url``. We override
    # the Host header explicitly.
    resp = await client.get("/health", headers={"Host": "evil.example"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cors_preflight_allows_vite(client: httpx.AsyncClient) -> None:
    resp = await client.options(
        "/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # Starlette's CORS middleware answers 200 for an allowed preflight.
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
