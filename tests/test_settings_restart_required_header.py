"""Tests for the ``X-Restart-Required`` response header on
``PATCH /settings`` (Codex HIGH item 9).

The header is set when the PATCH actually changes ``data_dir``;
it is NOT set for a PATCH that sets ``data_dir`` to its current
value.

Plan 01-04 (T8): the ``data_dir`` field is now required on
``UpdateSettingsRequest``; a PATCH with an empty body returns 422
(was 200 with no header in Plan 01-02).
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
async def test_empty_patch_returns_422(client: httpx.AsyncClient) -> None:
    """Plan 01-04 T8: data_dir is required; an empty body is rejected."""
    resp = await client.patch("/settings", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_same_data_dir_omits_header(client: httpx.AsyncClient) -> None:
    """PATCH with the SAME data_dir as the current value is not
    restart-required and omits the X-Restart-Required header.
    """
    # Read the current value.
    current_resp = await client.get("/settings")
    assert current_resp.status_code == 200
    current = current_resp.json()["data_dir"]

    resp = await client.patch("/settings", json={"data_dir": current})
    assert resp.status_code == 200, resp.text
    # No restart-required header: the value did not change.
    assert "x-restart-required" not in {k.lower() for k in resp.headers.keys()}
