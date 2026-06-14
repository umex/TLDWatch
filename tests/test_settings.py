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
    """A restart-required ``data_dir`` PATCH is persisted under the
    ``pending`` key (Plan 01-04 H1). The in-memory state and GET
    /settings still report the BOOT value until restart.
    """
    new_dir = "C:/tmp/x"
    boot_dir = str((tmp_data_dir / "data").resolve())
    resp = await client.patch("/settings", json={"data_dir": new_dir})
    assert resp.status_code == 200, resp.text
    # Response body is the in-memory state, which is the BOOT value
    # because the change is restart-required and the swap is deferred.
    body = resp.json()
    assert body["data_dir"] == boot_dir
    # Restart-required header is set.
    assert resp.headers.get("x-restart-required") == "true"

    # The on-disk file was rewritten atomically: data_dir stays at
    # the BOOT value; the new value lives under the pending key.
    settings_file = tmp_data_dir / "data" / "settings.json"
    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["data_dir"] == boot_dir
    assert payload["pending"]["data_dir"] == new_dir

    # GET /settings still returns the BOOT value (the in-memory
    # state was not swapped).
    follow = await client.get("/settings")
    assert follow.json()["data_dir"] == boot_dir


@pytest.mark.asyncio
async def test_patch_settings_rejects_int(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": 123})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_settings_rejects_unknown_field(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"unknown_field": "x"})
    assert resp.status_code == 422
