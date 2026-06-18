"""Tests for the concurrent-model policy (SC-5, D-04).

Four tests:

- ``test_default_refuses_second_model`` -- with the default
  ``concurrent_models=False``, a second load raises 409
  ``concurrent_refused`` (D-04 refuse-then-caller-unloads).
- ``test_opt_in_allows_second_model`` -- after ``PATCH /settings
  {"concurrent_models": true}``, a second load succeeds (200); the
  diagnostics endpoint shows both entries.
- ``test_concurrent_models_in_openapi`` -- ``GET /openapi.json``
  exposes ``concurrent_models`` in ``UpdateSettingsRequest.properties``.
- ``test_unload_first_then_load_second`` -- after unloading the
  resident model, a second load of a different category succeeds
  (D-04 caller-unloads pattern).
"""

from __future__ import annotations

import httpx
import pytest

from app.models.diagnostics import GpuBackend, VRAMState


@pytest.mark.asyncio
async def test_default_refuses_second_model(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """SC-5, D-04: default concurrent_models=False -> second load is 409."""
    # Default mock_probe_vram is generous and reflects the manager state.
    first = await client.post("/models/balanced.stt/load")
    assert first.status_code == 200, first.text

    second = await client.post("/models/balanced.llm/load")
    assert second.status_code == 409, second.text
    body = second.json()
    detail = body.get("detail", body)
    assert detail["error"] == "concurrent_refused"
    assert detail["loaded"] == "stt"
    assert detail["requested"] == "llm"
    assert detail["fix"] == "set concurrent_models=true in settings"


@pytest.mark.asyncio
async def test_opt_in_allows_second_model(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """SC-5: with concurrent_models=True (via PATCH), both loads succeed."""
    # Use a generous budget so both models fit.
    mock_probe_vram.side_effect = lambda backend, state: VRAMState(
        backend=GpuBackend.CUDA,
        total_mb=16384,
        available_mb=16384,
        used_mb=0,
        loaded=[],
    )
    patch = await client.patch("/settings", json={"concurrent_models": True})
    assert patch.status_code == 200, patch.text

    first = await client.post("/models/balanced.stt/load")
    assert first.status_code == 200, first.text
    second = await client.post("/models/balanced.llm/load")
    assert second.status_code == 200, second.text

    # Restore the default side_effect so diagnostics reflects state.
    from app.models.vram import _loaded_list

    mock_probe_vram.side_effect = lambda backend, state: VRAMState(
        backend=GpuBackend.CUDA,
        total_mb=16384,
        available_mb=16384,
        used_mb=0,
        loaded=_loaded_list(state),
    )
    diag = await client.get("/diagnostics/vram")
    assert diag.status_code == 200
    loaded_cats = {entry["category"] for entry in diag.json()["loaded"]}
    assert {"stt", "llm"}.issubset(loaded_cats)


@pytest.mark.asyncio
async def test_concurrent_models_in_openapi(
    client: httpx.AsyncClient,
) -> None:
    """SC-5: ``concurrent_models`` is exposed in UpdateSettingsRequest."""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schemas = resp.json()["components"]["schemas"]
    props = schemas["UpdateSettingsRequest"].get("properties", {})
    assert "concurrent_models" in props


@pytest.mark.asyncio
async def test_unload_first_then_load_second(
    client: httpx.AsyncClient, mock_probe_vram
) -> None:
    """D-04: after unloading the resident model, a different category loads."""
    # Default mock_probe_vram is generous and reflects the manager state.
    first = await client.post("/models/balanced.stt/load")
    assert first.status_code == 200, first.text

    unload = await client.post("/models/balanced.stt/unload")
    assert unload.status_code == 204

    second = await client.post("/models/balanced.llm/load")
    assert second.status_code == 200, second.text
    assert second.json()["category"] == "llm"