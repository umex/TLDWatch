"""Two-stage GPU backend detection (SC-1, D-06, D-08).

Stage 1: :func:`detect` is a CHEAP probe that picks the active backend
(``CUDA`` / ``ROCM`` / ``CPU``) by combining the installed torch wheel
tag (``+cu`` / ``+rocm``), ``nvidia-smi`` availability, ROCm env vars,
and a lazy ``torch.cuda.is_available()``. Every external call is
wrapped in ``try/except (TimeoutExpired, FileNotFoundError, OSError)``
so a missing tool is "not present," not an error (D-06 silent fallback).

Stage 2: :func:`burn_test` runs a REAL matmul kernel on the GPU to
confirm the path actually uses it (Pitfall 1 / 12 — "settings says
CUDA but jobs run on CPU"). On CPU it returns a typed probe with
``burn_test_ms=None`` and ``vram_total_mb=None`` (D-06 never refuses
to start). The burn test is the ONLY "is this real GPU" proof.

Both functions are ``async def`` so the lifespan can ``await`` them
inline (mirroring ``app.jobs.reconcile_all``). The torch calls are
synchronous inside; there is no real async torch API.

No ``torch`` / ``faster-whisper`` / ``llama-cpp-python`` / ``pyannote.audio``
import at module top: every GPU dependency is lazy-imported inside the
function body so a CPU-only test environment does not crash on import
(same discipline as ``app.storage.db`` uses for the engine listener).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from app.models.diagnostics import BackendProbe, GpuBackend

_log = logging.getLogger(__name__)

# Timeout for every external subprocess in :func:`detect`. A tool that
# has not responded in 3 seconds is treated as "not present" (D-06
# silent fallback), not an error.
_PROBE_TIMEOUT = 3


def _run_subprocess(args: list[str]) -> str | None:
    """Run ``args`` and return stdout, or ``None`` if the call failed.

    A missing executable (``FileNotFoundError``), a timeout, or any
    OS error is "the tool is not present on this machine" — we log at
    DEBUG and return ``None`` so the caller falls through to the next
    probe stage (D-06). Never raises.
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
    ``2.4.0+cu121`` indicates CUDA; ``2.4.0+rocm6.0`` indicates ROCm.
    A vanilla ``2.4.0`` (CPU wheel) returns ``None``.
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

    On ROCm, torch exposes the HIP stack THROUGH the ``torch.cuda`` API,
    so ``torch.cuda.is_available()`` is True and ``torch.version.hip`` is
    a non-None string. We check both to disambiguate from a CUDA wheel
    that happens to be installed alongside a ROCm one.
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


async def detect() -> GpuBackend:
    """Stage 1: cheap probe that picks the active backend.

    Ordered checks (first hit wins):

    1. ``pip show torch`` wheel variant (``+cu`` / ``+rocm``).
    2. ``nvidia-smi`` runs and reports a GPU  ->  CUDA candidate.
    3. ``ROCM_PATH`` / ``HIP_PATH`` env vars  ->  ROCm candidate.
    4. Lazy ``torch.cuda.is_available()`` confirms the CUDA candidate,
       or ``torch.version.hip`` confirms the ROCm candidate.
    5. Everything else  ->  ``GpuBackend.CPU`` (D-06 silent fallback).

    Never raises. A missing tool is "not present," not an error.
    """
    variant = _torch_wheel_variant()
    if variant == "+cu" and _nvidia_smi_present() and _torch_cuda_available():
        _log.info("detect: CUDA backend selected (wheel=+cu, nvidia-smi=ok)")
        return GpuBackend.CUDA
    if variant == "+rocm" and _torch_hip_present():
        _log.info("detect: ROCm backend selected (wheel=+rocm, torch.hip=ok)")
        return GpuBackend.ROCM
    if _rocm_env_present() and _torch_hip_present():
        _log.info("detect: ROCm backend selected (env hint + torch.hip=ok)")
        return GpuBackend.ROCM
    if _nvidia_smi_present() and _torch_cuda_available():
        _log.info("detect: CUDA backend selected (nvidia-smi + torch.cuda=ok)")
        return GpuBackend.CUDA
    _log.warning(
        "detect: no usable GPU path found; falling back to CPU (D-06 silent)"
    )
    return GpuBackend.CPU


async def burn_test(backend: GpuBackend) -> BackendProbe:
    """Stage 2: real-kernel run that confirms the GPU path actually works.

    For ``CUDA`` / ``ROCM`` (the HIP API is exposed via ``torch.cuda``):
    allocate two 1024x1024 tensors on ``cuda``, sync, time a matmul +
    ``.item()``, sync again. Record the wall time in ms, the device
    name, and the total VRAM in MB. If the kernel takes >5s, log a WARN
    ("may have fallen back to CPU"); the probe is still returned (D-06:
    the CPU-vs-GPU call is the user's, not ours).

    For ``CPU``: return a typed probe with ``burn_test_ms=None``,
    ``vram_total_mb=None``, ``device_name="CPU"`` (D-06 never refuses
    to start).

    Lazy ``import torch`` inside the function body so a CPU-only test
    environment does not crash on import. The torch calls are
    synchronous; the ``async def`` is for lifespan-await ergonomics.
    """
    if backend == GpuBackend.CPU:
        return BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            driver_version=None,
            vram_total_mb=None,
            burn_test_ms=None,
            notes="no GPU detected; running in CPU mode",
        )

    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        _log.warning(
            "burn_test: torch import failed for %s; returning CPU probe: %s",
            backend.value,
            exc,
        )
        return BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            driver_version=None,
            vram_total_mb=None,
            burn_test_ms=None,
            notes=f"torch import failed during burn_test; falling back to CPU: {exc}",
        )

    if not torch.cuda.is_available():
        _log.warning(
            "burn_test: torch.cuda.is_available() is False for %s; CPU probe",
            backend.value,
        )
        return BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            driver_version=None,
            vram_total_mb=None,
            burn_test_ms=None,
            notes="torch.cuda not available at burn_test time; CPU fallback",
        )

    try:
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
    except Exception as exc:
        _log.exception("burn_test: kernel run failed; returning CPU probe")
        return BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            driver_version=None,
            vram_total_mb=None,
            burn_test_ms=None,
            notes=f"burn_test kernel failed; CPU fallback: {exc}",
        )


__all__ = ["burn_test", "detect"]