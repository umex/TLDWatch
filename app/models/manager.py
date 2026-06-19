"""The :class:`ModelManager` -- lifecycle owner for every model on disk
and in VRAM (Plan 02-02).

Responsibilities (D-01 on-demand download, D-03 explicit-only unload,
D-04 refuse-then-caller-unloads):

- ``ensure_downloaded(spec, category)`` -- lazy-import
  ``huggingface_hub.hf_hub_download`` (the library's built-in
  ``<blob>.incomplete`` + Range-header resume is the resume
  mechanism), resolve the target via
  :func:`app.storage.models_dir.spec_file_path`, fast-path when the
  file already exists at the expected size, verify SHA256 when set
  (bounded retry: 1 re-download, no infinite loop -- Pitfall 4), and
  wrap ``GatedRepoError`` -> :class:`ModelGatedError` (Pitfall 3).
- ``load(category, spec)`` -- re-read settings via a factory so a
  PATCH to ``vram_budget_fraction`` / ``concurrent_models`` is picked
  up without a restart (H1 hot-swap); enforce D-04
  (``concurrent_models=False`` -> refuse a second load with
  :class:`ConcurrentModelRefused`); probe VRAM via
  :func:`app.models.vram.probe_vram` (Pitfall 2 two-pool fix); enforce
  the 85% budget gate (SC-4) -> :class:`VramBudgetExceeded`; record
  the reservation in ``ManagerState.live_vram_bytes`` +
  ``loaded_meta``; emit a structured per-model INFO log line (SC-2).
- ``unload(category)`` -- idempotent (D-03 explicit-only; no timer).
- ``unload_all()`` -- snapshot then unload each (lifespan teardown).
- ``verify`` / ``list_installed`` / ``currently_loaded``.

Phase 2 does NOT instantiate a faster-whisper / llama-cpp / pyannote
model -- ``load`` is a typed VRAM reservation. The real weight
loading happens inside the Phase 3 / 7 / 8 adapters; the manager
owns the lifecycle (reservation + unload), the adapters own the
inference.

The typed error hierarchy (5 classes) is the boundary between the
manager and the route layer (D-15 strict contract: typed errors
here, HTTP mapping in :mod:`app.api.routes_models`).
``huggingface_hub`` is imported ONLY inside ``ensure_downloaded`` (the
boundary check ``grep -rE "from huggingface_hub" app/`` matches only
``app/models/manager.py`` and ``app/models/hf_token.py``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict

from app.models.diagnostics import ModelCategory, ModelSet, ModelSpec
from app.models.registry import REGISTRY
from app.models.settings import Settings
from app.models.vram import ManagerState, set_manager_state, probe_vram
from app.settings.service import current
from app.storage.models_dir import spec_file_path
from app.util.time import utcnow_iso

_log = logging.getLogger(__name__)


# --- Typed error hierarchy (5 classes; route layer maps to HTTP codes) ------


class ModelManagerError(Exception):
    """Base for all :class:`ModelManager` typed errors."""


class VramBudgetExceeded(ModelManagerError):
    """The model would push past ``vram_budget_fraction * total_mb`` (SC-4).

    Route maps to 507.
    """

    def __init__(self, category: ModelCategory, needed_mb: int, available_mb: int) -> None:
        self.category = category
        self.needed_mb = needed_mb
        self.available_mb = available_mb
        super().__init__(
            f"vram budget exceeded for {category.value}: needed {needed_mb} MB, "
            f"available {available_mb} MB"
        )


class ConcurrentModelRefused(ModelManagerError):
    """A second load was requested with ``concurrent_models=False`` (D-04, SC-5).

    Route maps to 409.
    """

    def __init__(
        self,
        loaded_category: ModelCategory,
        requested_category: ModelCategory,
    ) -> None:
        self.loaded_category = loaded_category
        self.requested_category = requested_category
        super().__init__(
            f"concurrent model refused: {loaded_category.value} is resident, "
            f"cannot load {requested_category.value} (set concurrent_models=true "
            f"in settings)"
        )


class ModelGatedError(ModelManagerError):
    """The HF repo is gated and the configured token cannot access it (Pitfall 3).

    Route maps to 403 with the ``"add HF token in settings"`` fix.
    """

    def __init__(self, repo_id: str) -> None:
        self.repo_id = repo_id
        super().__init__(f"gated repo: {repo_id}")


class ModelIntegrityError(ModelManagerError):
    """The downloaded file's SHA256 did not match ``spec.expected_sha256``.

    Route maps to 500.
    """

    def __init__(self, repo_id: str, expected_sha: str, got_sha: str) -> None:
        self.repo_id = repo_id
        self.expected_sha = expected_sha
        self.got_sha = got_sha
        super().__init__(
            f"model integrity error for {repo_id}: expected sha256 {expected_sha}, "
            f"got {got_sha}"
        )


# --- Response / progress models --------------------------------------------


class LoadedModel(BaseModel):
    """One model currently resident in VRAM (the load() return value)."""

    model_config = ConfigDict(extra="forbid")

    category: ModelCategory
    model_id: str
    spec: ModelSpec
    vram_bytes: int
    loaded_at: str


class DownloadProgress(BaseModel):
    """Progress of an async download (read by the status + SSE routes)."""

    model_id: str
    bytes_done: int = 0
    bytes_total: int | None = None
    state: Literal["queued", "running", "verifying", "done", "failed", "resuming"] = (
        "queued"
    )
    message: str | None = None


class ModelsListResponse(BaseModel):
    """Response of ``GET /models`` (installed + available + active_set)."""

    installed: list[ModelSpec]
    available: list[dict]  # list of {"id": str, "spec": ModelSpec}
    active_set: ModelSet


class DownloadTaskResponse(BaseModel):
    """Response of ``POST /models/{id}/download`` (202 Accepted)."""

    task_id: str
    status_url: str


# --- Per-category VRAM overhead multipliers (RESEARCH) ----------------------
#
# ``expected_size_bytes`` is the file size on disk; the in-VRAM footprint
# is larger because of CUDA context, KV cache, etc. The multipliers are
# per-category heuristics from RESEARCH.md (1.2 for LLM, 1.5 for STT).
# Diarize uses 1.2 (Pyannote is comparable to the LLM pool size).


_VRAM_OVERHEAD: dict[ModelCategory, float] = {
    ModelCategory.LLM: 1.2,
    ModelCategory.STT: 1.5,
    ModelCategory.DIARIZE: 1.2,
}


def _sha256_of_file(path: Path) -> str:
    """Compute the SHA256 hex digest of ``path`` (streaming, never loads all)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_token() -> str | None:
    """Read the configured HF token (decoded from base64 on-disk form, D-05).

    Reads ``current().hf_token``; the ``Settings`` field_validator already
    decodes the base64 on load, so this returns the cleartext token (or
    ``None`` if not configured).
    """
    try:
        return current().hf_token
    except Exception:
        return None


