"""Two-stage GPU backend detection (SC-1, D-06, D-08), provider-registry shape.

The backend selection is **open-closed**: each backend is a
:class:`BackendProvider` (``available`` / ``burn_test`` / ``device_for``) listed
in the :data:`BACKENDS` registry, sorted by ``priority``. :func:`detect` returns
the first provider whose ``available()`` passes, else ``GpuBackend.CPU``
(D-06 silent fallback). **Adding a new backend = one ``BackendProvider`` class +
one entry in :data:`BACKENDS`** — no edits to ``detect`` / ``burn_test`` /
``probe_vram`` dispatch. Flip a stub provider's ``available()`` to enable it.

Stage 1: :func:`detect` is a CHEAP probe that picks the active backend
(``CUDA`` / ``ROCM`` / ``CPU`` today; ``DIRECTML`` / ``VULKAN`` are stubs with
``available() == False``). Every external call is wrapped in
``try/except (TimeoutExpired, FileNotFoundError, OSError)`` so a missing tool is
"not present," not an error (D-06 silent fallback).

Stage 2: :func:`burn_test` runs a REAL matmul kernel on the GPU to confirm the
path actually uses it (Pitfall 1 / 12 — "settings says CUDA but jobs run on
CPU"). On CPU it returns a typed probe with ``burn_test_ms=None`` and
``vram_total_mb=None`` (D-06 never refuses to start).

:func:`device_for` resolves the device argument a given inference *package*
expects (torch / faster-whisper / llama-cpp / pyannote) for the active backend
— the seam Phase 3's STT/diarize/LLM adapters call instead of hardcoding
``"cpu"``.

Both ``detect`` / ``burn_test`` are ``async def`` so the lifespan can ``await``
them inline (mirroring ``app.jobs.reconcile_all``). The torch calls are
synchronous inside; there is no real async torch API.

No ``torch`` / ``faster-whisper`` / ``llama-cpp-python`` / ``pyannote.audio``
import at module top: every GPU dependency is lazy-imported inside the
function body so a CPU-only test environment does not crash on import
(same discipline as ``app.storage.db`` uses for the engine listener).

``probe_vram`` lives in :mod:`app.models.vram` (kept off this protocol to avoid a
circular import); enabling a *real* DirectML/Vulkan VRAM probe later is a second
edit there (see plan Trade-off B).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Protocol

from app.models.diagnostics import BackendProbe, GpuBackend, InferenceEngine

_log = logging.getLogger(__name__)

# Timeout for every external subprocess in the probes. A tool that has not
# responded in 3 seconds is treated as "not present" (D-06 silent fallback),
# not an error.
_PROBE_TIMEOUT = 3


def _run_subprocess(args: list[str]) -> str | None:
    """Run ``args`` and return stdout, or ``None`` if the call failed.

    A missing executable (``FileNotFoundError``), a timeout, or any OS error is
    "the tool is not present on this machine" — we log at DEBUG and return
    ``None`` so the caller falls through to the next probe stage (D-06). Never
    raises.
    """
    try:
        result = subprocess.run(
            args,
            timeout=_PROBE_TIMEOUT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _log.debug("subprocess %s not available: %s", args[0], exc)
        return None


def _torch_wheel_variant() -> str | None:
    """Return ``"+cu"``, ``"+rocm"``, or ``None`` from the installed torch wheel.

    Parses ``pip show torch``'s ``Version:`` line. A wheel tagged
    ``2.4.0+cu121`` indicates CUDA; ``2.4.0+rocm6.0`` indicates ROCm. A vanilla
    ``2.4.0`` (CPU wheel) returns ``None``.
    """
    out = _run_subprocess(["pip", "show", "torch"])
    if not out:
        return None
    for line in out.splitlines():
        if line.strip().lower().startswith("version:"):
            version = line.split(":", 1)[1].strip()
            if "+cu" in version:
                return "+cu"
            if "+rocm" in version:
                return "+rocm"
            return None
    return None


def _nvidia_smi_present() -> bool:
    """Return True if ``nvidia-smi`` runs and reports at least one GPU."""
    out = _run_subprocess(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
    )
    if not out:
        return False
    return any(line.strip() for line in out.splitlines())


def _rocm_env_present() -> bool:
    """Return True if a ROCm install is hinted by env vars."""
    return bool(os.environ.get("ROCM_PATH") or os.environ.get("HIP_PATH"))


def _torch_cuda_available() -> bool:
    """Lazy-import torch and return ``torch.cuda.is_available()``.

    Any import or runtime error is "torch not usable on this machine"
    (D-06 silent fallback) — return False.
    """
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent
        _log.debug("torch import failed: %s", exc)
        return False
    try:
        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception as exc:  # pragma: no cover - environment-dependent
        _log.debug("torch.cuda probe failed: %s", exc)
        return False


def _torch_hip_present() -> bool:
    """Lazy-import torch and return True if the HIP (ROCm) path is active.

    On ROCm, torch exposes the HIP stack THROUGH the ``torch.cuda`` API, so
    ``torch.cuda.is_available()`` is True and ``torch.version.hip`` is a
    non-None string. We check both to disambiguate from a CUDA wheel that
    happens to be installed alongside a ROCm one.
    """
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent
        _log.debug("torch import failed (HIP check): %s", exc)
        return False
    try:
        return bool(
            torch.cuda.is_available()
            and getattr(torch, "version", None) is not None
            and getattr(torch.version, "hip", None) is not None
        )
    except Exception as exc:  # pragma: no cover - environment-dependent
        _log.debug("torch HIP probe failed: %s", exc)
        return False


# --- Provider registry -----------------------------------------------------


class BackendProvider(Protocol):
    """One GPU backend's detection + device-resolution surface.

    ``available()`` is a CHEAP, synchronous, never-raising probe (lazy-import
    its packages; a missing tool is "not present"). ``detect`` iterates
    :data:`BACKENDS` by ``priority`` and returns the first provider whose
    ``available()`` is True. ``burn_test`` runs a real kernel proof.
    ``device_for(engine)`` resolves the device argument for a given inference
    package. ``probe_vram`` is intentionally NOT here (it lives in
    :mod:`app.models.vram` to avoid a circular import — see plan Trade-off B).
    """

    backend: GpuBackend
    priority: int  # lower = tried first by ``detect``

    def available(self) -> bool: ...
    async def burn_test(self) -> BackendProbe: ...
    def device_for(self, engine: InferenceEngine) -> str | int: ...


def _cpu_probe(notes: str = "no GPU detected; running in CPU mode") -> BackendProbe:
    """Build the typed CPU-shaped :class:`BackendProbe` (D-06 never refuses)."""
    return BackendProbe(
        backend=GpuBackend.CPU,
        device_name="CPU",
        driver_version=None,
        vram_total_mb=None,
        burn_test_ms=None,
        notes=notes,
    )


async def _torch_burn_test(backend: GpuBackend) -> BackendProbe:
    """Shared real-kernel burn body for CUDA + ROCm (HIP via ``torch.cuda``).

    Allocate two 1024x1024 tensors on ``cuda``, sync, time a matmul + ``.item()``,
    sync again. Record wall time (ms), device name, total VRAM (MB), and the
    driver version (CUDA vs HIP). WARN at >5s but still return the probe (D-06:
    the CPU-vs-GPU call is the user's, not ours). Any failure returns a CPU
    probe via the caller's ``except``.
    """
    import torch  # type: ignore[import-not-found]

    if not torch.cuda.is_available():
        _log.warning(
            "burn_test: torch.cuda.is_available() is False for %s; CPU probe",
            backend.value,
        )
        return _cpu_probe("torch.cuda not available at burn_test time; CPU fallback")

    a = torch.randn(1024, 1024, device="cuda")
    b = torch.randn(1024, 1024, device="cuda")
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    (a @ b).item()
    torch.cuda.synchronize()
    t1 = time.perf_counter()
    burn_ms = (t1 - t0) * 1000.0
    device_name = torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info(0)
    vram_total_mb = int(total / 1024**2)
    driver_version = (
        str(torch.version.cuda) if backend == GpuBackend.CUDA
        else str(getattr(torch.version, "hip", None))
    )
    notes = ""
    if burn_ms > 5000.0:
        notes = "kernel took >5s; may have fallen back to CPU"
        _log.warning("burn_test: %s", notes)
    _log.info(
        "burn_test: backend=%s device=%s burn_ms=%.2f vram_total_mb=%d",
        backend.value,
        device_name,
        burn_ms,
        vram_total_mb,
    )
    return BackendProbe(
        backend=backend,
        device_name=device_name,
        driver_version=driver_version,
        vram_total_mb=vram_total_mb,
        burn_test_ms=burn_ms,
        notes=notes,
    )


# The torch-device family: CUDA, ROCm (HIP via torch.cuda), DirectML
# (``privateuseone``), pyannote (runs on torch). Shared by all backends that
# resolve through the torch API.
_TORCH_FAMILY = frozenset(
    {InferenceEngine.TORCH, InferenceEngine.FASTER_WHISPER, InferenceEngine.PYANNITE}
)


class CudaProvider:
    """NVIDIA CUDA via a ``+cu`` torch wheel + ``nvidia-smi`` + ``torch.cuda``."""

    backend = GpuBackend.CUDA
    priority = 10

    def available(self) -> bool:
        # Preserve both current CUDA clauses: wheel-gated AND nvidia-smi-gated
        # (a box with a +cu wheel but nvidia-smi off PATH still matches the
        # second; both must survive the refactor — see plan Risk #1).
        if _torch_wheel_variant() == "+cu" and _nvidia_smi_present() and _torch_cuda_available():
            return True
        return bool(_nvidia_smi_present() and _torch_cuda_available())

    async def burn_test(self) -> BackendProbe:
        try:
            import torch  # type: ignore[import-not-found]
        except Exception as exc:
            _log.warning("burn_test: torch import failed for CUDA; CPU probe: %s", exc)
            return _cpu_probe(f"torch import failed during burn_test; CPU fallback: {exc}")
        return await _torch_burn_test(self.backend)

    def device_for(self, engine: InferenceEngine) -> str | int:
        if engine == InferenceEngine.LLAMA_CPP:
            return 0
        return "cuda"


class RocmProvider:
    """AMD ROCm via a ``+rocm`` torch wheel or ROCm env vars + ``torch.version.hip``.

    ROCm exposes the HIP stack THROUGH ``torch.cuda``, so the burn test and the
    torch-family device string are identical to CUDA (``"cuda"``). The
    divergence is only llama-cpp (HIP device index) and is refined in Phase 3.
    """

    backend = GpuBackend.ROCM
    priority = 20

    def available(self) -> bool:
        # Preserve both current ROCm clauses: wheel-gated AND env-gated.
        if _torch_wheel_variant() == "+rocm" and _torch_hip_present():
            return True
        return bool(_rocm_env_present() and _torch_hip_present())

    async def burn_test(self) -> BackendProbe:
        try:
            import torch  # type: ignore[import-not-found]
        except Exception as exc:
            _log.warning("burn_test: torch import failed for ROCm; CPU probe: %s", exc)
            return _cpu_probe(f"torch import failed during burn_test; CPU fallback: {exc}")
        return await _torch_burn_test(self.backend)

    def device_for(self, engine: InferenceEngine) -> str | int:
        if engine == InferenceEngine.LLAMA_CPP:
            return 0  # HIP device index; Phase 3 may refine to a HIP-specific flag.
        return "cuda"  # HIP is exposed via the torch.cuda API.


class DirectmlProvider:
    """DirectML stub (Windows/RDMA2 fallback option). Not selectable yet.

    ``available()`` is False so :func:`detect` never picks it; flip it to a
    lazy ``import torch_directml`` probe when a real build is wired (plan
    Trade-off B: also add a real VRAM branch in :mod:`app.models.vram`).
    """

    backend = GpuBackend.DIRECTML
    priority = 30

    def available(self) -> bool:
        return False

    async def burn_test(self) -> BackendProbe:
        raise NotImplementedError("DirectML backend is not implemented yet")

    def device_for(self, engine: InferenceEngine) -> str | int:
        if engine == InferenceEngine.LLAMA_CPP:
            return -1  # llama-cpp has no DirectML backend; -1 = CPU for that pkg.
        return "privateuseone"


class VulkanProvider:
    """Vulkan stub (via llama-cpp's ``--device vulkan``). Not selectable yet."""

    backend = GpuBackend.VULKAN
    priority = 40

    def available(self) -> bool:
        return False

    async def burn_test(self) -> BackendProbe:
        raise NotImplementedError("Vulkan backend is not implemented yet")

    def device_for(self, engine: InferenceEngine) -> str | int:
        if engine == InferenceEngine.LLAMA_CPP:
            return "vulkan"
        return "cpu"  # no torch Vulkan path yet


class CpuProvider:
    """The universal CPU fallback. Always available (D-06 never refuses)."""

    backend = GpuBackend.CPU
    priority = 99

    def available(self) -> bool:
        return True

    async def burn_test(self) -> BackendProbe:
        return _cpu_probe()

    def device_for(self, engine: InferenceEngine) -> str | int:
        if engine == InferenceEngine.LLAMA_CPP:
            return -1
        return "cpu"


# Priority-ordered registry. ``detect`` returns the first provider whose
# ``available()`` passes. Add a backend = add a class + one entry here.
BACKENDS: list[BackendProvider] = [
    CudaProvider(),
    RocmProvider(),
    DirectmlProvider(),
    VulkanProvider(),
    CpuProvider(),
]
BACKENDS.sort(key=lambda p: p.priority)


def _provider_for(backend: GpuBackend) -> BackendProvider | None:
    """Return the registered provider for ``backend``, or ``None``."""
    return next((p for p in BACKENDS if p.backend == backend), None)


async def detect() -> GpuBackend:
    """Stage 1: cheap probe that picks the active backend.

    Iterates :data:`BACKENDS` in priority order; returns the first provider
    whose ``available()`` is True. If none match, returns ``GpuBackend.CPU``
    (D-06 silent fallback). Never raises — a provider's ``available()`` that
    raises is logged at DEBUG and skipped.
    """
    for provider in BACKENDS:
        try:
            if provider.available():
                _log.info("detect: %s backend selected", provider.backend.value)
                return provider.backend
        except Exception as exc:  # pragma: no cover - provider must never raise
            _log.debug(
                "detect: provider %s available() raised: %s",
                provider.backend.value,
                exc,
            )
            continue
    _log.warning(
        "detect: no usable GPU path found; falling back to CPU (D-06 silent)"
    )
    return GpuBackend.CPU


async def burn_test(backend: GpuBackend) -> BackendProbe:
    """Stage 2: real-kernel run that confirms the GPU path actually works.

    Dispatches to the matching provider. Any failure (incl. ``NotImplementedError``
    from a stub, or a torch import failure on a CPU box) returns a CPU-shaped
    probe (D-06 never refuses to start). For ``CPU`` the provider returns the
    null probe directly.
    """
    provider = _provider_for(backend)
    if provider is None:
        _log.warning("burn_test: no provider for %s; CPU probe", backend.value)
        return _cpu_probe(f"unknown backend {backend.value!r}; CPU fallback")
    try:
        return await provider.burn_test()
    except Exception as exc:
        _log.exception("burn_test: provider %s raised; returning CPU probe", backend.value)
        return _cpu_probe(f"burn_test failed for {backend.value}: {exc}")


def device_for(backend: GpuBackend, engine: InferenceEngine) -> str | int:
    """Resolve the device argument ``engine`` expects on ``backend``.

    The Phase 3 seam: STT/diarize/LLM adapters call this instead of hardcoding
    ``"cpu"``. Returns a ``str`` (torch/faster-whisper/pyannote/vulkan) or an
    ``int`` llama-cpp device index (``0`` GPU, ``-1`` CPU). For an unknown
    backend, falls back to the CPU defaults.
    """
    provider = _provider_for(backend)
    if provider is None:
        return -1 if engine == InferenceEngine.LLAMA_CPP else "cpu"
    return provider.device_for(engine)


__all__ = ["burn_test", "detect", "device_for"]