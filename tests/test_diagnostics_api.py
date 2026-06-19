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
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.models.diagnostics import BackendProbe, GpuBackend
from app.settings import service as settings_service


# --- Inline fixtures for the SC-4 / WR-03 live-behavior tests (02-05) -------
#
# These are defined INLINE in this test module (NOT in tests/conftest.py)
# because plan 02-04 owns the conftest edit this wave; a parallel conftest
# edit would risk a merge conflict. ``no_psutil`` simulates the exact UAT
# trigger (psutil declared in pyproject but not installed in the runtime
# env). ``cpu_manager`` mirrors ``configured_model_manager`` but WITHOUT
# ``mock_probe_vram`` so the real ``probe_vram`` CPU branch runs with real
# psutil reads (the mock forces backend='cuda', which would hide the CPU
# fallback the SC-4 fix is about).


@pytest.fixture
def no_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``import psutil`` to raise ``ModuleNotFoundError`` inside probe_vram.

    Simulates the exact SC-4 UAT trigger: psutil was declared in
    pyproject.toml (>=5.9) but not installed in the runtime env, so
    ``import psutil`` inside ``probe_vram`` raised and the CPU
    import-fail fallback fired. Setting ``sys.modules['psutil'] = None``
    makes ``import psutil`` raise
    ``ModuleNotFoundError: import of psutil halted; None in sys.modules``.
    """
    monkeypatch.setitem(sys.modules, "psutil", None)


@pytest.fixture
def cpu_manager(tmp_data_dir: Path) -> object:
    """Configure a fresh ``ModelManager`` WITHOUT mocking ``probe_vram``.

    Unlike ``configured_model_manager`` (which pulls ``mock_probe_vram``
    and forces ``backend='cuda'`` with ``total_mb=8192``), this fixture
    leaves ``probe_vram`` real so the CPU branch runs with real psutil
    reads. The lifespan already configured a manager; this replaces it
    with a fresh one for test isolation. Teardown resets via
    ``configure_manager(None)`` (which also resets the vram
    ``ManagerState`` singleton).
    """
    from app.models.manager import ModelManager, configure_manager

    settings = settings_service.current()
    mgr = ModelManager(settings)
    configure_manager(mgr)
    try:
        yield mgr
    finally:
        configure_manager(None)


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


# --- SC-4 / WR-03 live-behavior tests (Plan 02-05) -------------------------
#
# The existing test_get_vram_returns_state (above) only asserts the
# ``loaded==[]`` shape against an EMPTY manager state -- the test-coverage
# gap the 02-UAT diagnosed. These three tests load a model then assert
# /diagnostics/vram reflects it on CPU, including a psutil-absent variant
# that locks the graceful-degradation contract that was broken live.


@pytest.mark.asyncio
async def test_get_vram_loaded_when_psutil_absent(
    client: httpx.AsyncClient,
    cpu_manager: object,
    no_psutil: None,
) -> None:
    """SC-4 graceful degradation: when psutil is absent, the CPU
    error-fallback still populates ``loaded`` from ``manager_state``.

    This is the exact UAT failure mode: psutil declared in pyproject but
    not installed -> ``import psutil`` raised -> CPU import-fail fallback
    fired -> ``loaded=[]`` immediately after a 200 load. The fix
    (02-05 Task 1) makes both CPU error-fallbacks return
    ``loaded=_loaded_list(manager_state)`` so the indicator degrades
    gracefully (shows loaded even with total_mb=0).
    """
    resp = await client.post("/models/small.stt/load")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/diagnostics/vram")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "cpu"
    assert body["total_mb"] == 0
    assert body["available_mb"] == 0
    assert body["used_mb"] == 0
    assert len(body["loaded"]) == 1
    assert body["loaded"][0]["category"] == "stt"


@pytest.mark.asyncio
async def test_get_vram_reflects_loaded_model_on_cpu(
    client: httpx.AsyncClient,
    cpu_manager: object,
) -> None:
    """SC-4 happy path: with psutil installed, POST /models/{id}/load ->
    200 then GET /diagnostics/vram reflects the loaded model on CPU with
    real system RAM (total_mb > 0 via psutil.virtual_memory).
    """
    resp = await client.post("/models/small.stt/load")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/diagnostics/vram")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "cpu"
    assert body["total_mb"] > 0
    assert len(body["loaded"]) == 1
    assert body["loaded"][0]["category"] == "stt"
    assert "small" in body["loaded"][0]["model_id"]


@pytest.mark.asyncio
async def test_get_vram_empty_when_nothing_loaded(
    client: httpx.AsyncClient,
    cpu_manager: object,
) -> None:
    """Regression guard: with a live but empty manager state, GET
    /diagnostics/vram returns ``loaded==[]`` (now via
    ``_loaded_list(empty)`` instead of a literal ``[]``).
    """
    resp = await client.get("/diagnostics/vram")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["loaded"] == []