# --- The manager -----------------------------------------------------------


class ModelManager:
    """Owns the lifecycle of every model file on disk and in VRAM.

    Built once in the lifespan (:func:`configure_manager`) after the
    settings are fully populated. The ``settings_factory`` callable lets
    the manager re-read settings on every ``load`` call so a PATCH to
    ``vram_budget_fraction`` or ``concurrent_models`` is picked up
    without a restart (H1 hot-swap).
    """

    def __init__(
        self,
        settings: Settings,
        settings_factory: Callable[[], Settings] | None = None,
    ) -> None:
        self._settings = settings
        self._state = ManagerState()
        self._settings_factory = settings_factory or (lambda: current())

    @property
    def state(self) -> ManagerState:
        """Expose the live :class:`ManagerState` (read by routes / diagnostics)."""
        return self._state

    async def ensure_downloaded(
        self, spec: ModelSpec, category: ModelCategory
    ) -> Path:
        """Download ``spec`` for ``category`` if not already on disk (D-01).

        Lazy-import ``huggingface_hub.hf_hub_download`` inside the body
        (boundary check -- only this module + ``hf_token.py`` import
        ``huggingface_hub``). The download is OFFLOADED to a worker
        thread via ``asyncio.to_thread`` so the event loop stays
        responsive while the (synchronous, potentially long-running)
        download runs -- this is the SC-3 fix that restores WR-01 (409
        duplicate-in-flight), WR-02 (live SSE heartbeat + byte-level
        progress), and concurrent request handling.

        Resume path: we FORCE the classic non-Xet download path so the
        library's built-in ``<blob>.incomplete`` + HTTP Range-header
        resume mechanism applies (the one the
        ``_poll_bytes`` scanner in ``routes_models.py`` globs for). The
        Xet backend stages partial bytes in a different location that
        our scanner does not see, and on restart re-fetches from zero
        -- HW-09 resume-after-crash was broken for Xet downloads. We
        force the classic path two ways, belt-and-suspenders:

        - Pass ``hf_xet=False`` to ``hf_hub_download`` when the
          installed ``huggingface_hub`` version supports that kwarg
          (added in 0.26+; detected via ``inspect.signature``).
        - Set ``HF_HUB_DISABLE_XET=1`` in ``os.environ`` around the
          call (restored afterwards) -- effective on versions that
          read the env var, a harmless no-op on versions that do not.

        We pass ``force_download=False`` (the default) so a partial
        file is resumed, NOT re-fetched from zero.

        Fast-path: if the target exists at the expected size, return it.
        Corrupt fast-path: if the target exists, the SHA is set, and the
        SHA does not match, delete the file and re-download once
        (bounded retry -- Pitfall 4, no infinite loop).
        """
        target = spec_file_path(self._settings, category, spec)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Size fast-path: already fully downloaded.
        if (
            target.exists()
            and spec.expected_size_bytes is not None
            and target.stat().st_size == spec.expected_size_bytes
            and spec.expected_sha256 is None
        ):
            return target

        # Corrupt-SHA fast-path: if the target exists and a SHA is set,
        # verify it. On MATCH, return the cached file early so a valid
        # download is NOT re-fetched (and works offline) -- WR-06. On
        # mismatch, delete + re-download once (bounded retry).
        if (
            target.exists()
            and spec.expected_sha256 is not None
            and target.stat().st_size > 0
        ):
            if _sha256_of_file(target) == spec.expected_sha256:
                return target
            _log.warning(
                "corrupt model file at %s (sha mismatch); re-downloading",
                target,
            )
            try:
                target.unlink()
            except OSError:
                pass

        from huggingface_hub import hf_hub_download  # type: ignore[import-not-found]
        from huggingface_hub.errors import (  # type: ignore[import-not-found]
            GatedRepoError,
            RepositoryNotFoundError,
        )

        token = _get_token()
        # Use the target's basename as the download filename so it
        # matches ``spec_file_path`` exactly -- including the
        # ``<sanitized_repo_id>.bin`` fallback used when ``spec.file``
        # is None (e.g. ``small.stt`` -> ``Systran--faster-whisper-small.bin``).
        # Without this, the download writes to ``model.bin`` while the
        # size fast-path + the ``_poll_bytes`` scanner look for the
        # spec-derived name, so resume + byte progress silently break
        # for every spec with ``file=None`` (Rule 1 fix found by the
        # new live SSE test).
        filename = target.name
        revision = spec.revision or "main"

        # Detect whether the installed huggingface_hub supports the
        # ``hf_xet`` kwarg (added in 0.26+). On older versions we fall
        # back to the ``HF_HUB_DISABLE_XET`` env var alone.
        import inspect

        try:
            _supports_hf_xet = "hf_xet" in inspect.signature(
                hf_hub_download
            ).parameters
        except (TypeError, ValueError):
            _supports_hf_xet = False

        def _download_kwargs() -> dict:
            kw = {
                "repo_id": spec.repo_id,
                "filename": filename,
                "revision": revision,
                "local_dir": str(target.parent),
                "token": token,
            }
            if _supports_hf_xet:
                kw["hf_xet"] = False
            return kw

        # Force the classic non-Xet download path so the
        # ``<blob>.incomplete`` + HTTP Range resume mechanism the
        # ``_poll_bytes`` scanner assumes actually applies (HW-09).
        _prev_xet = os.environ.get("HF_HUB_DISABLE_XET")
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        try:
            try:
                await asyncio.to_thread(hf_hub_download, **_download_kwargs())
            except GatedRepoError as exc:
                raise ModelGatedError(spec.repo_id) from exc
            except RepositoryNotFoundError as exc:
                raise ModelManagerError(
                    f"repository not found: {spec.repo_id}"
                ) from exc

            # Post-download SHA verify (bounded: 1 re-download attempt).
            if spec.expected_sha256 is not None:
                if not target.exists():
                    raise ModelManagerError(
                        f"download succeeded but target file is missing: {target}"
                    )
                got = _sha256_of_file(target)
                if got != spec.expected_sha256:
                    # One bounded retry: delete + re-download + re-verify.
                    _log.warning(
                        "post-download sha mismatch for %s; retrying once",
                        spec.repo_id,
                    )
                    try:
                        target.unlink()
                    except OSError:
                        pass
                    try:
                        await asyncio.to_thread(
                            hf_hub_download, **_download_kwargs()
                        )
                    except GatedRepoError as exc:
                        raise ModelGatedError(spec.repo_id) from exc
                    except RepositoryNotFoundError as exc:
                        raise ModelManagerError(
                            f"repository not found: {spec.repo_id}"
                        ) from exc
                    got = _sha256_of_file(target)
                    if got != spec.expected_sha256:
                        raise ModelIntegrityError(
                            spec.repo_id, spec.expected_sha256, got
                        )
        finally:
            # Restore the prior env state (unset if it was absent).
            if _prev_xet is None:
                os.environ.pop("HF_HUB_DISABLE_XET", None)
            else:
                os.environ["HF_HUB_DISABLE_XET"] = _prev_xet

        return target

    async def load(
        self, category: ModelCategory, spec: ModelSpec
    ) -> LoadedModel:
        """Reserve VRAM for ``category`` using ``spec`` (SC-4, D-04, SC-2).

        Re-reads settings via the factory so a PATCH to
        ``vram_budget_fraction`` / ``concurrent_models`` is picked up
        without a restart (H1 hot-swap).

        Checks (in order):

        1. Concurrent policy (D-04): if a model is already resident and
           ``concurrent_models=False``, refuse with
           :class:`ConcurrentModelRefused` (the caller must unload
           first -- auto-swap is a Phase 4 follow-up).
        2. VRAM budget (SC-4, Pitfall 2): probe VRAM (two-pool fix),
           compute the expected in-VRAM footprint with the per-category
           overhead multiplier, and refuse with
           :class:`VramBudgetExceeded` if it would push past
           ``vram_budget_fraction * total_mb``.

        On success: record the reservation in
        ``self._state.live_vram_bytes`` + ``loaded_meta`` and emit a
        structured INFO log line (SC-2). Phase 2 does NOT instantiate
        the real model -- the load is a typed VRAM reservation; the
        Phase 3 / 7 / 8 adapters own the inference.
        """
        settings = self._settings_factory()

        # 1. Concurrent policy (D-04).
        live = list(self._state.live_vram_bytes.keys())
        if live and not settings.concurrent_models:
            raise ConcurrentModelRefused(
                loaded_category=live[0],
                requested_category=category,
            )

        # 2. VRAM budget (SC-4, Pitfall 2 two-pool fix).
        vram = probe_vram(settings.backend, self._state)
        expected_mb = (spec.expected_size_bytes or 0) / 1024**2
        expected_mb *= _VRAM_OVERHEAD.get(category, 1.2)
        budget_mb = vram.total_mb * settings.vram_budget_fraction
        available_for_new = budget_mb - vram.used_mb
        if vram.total_mb > 0 and (vram.used_mb + expected_mb) > budget_mb:
            raise VramBudgetExceeded(
                category=category,
                needed_mb=int(expected_mb),
                available_mb=int(max(available_for_new, 0)),
            )

        # Record the reservation.
        vram_bytes = int(expected_mb * 1024**2)
        loaded = LoadedModel(
            category=category,
            model_id=spec.repo_id,
            spec=spec,
            vram_bytes=vram_bytes,
            loaded_at=utcnow_iso(),
        )
        self._state.live_vram_bytes[category] = vram_bytes
        self._state.loaded_meta[category] = loaded

        # SC-2: structured per-model INFO log line (JSON-shaped so a
        # future diagnostics panel can parse it).
        _log.info(
            json.dumps(
                {
                    "event": "model_loaded",
                    "category": category.value,
                    "model_id": spec.repo_id,
                    "expected_vram_mb": int(expected_mb),
                    "measured_vram_mb_after_load": int(vram.used_mb + expected_mb),
                    "total_vram_mb": int(vram.total_mb),
                    "available_vram_mb_after_load": int(
                        max(vram.available_mb - expected_mb, 0)
                    ),
                },
                sort_keys=True,
            )
        )
        return loaded

    async def unload(self, category: ModelCategory) -> None:
        """Idempotent unload (D-03 explicit-only; no timer).

        Clears ``live_vram_bytes`` + ``loaded_meta`` for ``category`` if
        present; returns ``None`` either way. A second unload for a
        category that is not resident is a no-op.
        """
        if category in self._state.live_vram_bytes:
            self._state.live_vram_bytes.pop(category, None)
            self._state.loaded_meta.pop(category, None)
            _log.info(
                json.dumps(
                    {"event": "model_unloaded", "category": category.value},
                    sort_keys=True,
                )
            )

    async def unload_all(self) -> None:
        """Snapshot then unload each (lifespan teardown)."""
        for category in list(self._state.live_vram_bytes.keys()):
            await self.unload(category)

    def currently_loaded(self) -> list[LoadedModel]:
        """Return the list of :class:`LoadedModel` records currently resident."""
        return list(self._state.loaded_meta.values())

    async def verify(self, spec: ModelSpec, category: ModelCategory) -> bool:
        """Return ``True`` if the on-disk file matches ``spec.expected_sha256``.

        ``True`` if the SHA matches OR ``spec.expected_sha256 is None``
        (no integrity check configured). ``False`` on mismatch. Does NOT
        raise -- the caller decides what to do with a ``False``.
        """
        target = spec_file_path(self._settings, category, spec)
        if not target.exists():
            return False
        if spec.expected_sha256 is None:
            return True
        return _sha256_of_file(target) == spec.expected_sha256

    def list_installed(self) -> list[ModelSpec]:
        """Return the registry specs whose target file exists on disk."""
        installed: list[ModelSpec] = []
        # The category is derived from the registry id (``<preset>.<category>``).
        for id, spec in REGISTRY.items():
            category_short = id.rpartition(".")[2]
            from app.models.registry import _CATEGORY_SHORTS  # noqa: PLC0415

            category = _CATEGORY_SHORTS.get(category_short)
            if category is None:
                continue
            target = spec_file_path(self._settings, category, spec)
            if target.exists():
                installed.append(spec)
        return installed


