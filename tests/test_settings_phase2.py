"""Phase 2 settings: strict-input (D-08, D-15) + hot-swap (H1) + D-05 token.

Covers:

- ``backend`` and ``backend_probe`` are rejected by PATCH /settings (422)
  -- D-08 (only the detect/burn path writes them).
- ``vram_budget_fraction`` range + type validation (D-15).
- ``quality_preset`` and ``concurrent_models`` hot-swap (H1: no restart,
  in-memory swapped, on-disk persisted).
- ``hf_token`` is base64 on disk (D-05) and ``null`` in GET /settings.

The ``client`` fixture boots the lifespan against a Phase 2-shaped
``data/settings.json`` with ``backend=CPU`` (no detect runs).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_patch_rejects_backend_field(client: httpx.AsyncClient) -> None:
    """D-08: ``backend`` is not on UpdateSettingsRequest; extra=forbid 422s it."""
    resp = await client.patch("/settings", json={"backend": "cuda"})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_rejects_backend_probe_field(client: httpx.AsyncClient) -> None:
    """D-08: ``backend_probe`` is not on UpdateSettingsRequest; 422."""
    resp = await client.patch(
        "/settings",
        json={"backend_probe": {"backend": "cuda", "device_name": "x"}},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_vram_budget_fraction_out_of_range_returns_422(
    client: httpx.AsyncClient,
) -> None:
    """D-15: vram_budget_fraction must be in [0.1, 0.95]."""
    for bad in (1.5, 0.05, -0.1):
        resp = await client.patch(
            "/settings", json={"vram_budget_fraction": bad}
        )
        assert resp.status_code == 422, (bad, resp.text)


@pytest.mark.asyncio
async def test_patch_vram_budget_fraction_wrong_type_returns_422(
    client: httpx.AsyncClient,
) -> None:
    """D-15: a string for vram_budget_fraction is 422 (strict=True)."""
    resp = await client.patch(
        "/settings", json={"vram_budget_fraction": "high"}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_quality_preset_hot_swap(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """H1: quality_preset hot-swaps in-memory AND on disk; no restart header."""
    resp = await client.patch("/settings", json={"quality_preset": "small"})
    assert resp.status_code == 200, resp.text
    # No restart-required (only data_dir is restart-required).
    assert "x-restart-required" not in {k.lower() for k in resp.headers.keys()}

    # GET /settings returns the new value.
    follow = await client.get("/settings")
    assert follow.status_code == 200
    assert follow.json()["quality_preset"] == "small"

    # On-disk file persisted the new value (Phase 2 hot-swap writes
    # the full new.model_dump()).
    settings_path = tmp_data_dir / "data" / "settings.json"
    disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert disk["quality_preset"] == "small"


@pytest.mark.asyncio
async def test_patch_concurrent_models_hot_swap(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """H1: concurrent_models hot-swaps; no restart header; persisted."""
    resp = await client.patch("/settings", json={"concurrent_models": True})
    assert resp.status_code == 200, resp.text
    assert "x-restart-required" not in {k.lower() for k in resp.headers.keys()}

    follow = await client.get("/settings")
    assert follow.json()["concurrent_models"] is True

    settings_path = tmp_data_dir / "data" / "settings.json"
    disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert disk["concurrent_models"] is True


@pytest.mark.asyncio
async def test_get_settings_hf_token_is_null_in_response(
    client: httpx.AsyncClient,
) -> None:
    """D-05: GET /settings never returns the hf_token (always null)."""
    patch = await client.patch("/settings", json={"hf_token": "hf_abc123"})
    assert patch.status_code == 200, patch.text

    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert resp.json()["hf_token"] is None


@pytest.mark.asyncio
async def test_hf_token_is_base64_on_disk(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    """D-05: the on-disk settings.json holds hf_token base64-encoded."""
    resp = await client.patch("/settings", json={"hf_token": "hf_abc123"})
    assert resp.status_code == 200, resp.text

    settings_path = tmp_data_dir / "data" / "settings.json"
    raw = settings_path.read_text(encoding="utf-8")
    # base64("hf_abc123") == "aGZfYWJjMTIz"
    assert "aGZfYWJjMTIz" in raw, raw
    assert "hf_abc123" not in raw, raw