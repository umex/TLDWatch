"""Model API routes (Plan 02-02).

Six routes under ``/models``:

- ``GET /models`` -- list installed (on disk) + available (registry
  entries not yet installed) + the active :class:`ModelSet` (D-09 +
  override resolution).
- ``POST /models/{id}/download`` -- 202 Accepted; kicks off an
  ``asyncio.create_task`` that calls
  :func:`ModelManager.ensure_downloaded` (D-01). Returns
  ``{"task_id": "<uuid>", "status_url": "/models/{id}/status"}``.
- ``GET /models/{id}/status`` -- returns the current
  :class:`DownloadProgress` from the in-memory dict (default
  ``state="queued"`` when no task is running).
- ``GET /models/{id}/download-progress`` -- ``text/event-stream`` SSE
  (Phase 5 consumer); yields ``event: progress`` lines.
- ``POST /models/{id}/load`` -- calls ``manager.load(category, spec)``;
  maps the typed errors to HTTP codes (D-15 strict contract: typed
  errors in the manager, HTTP mapping here):
  ``VramBudgetExceeded`` -> 507, ``ConcurrentModelRefused`` -> 409
  (D-04), ``ModelGatedError`` -> 403, ``ModelIntegrityError`` -> 500.
- ``POST /models/{id}/unload`` -- 204 No Content, idempotent (D-03).

The ``id`` path param is resolved via :func:`app.models.registry.get_spec`
(raises :class:`KeyError` on unknown ids -- no path traversal, T-02-10)
and :func:`app.models.registry.get_category` for the category.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_settings
from app.models.diagnostics import ModelSet, ModelSpec
from app.models.manager import (
    ConcurrentModelRefused,
    DownloadProgress,
    DownloadTaskResponse,
    LoadedModel,
    ModelGatedError,
    ModelIntegrityError,
    ModelsListResponse,
    ModelManagerError,
    VramBudgetExceeded,
    get_manager,
)
from app.models.presets import active_model_set
from app.models.registry import REGISTRY, get_category, get_spec, list_specs
from app.models.settings import Settings
from app.storage.models_dir import spec_file_path

router = APIRouter(prefix="/models", tags=["models"])

# In-memory progress dict (the SSE generator + status endpoint read
# from it; the download task writes to it). Keyed by registry id.
_in_flight: dict[str, DownloadProgress] = {}


def _resolve(id: str) -> tuple[ModelSpec, "object"]:
    """Resolve ``id`` to ``(spec, category)`` or raise 404."""
    try:
        spec = get_spec(id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_model",
                "id": id,
                "available": sorted(REGISTRY.keys()),
            },
        ) from exc
    try:
        category = get_category(id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "unknown_model", "id": id}
        ) from exc
    return spec, category


@router.get("", response_model=ModelsListResponse)
async def list_models(
    settings: Settings = Depends(get_settings),
) -> ModelsListResponse:
    """Return the installed + available + active model set."""
    manager = get_manager()
    installed = manager.list_installed()
    installed_ids = {spec.repo_id for spec in installed}
    available: list[dict] = []
    for id, spec in list_specs():
        if spec.repo_id not in installed_ids:
            available.append({"id": id, "spec": spec})
    active = active_model_set(settings)
    return ModelsListResponse(
        installed=installed, available=available, active_set=active
    )


async def _run_download(
    spec: ModelSpec, category, id: str, settings: Settings
) -> None:
    """Background task: call ``ensure_downloaded`` and update ``_in_flight``.

    Polls the on-disk partial file size while the download runs so
    ``progress.bytes_done`` reflects byte-level progress (WR-02). HF
    Hub writes to ``<filename>.incomplete`` next to the target during
    download; we sum the target and any matching ``*.incomplete``
    files in the target's directory.
    """
    manager = get_manager()
    progress = _in_flight.setdefault(
        id,
        DownloadProgress(model_id=spec.repo_id, state="running"),
    )
    progress.state = "running"
    progress.bytes_total = spec.expected_size_bytes
    target = spec_file_path(settings, category, spec)

    async def _poll_bytes() -> None:
        import time

        while progress.state == "running":
            try:
                total = 0
                if target.exists():
                    total += target.stat().st_size
                parent = target.parent
                if parent.exists():
                    stem = target.name
                    for p in parent.glob(f"{stem}*.incomplete"):
                        try:
                            total += p.stat().st_size
                        except OSError:
                            pass
                    # huggingface_hub may stage under .cache/huggingface/download
                    cache_dl = parent / ".cache" / "huggingface" / "download"
                    if cache_dl.exists():
                        for p in cache_dl.glob(f"{stem}*.incomplete"):
                            try:
                                total += p.stat().st_size
                            except OSError:
                                pass
                progress.bytes_done = total
            except OSError:
                pass
            await asyncio.sleep(0.5)
            _ = time  # keep import local to the closure

    poll_task = asyncio.create_task(_poll_bytes())
    try:
        await manager.ensure_downloaded(spec, category)
        progress.state = "done"
        progress.bytes_done = spec.expected_size_bytes or progress.bytes_done
    except ModelGatedError as exc:
        progress.state = "failed"
        progress.message = f"gated: {exc.repo_id}"
    except ModelIntegrityError as exc:
        progress.state = "failed"
        progress.message = f"integrity: {exc.repo_id}"
    except ModelManagerError as exc:
        progress.state = "failed"
        progress.message = str(exc)
    except Exception as exc:  # noqa: BLE001
        progress.state = "failed"
        progress.message = str(exc)
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@router.post(
    "/{id}/download",
    response_model=DownloadTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def download_model(
    id: str,
    settings: Settings = Depends(get_settings),
) -> DownloadTaskResponse:
    """Kick off an async download for ``id`` (D-01 on-demand).

    Deduplicates in-flight downloads: if a task for ``id`` is already
    ``queued`` or ``running``, returns 409 instead of overwriting the
    progress entry and spawning a racing second background task.
    """
    spec, category = _resolve(id)
    existing = _in_flight.get(id)
    if existing is not None and existing.state in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "download_in_flight",
                "id": id,
                "state": existing.state,
                "status_url": f"/models/{id}/status",
            },
        )
    task_id = str(uuid.uuid4())
    _in_flight[id] = DownloadProgress(
        model_id=spec.repo_id,
        state="queued",
        bytes_total=spec.expected_size_bytes,
    )
    asyncio.create_task(_run_download(spec, category, id, settings))
    return DownloadTaskResponse(
        task_id=task_id, status_url=f"/models/{id}/status"
    )


@router.get("/{id}/status", response_model=DownloadProgress)
async def download_status(
    id: str,
    settings: Settings = Depends(get_settings),
) -> DownloadProgress:
    """Return the current :class:`DownloadProgress` for ``id``."""
    return _in_flight.get(
        id, DownloadProgress(model_id=id, state="queued")
    )


@router.get("/{id}/download-progress")
async def download_progress_sse(
    id: str,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """SSE stream of :class:`DownloadProgress` for ``id`` (Phase 5 consumer)."""

    async def event_generator():
        import time

        last_state = None
        last_bytes = None
        last_emit = 0.0
        heartbeat = 0.0
        while True:
            progress = _in_flight.get(id)
            if progress is not None:
                current_state = progress.state
                current_bytes = progress.bytes_done
                # Emit on state change, or on bytes_done change throttled
                # to >= 0.5s between frames (WR-02 byte-level progress).
                now = time.monotonic()
                state_changed = current_state != last_state
                bytes_changed = current_bytes != last_bytes
                if state_changed or (bytes_changed and now - last_emit >= 0.5):
                    payload = progress.model_dump_json()
                    yield f"event: progress\ndata: {payload}\n\n"
                    last_state = current_state
                    last_bytes = current_bytes
                    last_emit = now
                    if current_state in ("done", "failed"):
                        return
            # Heartbeat every ~5 seconds so a slow consumer does not
            # time out (SSE comment line).
            now = time.monotonic()
            if now - heartbeat > 5.0:
                yield ": ping\n\n"
                heartbeat = now
            await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{id}/load", response_model=LoadedModel)
async def load_model(
    id: str,
    settings: Settings = Depends(get_settings),
) -> LoadedModel:
    """Load ``id`` into VRAM (D-04 concurrent policy + SC-4 budget gate)."""
    spec, category = _resolve(id)
    manager = get_manager()
    try:
        return await manager.load(category, spec)
    except VramBudgetExceeded as exc:
        raise HTTPException(
            status_code=507,
            detail={
                "error": "vram_budget_exceeded",
                "category": exc.category.value,
                "needed_mb": exc.needed_mb,
                "available_mb": exc.available_mb,
            },
        ) from exc
    except ConcurrentModelRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "concurrent_refused",
                "loaded": exc.loaded_category.value,
                "requested": exc.requested_category.value,
                "fix": "set concurrent_models=true in settings",
            },
        ) from exc
    except ModelGatedError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "gated",
                "repo": exc.repo_id,
                "fix": "add HF token in settings",
            },
        ) from exc
    except ModelIntegrityError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "integrity", "repo": exc.repo_id},
        ) from exc


@router.post("/{id}/unload", status_code=status.HTTP_204_NO_CONTENT)
async def unload_model(
    id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """Unload ``id`` from VRAM (D-03 idempotent, 204 No Content)."""
    try:
        category = get_category(id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "unknown_model", "id": id}
        ) from exc
    manager = get_manager()
    await manager.unload(category)
    return None


__all__ = ["router"]