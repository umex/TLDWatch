"""Tests for the VRAM budget gate + the unload endpoint (SC-4, D-03).

Three tests via the API (``POST /models/{id}/load`` / ``/unload``):

- ``test_load_refuses_when_budget_exceeded`` -- a tight ``probe_vram``
  state makes the 7B LLM load fail with 507 ``vram_budget_exceeded``.
- ``test_load_succeeds_within_budget`` -- a generous ``probe_vram``
  state lets the 7B LLM load succeed (200 + ``LoadedModel`` body);
  ``GET /diagnostics/vram`` shows the loaded entry.
- ``test_unload_clears_loaded_entry`` -- ``POST /models/{id}/unload``
  returns 204; ``GET /diagnostics/vram`` shows ``loaded=[]``; a
  second unload is also 204 (D-03 idempotent).
"""

from __future__ import annotations

import httpx
import pytest

from app.models.diagnostics import GpuBackend, VRAMState


@pytest.mark.asyncio
async def test_load_refuses_when_budget_exceeded(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """SC-4: 507 when the 7B LLM would push past the 85% budget."""
    mock_probe_vram.side_effect = lambda backend, state: VRAMState(
        backend=GpuBackend.CUDA,
        total_mb=4096,
        available_mb=0,
        used_mb=2000,
        loaded=[],
    )
    resp = await client.post("/models/balanced.llm/load")
    assert resp.status_code == 507, resp.text
    body = resp.json()
    # FastAPI wraps HTTPException detail in a "detail" envelope.
    detail = body.get("detail", body)
    assert detail["error"] == "vram_budget_exceeded"
    assert detail["category"] == "llm"
    assert detail["needed_mb"] > 0
    assert detail["available_mb"] >= 0


@pytest.mark.asyncio
async def test_load_succeeds_within_budget(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """SC-4: 200 + LoadedModel body when the budget is generous; the
    diagnostics endpoint then shows the loaded entry.
    """
    # Default mock_probe_vram is generous and reflects the manager state.
    resp = await client.post("/models/balanced.llm/load")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category"] == "llm"
    assert body["model_id"] == "Qwen/Qwen2.5-7B-Instruct-GGUF"
    assert body["vram_bytes"] > 0

    # GET /diagnostics/vram reflects the loaded entry.
    diag = await client.get("/diagnostics/vram")
    assert diag.status_code == 200, diag.text
    loaded = diag.json()["loaded"]
    assert any(entry["category"] == "llm" for entry in loaded)


@pytest.mark.asyncio
async def test_unload_clears_loaded_entry(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """SC-4, D-03: unload is 204 + idempotent; diagnostics shows loaded=[]."""
    # Default mock_probe_vram is generous and reflects the manager state.
    # Load first so there is something to unload.
    load = await client.post("/models/balanced.llm/load")
    assert load.status_code == 200, load.text

    unload = await client.post("/models/balanced.llm/unload")
    assert unload.status_code == 204

    diag = await client.get("/diagnostics/vram")
    assert diag.status_code == 200
    loaded = diag.json()["loaded"]
    assert not any(entry["category"] == "llm" for entry in loaded)

    # Idempotent: a second unload is also 204 (D-03).
    again = await client.post("/models/balanced.llm/unload")
    assert again.status_code == 204