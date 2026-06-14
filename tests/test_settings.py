"""Tests for ``GET /settings`` and ``PATCH /settings``.

The strict-input model (D-15) rejects int values and unknown
fields at the API boundary with a 422.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_settings(client: httpx.AsyncClient) -> None:
    resp = await client.get("/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data_dir" in body
    # The default data_dir is the absolute path of the bootstrap
    # data dir from the test fixture; we only assert it is non-empty.
    assert body["data_dir"]


@pytest.mark.asyncio
async def test_patch_settings_persists(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    new_dir = "C:/tmp/x"
    resp = await client.patch("/settings", json={"data_dir": new_dir})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_dir"] == new_dir

    # The on-disk file was rewritten atomically.
    settings_file = tmp_data_dir / "data" / "settings.json"
    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["data_dir"] == new_dir

    # The in-memory state reflects the change.
    follow = await client.get("/settings")
    assert follow.json()["data_dir"] == new_dir


@pytest.mark.asyncio
async def test_patch_settings_rejects_int(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": 123})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_settings_rejects_unknown_field(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"unknown_field": "x"})
    assert resp.status_code == 422
