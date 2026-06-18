"""Diagnostics API: POST /diagnostics/gpu-burn + GET /diagnostics/vram (SC-1, H1).

Covers:

- ``POST /diagnostics/gpu-burn`` re-runs detect + burn, hot-swaps the
  in-memory backend, and persists to disk atomically (no
  ``X-Restart-Required`` -- H1: only ``data_dir`` is restart-required).
- ``GET /diagnostics/vram`` returns the typed :class:`VRAMState` shape
  with ``loaded=[]`` (no models loaded in 02-01).
- ``GET /diagnostics/vram`` reports the same backend as ``current()``.

The ``mock_backend_detect`` fixture patches
:func:`app.models.backend.detect` + :func:`app.models.backend.burn_test`.
The ``client`` fixture boots the lifespan against a Phase 2-shaped
``data/settings.json`` with ``backend=CPU`` (no detect runs at boot).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.models.diagnostics import BackendProbe, GpuBackend
from app.settings import service as settings_service


@pytest.mark.asyncio
async def test_gpu_burn_updates_in_memory_backend(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
    mock_backend_detect: SimpleNamespace,
) -> None:
    """POST /diagnostics/gpu-burn hot-swaps the in-memory backend to the
    re-detected value and persists it atomically (D-04 Phase-1 helper)."""
    mock_backend_detect.detect.return_value = GpuBackend.ROCM
    mock_backend_detect.burn_test.return_value = BackendProbe(
        backend=GpuBackend.ROCM,
        device_name="AMD Radeon RX 6800 XT",
        burn_test_ms=18.0,
        vram_total_mb=16384,
    )

    resp = await client.post("/diagnostics/gpu-burn")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_backend"] == "rocm"
    assert body["settings_written"] is True
    assert body["probe"]["device_name"] == "AMD Radeon RX 6800 XT"

    # In-memory state swapped immediately (no restart).
    assert settings_service.current().backend == GpuBackend.ROCM

    # GET /settings reflects the new backend.
    follow = await client.get("/settings")
    assert follow.status_code == 200
    assert follow.json()["backend"] == "rocm"

    # On-disk file persisted atomically.
    settings_path = tmp_data_dir / "data" / "settings.json"
    disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert disk["backend"] == "rocm"
    assert disk["backend_probe"]["device_name"] == "AMD Radeon RX 6800 XT"


@pytest.mark.asyncio
async def test_gpu_burn_no_restart_required_header(
    client: httpx.AsyncClient, mock_backend_detect: SimpleNamespace
) -> None:
    """H1: POST /diagnostics/gpu-burn is a hot-swap; no X-Restart-Required."""
    mock_backend_detect.detect.return_value = GpuBackend.CUDA
    mock_backend_detect.burn_test.return_value = BackendProbe(
        backend=GpuBackend.CUDA,
        device_name="NVIDIA RTX 2000 Ada",
        burn_test_ms=10.0,
        vram_total_mb=8192,
    )

    resp = await client.post("/diagnostics/gpu-burn")
    assert resp.status_code == 200, resp.text
    assert "x-restart-required" not in {
        k.lower() for k in resp.headers.keys()
    }


@pytest.mark.asyncio
async def test_get_vram_returns_state(client: httpx.AsyncClient) -> None:
    """GET /diagnostics/vram returns 200 with the typed VRAMState shape.

    ``loaded`` is empty until 02-02's model manager wires in.
    """
    resp = await client.get("/diagnostics/vram")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("backend", "total_mb", "available_mb", "used_mb", "loaded"):
        assert key in body, f"missing {key}"
    assert isinstance(body["loaded"], list)
    assert body["loaded"] == []


@pytest.mark.asyncio
async def test_get_vram_uses_settings_backend(
    client: httpx.AsyncClient,
) -> None:
    """GET /diagnostics/vram reports the same backend as the in-memory
    Settings (the route reads ``current().backend``)."""
    resp = await client.get("/diagnostics/vram")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == settings_service.current().backend.value