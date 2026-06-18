"""Diagnostics API: GPU re-detect + VRAM probe + HF token test (SC-1, D-05, D-06).

Three routes mounted under ``/diagnostics``:

- ``POST /diagnostics/gpu-burn`` — re-runs the two-stage detect + burn
  test and atomically updates ``settings.json`` with the new
  ``backend`` + ``backend_probe`` (D-04 Phase-1 atomic write). The
  in-memory state is swapped immediately (H1: only ``data_dir`` is
  restart-required; a re-detect is a hot-swap). Returns a typed
  :class:`GpuBurnResult`. Does NOT call ``apply_update`` (the detect
  result is a back-end-initiated write, not a user PATCH; D-08 —
  ``backend`` / ``backend_probe`` are NOT on
  :class:`UpdateSettingsRequest`).
- ``GET /diagnostics/vram`` — returns the current :class:`VRAMState`
  for the active backend (two-pool fix in :func:`probe_vram`).
- ``POST /diagnostics/test-hf-token`` — runs the four-state HF Hub
  HEAD shim (D-05, Pitfall 3). The helper never raises; the route
  maps ``rejected`` to 401 (token invalid) or 403 (gated terms) and
  returns 200 for ``skipped`` (including network errors) and ``ok``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import GpuBurnResult, HfTokenResult, VRAMState
from app.models import backend as backend_module
from app.models.hf_token import validate_token
from app.models.vram import get_manager_state, probe_vram
from app.settings import service as settings_service
from app.storage.atomic import atomic_write_json

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.post("/gpu-burn", response_model=GpuBurnResult)
async def gpu_burn() -> GpuBurnResult:
    """Re-run the two-stage detect + burn test and persist the result.

    Hot-swap (H1): the in-memory ``Settings.backend`` /
    ``Settings.backend_probe`` are swapped immediately and the on-disk
    ``settings.json`` is rewritten atomically (D-04 Phase-1 helper).
    No ``X-Restart-Required`` header (only ``data_dir`` is
    restart-required).
    """
    backend = await backend_module.detect()
    probe = await backend_module.burn_test(backend)

    existing = settings_service.current()
    new_settings = existing.model_copy(
        update={"backend": backend, "backend_probe": probe}
    )

    target_path = settings_service._State.path  # noqa: SLF001
    if target_path is None:
        from app.storage.fs import bootstrap_settings_path

        target_path = bootstrap_settings_path()

    # Atomic write of the full new settings (D-04 Phase-1 helper). The
    # pending slot is NOT used — the re-detect path is a hot-swap, not
    # a restart-required change.
    await atomic_write_json(target_path, new_settings.model_dump())
    settings_service.configure(new_settings)

    return GpuBurnResult(
        probe=probe,
        active_backend=backend,
        settings_written=True,
    )


@router.get("/vram", response_model=VRAMState)
def get_vram() -> VRAMState:
    """Return the current VRAM state for the active backend."""
    settings = settings_service.current()
    return probe_vram(settings.backend, get_manager_state())


@router.post("/test-hf-token", response_model=HfTokenResult)
async def test_hf_token() -> HfTokenResult:
    """Probe the configured HF token against the gated pyannote repo.

    Four-state contract (D-05, Pitfall 3):

    - ``skipped`` -> 200 (no token, OR HF Hub unreachable / network error)
    - ``ok`` -> 200 (token valid + gated terms accepted; ``user`` set)
    - ``rejected`` with ``reason="token invalid"`` -> 401
    - ``rejected`` with ``reason="model terms not accepted"`` -> 403

    The helper :func:`validate_token` never raises; the route maps the
    typed result to the HTTP code.
    """
    settings = settings_service.current()
    result = await validate_token(settings.hf_token)
    if result.status == "rejected":
        if result.reason == "token invalid":
            raise HTTPException(status_code=401, detail=result.model_dump())
        if result.reason == "model terms not accepted":
            raise HTTPException(status_code=403, detail=result.model_dump())
        # Any other rejected reason — surface as 400.
        raise HTTPException(status_code=400, detail=result.model_dump())
    return result


__all__ = ["router"]