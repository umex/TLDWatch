"""SC-1 tests: first-run GPU detect + burn test writes settings.json.

Covers the three first-boot paths (CUDA / ROCm / CPU) and the
subsequent-boot skip-detect path. The mock seam is
:func:`app.models.backend.detect` + :func:`app.models.backend.burn_test`
(patched via the ``mock_backend_detect`` fixture).

The first-boot tests write a Phase 1-shaped ``data/settings.json``
(just ``data_dir``, no ``backend``) so the lifespan's
``try/except ValidationError`` falls through to the detect path. The
subsequent-boot test writes a Phase 2-shaped file (``backend`` already
set) so the lifespan skips detect.

D-06: the CPU path asserts ``burn_test_ms is None`` and
``vram_total_mb is None`` and that the app still starts (never refuses).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.models.diagnostics import BackendProbe, GpuBackend
from app.models.settings import Settings


@asynccontextmanager
async def _boot_and_client():
    """Drive the FastAPI lifespan manually and yield an httpx client.

    The ``client`` fixture cannot be used directly for the first-boot
    tests because they need to overwrite ``data/settings.json`` AFTER
    ``tmp_data_dir`` sets up the temp dir but BEFORE the lifespan
    boots. This helper runs the lifespan inline so the test body
    controls the ordering.
    """
    agen = app.router.lifespan_context(app)
    await agen.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as ac:
            yield ac
    finally:
        await agen.__aexit__(None, None, None)


def _write_phase1_settings(tmp_data_dir: Path) -> None:
    """Overwrite settings.json with a Phase 1-shaped file (just data_dir)."""
    data_dir = tmp_data_dir / "data"
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        json.dumps({"data_dir": str(data_dir.resolve())}),
        encoding="utf-8",
    )


def _write_phase2_settings(tmp_data_dir: Path, backend: GpuBackend) -> None:
    """Overwrite settings.json with a Phase 2-shaped file (backend set)."""
    data_dir = tmp_data_dir / "data"
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        Settings(
            data_dir=str(data_dir.resolve()), backend=backend
        ).model_dump_json(),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_first_run_writes_settings_with_cuda_backend(
    tmp_data_dir: Path, mock_backend_detect: SimpleNamespace
) -> None:
    """SC-1: a fresh install with a CUDA GPU writes backend=cuda."""
    mock_backend_detect.detect.return_value = GpuBackend.CUDA
    mock_backend_detect.burn_test.return_value = BackendProbe(
        backend=GpuBackend.CUDA,
        device_name="NVIDIA RTX 2000 Ada",
        burn_test_ms=12.5,
        vram_total_mb=8192,
    )
    _write_phase1_settings(tmp_data_dir)

    async with _boot_and_client() as client:
        settings_path = tmp_data_dir / "data" / "settings.json"
        disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert disk["backend"] == "cuda"
        assert disk["backend_probe"]["device_name"] == "NVIDIA RTX 2000 Ada"
        assert disk["backend_probe"]["burn_test_ms"] == 12.5
        assert disk["backend_probe"]["vram_total_mb"] == 8192
        # All 7 new fields are on disk (D-08 declare-now).
        for field in (
            "backend",
            "backend_probe",
            "hf_token",
            "quality_preset",
            "per_category_overrides",
            "concurrent_models",
            "vram_budget_fraction",
        ):
            assert field in disk, f"missing {field}"

        resp = await client.get("/settings")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["backend"] == "cuda"
        assert body["backend_probe"]["device_name"] == "NVIDIA RTX 2000 Ada"


@pytest.mark.asyncio
async def test_first_run_writes_settings_with_rocm_backend(
    tmp_data_dir: Path, mock_backend_detect: SimpleNamespace
) -> None:
    """SC-1: a fresh install with an ROCm GPU writes backend=rocm."""
    mock_backend_detect.detect.return_value = GpuBackend.ROCM
    mock_backend_detect.burn_test.return_value = BackendProbe(
        backend=GpuBackend.ROCM,
        device_name="AMD Radeon RX 6800 XT",
        burn_test_ms=18.0,
        vram_total_mb=16384,
    )
    _write_phase1_settings(tmp_data_dir)

    async with _boot_and_client() as client:
        settings_path = tmp_data_dir / "data" / "settings.json"
        disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert disk["backend"] == "rocm"
        assert disk["backend_probe"]["device_name"] == "AMD Radeon RX 6800 XT"
        assert disk["backend_probe"]["vram_total_mb"] == 16384

        resp = await client.get("/settings")
        assert resp.status_code == 200, resp.text
        assert resp.json()["backend"] == "rocm"


@pytest.mark.asyncio
async def test_first_run_writes_settings_with_cpu_backend(
    tmp_data_dir: Path, mock_backend_detect: SimpleNamespace
) -> None:
    """SC-1 / D-06: a fresh install with no GPU writes backend=cpu and
    still starts (never refuses). burn_test_ms and vram_total_mb are None.
    """
    mock_backend_detect.detect.return_value = GpuBackend.CPU
    mock_backend_detect.burn_test.return_value = BackendProbe(
        backend=GpuBackend.CPU,
        device_name="CPU",
        burn_test_ms=None,
        vram_total_mb=None,
        notes="no GPU detected; running in CPU mode",
    )
    _write_phase1_settings(tmp_data_dir)

    async with _boot_and_client() as client:
        settings_path = tmp_data_dir / "data" / "settings.json"
        disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert disk["backend"] == "cpu"
        assert disk["backend_probe"]["device_name"] == "CPU"
        assert disk["backend_probe"]["burn_test_ms"] is None
        assert disk["backend_probe"]["vram_total_mb"] is None

        # D-06: the app still starts.
        resp = await client.get("/settings")
        assert resp.status_code == 200, resp.text
        assert resp.json()["backend"] == "cpu"


@pytest.mark.asyncio
async def test_subsequent_boot_does_not_redetect(
    tmp_data_dir: Path, mock_backend_detect: SimpleNamespace
) -> None:
    """SC-1: a subsequent boot (backend already on disk) skips detect."""
    _write_phase2_settings(tmp_data_dir, GpuBackend.CUDA)

    async with _boot_and_client() as client:
        # detect was NOT called: the on-disk backend is already set.
        mock_backend_detect.detect.assert_not_called()
        mock_backend_detect.burn_test.assert_not_called()

        resp = await client.get("/settings")
        assert resp.status_code == 200, resp.text
        assert resp.json()["backend"] == "cuda"