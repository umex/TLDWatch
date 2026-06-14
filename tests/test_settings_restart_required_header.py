"""Tests for the ``X-Restart-Required`` response header on
``PATCH /settings`` (Codex HIGH item 9).

The header is set when the PATCH actually changes ``data_dir``;
it is NOT set for an empty body (``{}``) or for a PATCH that sets
``data_dir`` to its current value.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_data_dir_change_sets_header(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": "C:/some/other/path"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-restart-required") == "true"


@pytest.mark.asyncio
async def test_empty_patch_omits_header(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={})
    assert resp.status_code == 200, resp.text
    # Empty PATCH: no field set, no restart required.
    assert "x-restart-required" not in {k.lower() for k in resp.headers.keys()}
