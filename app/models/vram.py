"""VRAM probe + the in-memory ``ManagerState`` singleton (SC-4, Pitfall 2).

``probe_vram`` returns a typed :class:`VRAMState` for the active
backend. The two-pool problem (Pitfall 2): ``torch`` holds one VRAM
pool (``torch.cuda.memory_allocated``) and ``llama.cpp`` holds a
separate pool tracked by ``ManagerState.live_vram_bytes``. The
"available" number must subtract BOTH from the GPU's free bytes, and
"used" must sum BOTH, or the 85% budget check (02-02) under-reports
and lets a second load OOM the GPU.

``ManagerState`` is a typed holder; :func:`get_manager_state` /
:func:`set_manager_state` are the accessors. The lifespan calls
``set_manager_state(ManagerState(live_vram_bytes={}))`` at boot so
``GET /diagnostics/vram`` returns ``loaded=[]`` from the start;
02-02's ``configure_manager`` swaps in the real manager's state.

``import torch`` and ``import psutil`` are INSIDE the function body
(NOT at module top) so a CPU-only test environment does not crash on
import. This mirrors the lazy-import discipline in
``app.storage.db`` for the engine listener.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from app.models.diagnostics import GpuBackend, LoadedModelInfo, ModelCategory, VRAMState
from app.util.time import utcnow_iso


class ManagerState(BaseModel):
    """In-memory holder for the model manager's live VRAM accounting.

    ``live_vram_bytes`` maps each loaded model category to the bytes it
    holds in the llama.cpp pool. 02-02's ``ModelManager`` updates this
    on every load/unload; ``probe_vram`` reads it to combine with
    ``torch.cuda.memory_allocated`` (the torch pool) for the two-pool
    fix (Pitfall 2).

    For 02-01, the ``loaded`` list in :class:`VRAMState` is built from
    this dict with a placeholder ``model_id = "<category>:unknown"``;
    02-02 plumbs the real ``model_id`` and ``loaded_at`` from a richer
    ``ManagerState``.
    """

    model_config = ConfigDict(extra="forbid")

    live_vram_bytes: dict[ModelCategory, int] = Field(default_factory=dict)


# Module-level singleton. The lifespan installs a fresh empty state at
# boot; 02-02's ``configure_manager`` swaps it for the manager's state.
_manager_state: ManagerState = ManagerState()


def get_manager_state() -> ManagerState:
    """Return the module-level :class:`ManagerState` singleton."""
    return _manager_state


def set_manager_state(state: ManagerState) -> None:
    """Install ``state`` as the module-level singleton.

    Called by the lifespan at boot (with an empty state) and by
    02-02's ``configure_manager`` (with the manager's live state).
    """
    global _manager_state
    _manager_state = state


def _loaded_list(manager_state: ManagerState) -> list[LoadedModelInfo]:
    """Build the ``loaded`` list from ``manager_state.live_vram_bytes``.

    02-01 placeholder: ``model_id = "<category>:unknown"`` because the
    manager is not wired in yet. 02-02 plumbs the real ``model_id`` and
    ``loaded_at`` from a richer ``ManagerState``.
    """
    now = utcnow_iso()
    return [
        LoadedModelInfo(
            category=category,
            model_id=f"{category.value}:unknown",
            vram_mb=int(bytes_ // 1024**2),
            loaded_at=now,
        )
        for category, bytes_ in manager_state.live_vram_bytes.items()
    ]


def probe_vram(backend: GpuBackend, manager_state: ManagerState) -> VRAMState:
    """Return a typed :class:`VRAMState` for the active backend.

    Per backend:

    - ``CUDA`` / ``ROCM``: lazy ``import torch``; if torch.cuda is not
      available at probe time, return a zeroed state (the route layer
      still returns 200). Read ``torch.cuda.mem_get_info(0)`` for
      ``free``/``total``; ``torch_alloc = torch.cuda.memory_allocated(0)``
      is the torch pool; ``llm_pool = sum(manager_state.live_vram_bytes.values())``
      is the llama.cpp pool (Pitfall 2 two-pool fix). ``used = torch_alloc
      + llm_pool``; ``available = free - llm_pool`` (torch already
      counts its own pool inside ``free``; llama.cpp does not).
    - ``CPU``: lazy ``import psutil``; report system virtual memory
      for ``total``/``available`` and the process RSS for ``used``.

    Never raises. A lazy-import failure or a torch error returns a
    zeroed state so ``GET /diagnostics/vram`` still responds 200.
    """
    if backend == GpuBackend.CPU:
        try:
            import psutil  # type: ignore[import-not-found]
        except Exception:
            return VRAMState(
                backend=backend,
                total_mb=0,
                available_mb=0,
                used_mb=0,
                loaded=[],
            )
        try:
            ps = psutil.virtual_memory()
            rss = psutil.Process(os.getpid()).memory_info().rss
            return VRAMState(
                backend=backend,
                total_mb=int(ps.total / 1024**2),
                available_mb=int(ps.available / 1024**2),
                used_mb=int(rss / 1024**2),
                loaded=[],
            )
        except Exception:
            return VRAMState(
                backend=backend,
                total_mb=0,
                available_mb=0,
                used_mb=0,
                loaded=[],
            )

    # CUDA / ROCm (HIP): the torch.cuda API serves both.
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return VRAMState(
            backend=backend,
            total_mb=0,
            available_mb=0,
            used_mb=0,
            loaded=_loaded_list(manager_state),
        )

    try:
        if not torch.cuda.is_available():
            return VRAMState(
                backend=backend,
                total_mb=0,
                available_mb=0,
                used_mb=0,
                loaded=_loaded_list(manager_state),
            )
        free, total = torch.cuda.mem_get_info(0)
        torch_alloc = torch.cuda.memory_allocated(0)
        llm_pool = sum(manager_state.live_vram_bytes.values())
        used = torch_alloc + llm_pool
        available = free - llm_pool
        return VRAMState(
            backend=backend,
            total_mb=int(total / 1024**2),
            available_mb=int(max(available, 0) / 1024**2),
            used_mb=int(used / 1024**2),
            loaded=_loaded_list(manager_state),
        )
    except Exception:
        return VRAMState(
            backend=backend,
            total_mb=0,
            available_mb=0,
            used_mb=0,
            loaded=_loaded_list(manager_state),
        )


__all__ = [
    "ManagerState",
    "get_manager_state",
    "probe_vram",
    "set_manager_state",
]