# --- Module-level singleton (mirrors app.settings.service) ------------------

_manager: ModelManager | None = None


def get_manager() -> ModelManager:
    """Return the configured :class:`ModelManager`.

    Raises :class:`RuntimeError` if not configured (mirrors
    :func:`app.settings.service.current`).
    """
    if _manager is None:
        raise RuntimeError(
            "model manager not configured (lifespan not installed)"
        )
    return _manager


def configure_manager(manager: ModelManager | None) -> None:
    """Install ``manager`` as the module-level singleton.

    Also installs ``manager._state`` as the
    :func:`app.models.vram.set_manager_state` singleton so
    ``GET /diagnostics/vram`` sees the live ``loaded_meta``. Passing
    ``None`` clears the singleton AND resets the manager state (used by
    the test fixture cleanup).
    """
    global _manager
    _manager = manager
    if manager is not None:
        set_manager_state(manager._state)  # noqa: SLF001
    else:
        # Reset to an empty state so a subsequent test boot starts clean.
        set_manager_state(ManagerState())


__all__ = [
    "ConcurrentModelRefused",
    "DownloadProgress",
    "DownloadTaskResponse",
    "LoadedModel",
    "ModelGatedError",
    "ModelIntegrityError",
    "ModelManager",
    "ModelManagerError",
    "ModelsListResponse",
    "VramBudgetExceeded",
    "configure_manager",
    "get_manager",
]