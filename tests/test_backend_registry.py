"""Registry tests for the extensible GPU backend detection (02 refactor).

Exercises the provider-registry internals that the mocked ``test_gpu_detect``
suite never touches: priority ordering, stub unavailability, the real
``detect()`` no-GPU path, the ``device_for`` mapping table, and the
``burn_test`` defensive fallback for stub backends.
"""

from __future__ import annotations

import pytest

from app.models import backend as backend_module
from app.models.backend import (
    BACKENDS,
    CpuProvider,
    DirectmlProvider,
    VulkanProvider,
    _provider_for,
    burn_test,
    detect,
    device_for,
)
from app.models.diagnostics import GpuBackend, InferenceEngine


# --- Registry ordering -----------------------------------------------------


def test_registry_sorted_by_priority() -> None:
    """BACKENDS is priority-sorted; CUDA before ROCm before CPU."""
    priorities = [p.priority for p in BACKENDS]
    assert priorities == sorted(priorities)
    order = [p.backend for p in BACKENDS]
    assert order == [
        GpuBackend.CUDA,
        GpuBackend.ROCM,
        GpuBackend.DIRECTML,
        GpuBackend.VULKAN,
        GpuBackend.CPU,
    ]


def test_provider_for_each_backend() -> None:
    for backend in GpuBackend:
        assert _provider_for(backend) is not None


# --- Stub providers are not selectable -------------------------------------


def test_directml_provider_not_available() -> None:
    assert DirectmlProvider().available() is False


def test_vulkan_provider_not_available() -> None:
    assert VulkanProvider().available() is False


def test_cpu_provider_always_available() -> None:
    assert CpuProvider().available() is True


# --- detect() through the REAL registry (not mocked) ----------------------


def _force_available(monkeypatch: pytest.MonkeyPatch, mapping: dict) -> None:
    """Patch each provider's ``available`` to a canned bool in ``mapping``."""
    for provider in BACKENDS:
        if provider.backend in mapping:
            monkeypatch.setattr(
                provider, "available", lambda _self=provider, v=mapping[provider.backend]: v
            )


@pytest.mark.asyncio
async def test_detect_returns_cpu_when_all_gpu_providers_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-GPU box: every GPU provider unavailable -> detect returns CPU."""
    _force_available(
        monkeypatch,
        {
            GpuBackend.CUDA: False,
            GpuBackend.ROCM: False,
            GpuBackend.DIRECTML: False,
            GpuBackend.VULKAN: False,
        },
    )
    assert await detect() == GpuBackend.CPU


@pytest.mark.asyncio
async def test_detect_returns_cuda_when_cuda_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_available(
        monkeypatch,
        {
            GpuBackend.CUDA: True,
            GpuBackend.ROCM: True,
            GpuBackend.DIRECTML: False,
            GpuBackend.VULKAN: False,
        },
    )
    # CUDA has priority 10 < ROCm 20, so CUDA wins even though ROCm is available.
    assert await detect() == GpuBackend.CUDA


@pytest.mark.asyncio
async def test_detect_returns_rocm_when_cuda_unavailable_but_rocm_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_available(
        monkeypatch,
        {
            GpuBackend.CUDA: False,
            GpuBackend.ROCM: True,
            GpuBackend.DIRECTML: False,
            GpuBackend.VULKAN: False,
        },
    )
    assert await detect() == GpuBackend.ROCM


# --- device_for mapping table ---------------------------------------------


@pytest.mark.parametrize(
    ("backend", "engine", "expected"),
    [
        (GpuBackend.CUDA, InferenceEngine.TORCH, "cuda"),
        (GpuBackend.CUDA, InferenceEngine.FASTER_WHISPER, "cuda"),
        (GpuBackend.CUDA, InferenceEngine.PYANNITE, "cuda"),
        (GpuBackend.CUDA, InferenceEngine.LLAMA_CPP, 0),
        (GpuBackend.ROCM, InferenceEngine.TORCH, "cuda"),
        (GpuBackend.ROCM, InferenceEngine.LLAMA_CPP, 0),
        (GpuBackend.DIRECTML, InferenceEngine.TORCH, "privateuseone"),
        (GpuBackend.DIRECTML, InferenceEngine.LLAMA_CPP, -1),
        (GpuBackend.VULKAN, InferenceEngine.LLAMA_CPP, "vulkan"),
        (GpuBackend.VULKAN, InferenceEngine.TORCH, "cpu"),
        (GpuBackend.CPU, InferenceEngine.TORCH, "cpu"),
        (GpuBackend.CPU, InferenceEngine.LLAMA_CPP, -1),
    ],
)
def test_device_for_mapping(
    backend: GpuBackend, engine: InferenceEngine, expected: str | int
) -> None:
    assert device_for(backend, engine) == expected


# --- burn_test defensive fallback for stubs --------------------------------


@pytest.mark.asyncio
async def test_burn_test_returns_cpu_probe_for_directml() -> None:
    """Stub provider's NotImplementedError is caught -> CPU probe (D-06)."""
    probe = await burn_test(GpuBackend.DIRECTML)
    assert probe.backend == GpuBackend.CPU
    assert probe.burn_test_ms is None
    assert probe.vram_total_mb is None


@pytest.mark.asyncio
async def test_burn_test_returns_cpu_probe_for_vulkan() -> None:
    probe = await burn_test(GpuBackend.VULKAN)
    assert probe.backend == GpuBackend.CPU


@pytest.mark.asyncio
async def test_burn_test_cpu_provider_returns_null_probe() -> None:
    probe = await burn_test(GpuBackend.CPU)
    assert probe.backend == GpuBackend.CPU
    assert probe.burn_test_ms is None