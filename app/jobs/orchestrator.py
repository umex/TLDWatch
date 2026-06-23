"""run_job: the state-machine driver that walks a job through its stages.

Phase 4 plan 04-01. This is the spine every later phase plugs into as
"just add a stage" (D-12). The driver:

1. Calls :func:`app.jobs.resume.infer_resume_point` at the top so a
   re-entered job SKIPS stages whose file-as-truth check is already
   complete (Fix 4 -- re-entrant correctness). A crashed transcription
   leaves no ``transcript.json`` (the atomic write only fires at the
   end of the whole transcribe call), so the walker naturally
   re-transcribes from scratch (D-02).
2. Drives ``queued -> ingesting -> transcribing -> done`` via
   :func:`app.jobs.manifest.update_stage` (write-manifest-first /
   commit-DB-last). Stage completion is recorded ONLY AFTER the output
   file exists (Fix 4): publish ``stage_changed`` and run the work
   BEFORE calling ``update_stage("transcribed")``, and call
   ``update_stage("transcribed")`` only after ``transcript.json`` is
   written. Same for ``ingested``: validate ``source_path`` FIRST, then
   ``update_stage("ingested")``.
3. Runs the transcribe off-loop via
   ``loop.run_in_executor(None, functools.partial(transcribe_file, ...,
   progress_cb=..., cancel_flag=...))`` (Fix 3 -- ``run_in_executor``
   cannot take kwargs directly, so ``functools.partial`` wraps them).
4. Marshals per-chunk progress from the worker thread back to the
   asyncio loop via ``loop.call_soon_threadsafe(bus.publish, ...)``
   (T-04-thread). The ``cancel_flag`` is a ``threading.Event`` (NOT
   ``asyncio.Event``) so the asyncio side can set it without crossing
   loop boundaries; the chunker checks it at the next chunk boundary
   and raises :class:`JobCancelled` (D-06 cooperative cancel).
5. Graceful in-flight shutdown (Fix 3): the ``finally`` block awaits
   the in-flight executor future with a bounded timeout
   (``asyncio.wait_for(future, timeout=30.0)``) so the sync thread
   gets a chance to exit at the next chunk boundary BEFORE the model
   is unloaded. This prevents use-after-free / partial writes during
   lifespan teardown.
6. On :class:`JobCancelled`: ``cancel_job`` (DB-first + rmtree) +
   ``bus.publish({"type":"cancelled"})``. ``transcript.json`` is NOT
   written (``atomic_write_json`` only fires after the transcribe
   returns -- Pitfall 4).
7. On any other exception: ``mark_failed(session, job_id, str(exc))`` +
   ``bus.publish({"type":"failed","error":str(exc)})``; re-raise so the
   caller (the 04-02 worker) can log / surface the failure.

``_running`` is the module-level registry of in-flight cancel flags
keyed by ``job_id``; the 04-02 cancel route sets the flag to stop a
running job. ``_running.pop(job_id, None)`` in the ``finally`` block
keeps the registry clean.

Re-exports :class:`JobCancelled` for convenience so existing call sites
that imported it from here keep working; the SOURCE OF TRUTH is
:mod:`app.jobs.errors` (Fix 5).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from typing import Any, Callable

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.errors import JobCancelled  # re-export (source of truth: app.jobs.errors)
from app.jobs.manifest import read_manifest, update_stage
from app.jobs.progress import EventBus
from app.jobs.resume import infer_resume_point, is_stage_complete
from app.models.job import ManifestPatch
from app.models.settings import Settings
from app.models.stt.chunker import transcribe_file
from app.models.stt.protocol import STTAdapter, ChunkProgress
from app.storage.atomic import atomic_write_json
from app.storage.fs import job_dir, transcript_path

_log = logging.getLogger(__name__)

# Module-level registry of in-flight cancel flags keyed by job_id.
# The 04-02 cancel route looks up the flag for a running job and sets
# it so the chunker exits at the next chunk boundary (D-06).
_running: dict[str, threading.Event] = {}


async def run_job(
    settings: Settings,
    session_factory: async_sessionmaker,
    job_id: str,
    bus: EventBus | None = None,
    adapter: STTAdapter | None = None,
) -> None:
    """Drive ``job_id`` through ``queued -> ingesting -> transcribing -> done``.

    File-as-truth transitions via :func:`update_stage`; stage completion
    recorded only after the output file exists (Fix 4); re-entrant via
    :func:`infer_resume_point` at the top (Fix 4); cooperative cancel
    via a ``threading.Event`` checked at the chunk boundary (D-06);
    graceful in-flight shutdown via a bounded await on the executor
    future before model unload (Fix 3).

    :param settings: project settings (data_dir, backend, ...).
    :param session_factory: the engine's :class:`async_sessionmaker`
        (the orchestrator opens a short-lived session per stage
        transition -- mirrors :mod:`app.jobs.reconcile`).
    :param job_id: the job to drive.
    :param bus: optional :class:`EventBus` for progress / stage events.
        When ``None`` the events are not published (used by tests that
        only assert on DB / file state).
    :param adapter: optional :class:`STTAdapter` for the transcribing
        stage. Tests pass a :class:`tests._stt_fake.FakeAdapter`; the
        production path (``adapter=None``) loads the STT model via the
        model manager + builds a :class:`FasterWhisperAdapter` mirroring
        :mod:`app.cli.transcribe`.

    On :class:`JobCancelled` the job is cancelled (``cancel_job``) and
    the function returns normally. On any other exception the job is
    marked failed (``mark_failed``) and the exception is re-raised so
    the caller (the 04-02 worker) can log / surface it.
    """
    cancel_flag = threading.Event()
    _running[job_id] = cancel_flag
    loop = asyncio.get_running_loop()
    future: Any = None
    loaded_by_run = False  # True iff THIS run loaded the STT model (unload in finally)
    start_time = time.monotonic()
    last_progress_write: float = 0.0  # Fix 9 throttling (< =1/s)

    def _publish(event: dict) -> None:
        if bus is not None:
            bus.publish(job_id, event)

    async def _persist_progress(event: dict) -> None:
        """Throttled atomic progress.json write (Fix 9, Task 3).

        Reconnecting WS clients read ``progress.json`` on connect
        (04-03 WS handler) and see the latest percent / eta even if
        they missed the live events. Throttled to <=1/s to avoid disk
        churn on every chunk. The first event is always allowed through
        so a fast job still writes at least one snapshot (the 04-03
        reconnect contract).
        """
        nonlocal last_progress_write
        now = time.monotonic()
        # Throttle: allow the first event through, then gate subsequent
        # writes to one per second so a fast job still writes at least
        # one snapshot (the 04-03 reconnect contract).
        if last_progress_write > 0 and (now - last_progress_write) < 1.0:
            return
        last_progress_write = now
        from datetime import datetime

        snapshot = {
            "chunks_done": event["chunks_done"],
            "chunks_total": event["chunks_total"],
            "percent": event["percent"],
            "eta_s": event["eta_s"],
            "updated_at": datetime.now().isoformat(),
        }
        try:
            await atomic_write_json(
                job_dir(settings, job_id) / "progress.json", snapshot
            )
        except Exception:  # pragma: no cover - defensive logging only
            _log.warning("progress.json write failed for %s", job_id, exc_info=True)

    def _schedule_persist(event: dict) -> None:
        """Sync shim so ``call_soon_threadsafe`` can schedule the async write.

        ``call_soon_threadsafe`` requires a sync callable; this wraps the
        async ``_persist_progress`` in ``loop.create_task`` (which is
        safe to call from the loop thread -- ``call_soon_threadsafe``
        runs the shim ON the loop thread).
        """
        loop.create_task(_persist_progress(event))

    def _on_progress(p: ChunkProgress) -> None:
        """Sync progress callback invoked from the worker thread (Fix 3).

        Marshals the event back to the asyncio loop via
        ``call_soon_threadsafe`` (T-04-thread -- never touch the loop
        directly from off-loop). Computes percent + ETA (D-09 -- ETA
        hidden until ``chunks_done >= 2``), publishes the event to the
        bus, and schedules the throttled ``progress.json`` write (Fix 9).
        """
        percent = p.chunks_done / p.chunks_total if p.chunks_total > 0 else 0.0
        eta_s: float | None = None
        if p.chunks_done >= 2 and percent > 0:
            elapsed = time.monotonic() - start_time
            eta_s = elapsed / percent * (1.0 - percent)
        event = {
            "type": "progress",
            "chunks_done": p.chunks_done,
            "chunks_total": p.chunks_total,
            "percent": percent,
            "eta_s": eta_s,
            "chunk_start_s": p.chunk_start_s,
        }
        loop.call_soon_threadsafe(_publish, event)
        loop.call_soon_threadsafe(_schedule_persist, event)

    try:
        manifest = await read_manifest(settings, job_id)

        # Fix 4: resume walker at the top -- skip completed stages.
        resume_stage = infer_resume_point(settings, job_id, manifest)
        if resume_stage is None:
            # Every applicable stage is complete -- nothing to do.
            _log.info("run_job %s: resume walker says nothing to do", job_id)
            return
        _log.info("run_job %s: resume at %s", job_id, resume_stage)

        skip_ingested = is_stage_complete("ingested", settings, job_id, manifest)
        skip_transcribed = is_stage_complete("transcribed", settings, job_id, manifest)

        # --- Ingesting stage (D-01 local-only, D-04 reference-in-place) ---
        if not skip_ingested:
            _publish({"type": "stage_changed", "stage": "ingesting"})
            source_type = manifest.source_type
            if source_type == "youtube":
                # D-01 seam: the youtube branch is Phase 6, not Phase 4.
                raise NotImplementedError("youtube ingest is Phase 6")
            # Local (or None -- default to local for the MVP contract).
            sp = manifest.source_path
            if not sp:
                raise ValueError("source file missing or empty")
            p = _resolve_source(sp)
            if not p.exists() or p.stat().st_size == 0:
                raise ValueError("source file missing or empty")
            # Fix 4: completion AFTER the file check passes.
            async with session_factory() as session:
                await update_stage(
                    settings, session, job_id, "ingested",
                    ManifestPatch(source_path=str(p)),
                )
            manifest = await read_manifest(settings, job_id)

        # --- Transcribing stage ---
        if not skip_transcribed:
            _publish({"type": "stage_changed", "stage": "transcribing"})

            # Resolve / load the STT adapter (JIT at stage start, D-02).
            stt_adapter: STTAdapter
            if adapter is not None:
                # Test path: caller-provided fake / pre-loaded adapter.
                stt_adapter = adapter
            else:
                # Production path: mirror app/cli/transcribe.py.
                stt_adapter = await _load_stt_adapter(settings)
                loaded_by_run = True

            # Run transcribe off-loop (Fix 3 -- functools.partial wraps
            # the kwargs run_in_executor cannot take directly).
            source_path = manifest.source_path
            if source_path is None:
                raise ValueError("manifest.source_path is None at transcribe time")
            future = loop.run_in_executor(
                None,
                functools.partial(
                    transcribe_file,
                    stt_adapter,
                    source_path,
                    language=None,
                    job_id=job_id,
                    progress_cb=_on_progress,
                    cancel_flag=cancel_flag,
                ),
            )
            transcript = await future

            # Fix 4: transcript.json EXISTS now; record stage completion
            # ONLY AFTER the output file is on disk.
            await atomic_write_json(
                transcript_path(settings, job_id),
                transcript.model_dump(mode="json"),
            )
            async with session_factory() as session:
                await update_stage(
                    settings, session, job_id, "transcribed",
                    ManifestPatch(language=transcript.language),
                )
            async with session_factory() as session:
                await update_stage(settings, session, job_id, "done")
            _publish({"type": "done"})

        if resume_stage == "done":
            # CR-03 fix: a crash between update_stage("transcribed") and
            # update_stage("done") leaves transcript.json on disk (file
            # truth says transcribed is complete) but manifest.current_stage
            # != "done". infer_resume_point returns "done" in this window;
            # without this branch run_job would fall through both `if not
            # skip_*` blocks and exit without advancing -- the job stuck in
            # "transcribing" forever. Advance the derived done transition
            # here and publish the done event (same event the happy path
            # publishes at line 282).
            async with session_factory() as session:
                await update_stage(settings, session, job_id, "done")
            _publish({"type": "done"})
            _log.info("run_job %s: advanced to done via resume", job_id)

    except JobCancelled:
        _log.info("run_job %s: cancelled at chunk boundary", job_id)
        async with session_factory() as session:
            await _cancel_job(session, settings, job_id)
        _publish({"type": "cancelled"})
        # Do NOT re-raise -- cancel is an expected flow, not an error.
    except Exception as exc:
        _log.warning("run_job %s: failed: %s", job_id, exc)
        try:
            async with session_factory() as session:
                await _mark_failed(session, job_id, str(exc))
        except Exception:  # pragma: no cover - defensive logging only
            _log.exception("run_job %s: mark_failed itself failed", job_id)
        _publish({"type": "failed", "error": str(exc)})
        raise
    finally:
        # Fix 3: graceful in-flight shutdown. If the cancel flag was set,
        # give the sync worker thread a chance to exit at the next chunk
        # boundary BEFORE unloading the model. The bounded timeout
        # prevents an orphaned thread holding model references.
        if cancel_flag.is_set() and future is not None:
            try:
                await asyncio.wait_for(future, timeout=30.0)
            except (asyncio.TimeoutError, JobCancelled, Exception):  # noqa: BLE001
                # The future raised (cancel / crash) or timed out --
                # either way the thread is done or past our control.
                pass
        # Unload the model only if THIS run loaded it (mirror the CLI's
        # finally-block explicit-only unload, Phase 2 D-03).
        if loaded_by_run:
            try:
                from app.models.manager import ModelCategory, get_manager

                await get_manager().unload(ModelCategory.STT)
            except Exception:  # pragma: no cover - defensive logging only
                _log.exception("run_job %s: model unload failed", job_id)
        _running.pop(job_id, None)


def _resolve_source(source_path: str) -> "Any":
    """Resolve ``source_path`` to a :class:`Path` (D-04 reference-in-place)."""
    from pathlib import Path

    return Path(source_path)


async def _cancel_job(session: Any, settings: Settings, job_id: str) -> None:
    """Thin wrapper around :func:`app.jobs.cleanup.cancel_job` (imported lazily).

    Lazy import keeps the orchestrator's top-level import graph free of
    the cleanup module (which imports ``shutil`` + ``retry_windows`` --
    keeping it lazy makes the orchestrator importable in isolation for
    tests that only exercise the state machine).
    """
    from app.jobs.cleanup import cancel_job

    await cancel_job(session, settings, job_id)


async def _mark_failed(session: Any, job_id: str, error: str) -> None:
    """Thin wrapper around :func:`app.jobs.cleanup.mark_failed` (lazy import)."""
    from app.jobs.cleanup import mark_failed

    await mark_failed(session, job_id, error)


async def _load_stt_adapter(settings: Settings) -> STTAdapter:
    """Build + load the production STT adapter (mirrors :mod:`app.cli.transcribe`).

    Resolves the model spec from the persisted quality preset, ensures
    the model is downloaded, builds a :class:`FasterWhisperAdapter`, and
    calls ``load()`` (D-08 int8 verification). Returns the loaded
    adapter; the caller (``run_job``) is responsible for unloading it in
    its ``finally`` block (Phase 2 D-03 explicit-only).

    This path is NOT exercised by the orchestrator tests (they pass a
    fake adapter); it is exercised once 04-02 wires the worker. Kept
    here so the production path is colocated with the state machine.
    """
    from app.models.backend import InferenceEngine, device_for
    from app.models.diagnostics import ModelCategory
    from app.models.manager import ModelManager, configure_manager, get_manager
    from app.models.registry import get_category, get_spec
    from app.models.stt import FasterWhisperAdapter
    from app.settings.service import current

    live_settings = current()
    spec = get_spec(f"{live_settings.quality_preset.value}.stt")
    category = get_category(f"{live_settings.quality_preset.value}.stt")
    try:
        manager = get_manager()
    except RuntimeError:
        manager = ModelManager(live_settings)
        configure_manager(manager)
        manager = get_manager()
    model_path = await manager.ensure_downloaded(spec, category)
    await manager.load(category, spec)
    device = str(device_for(live_settings.backend, InferenceEngine.FASTER_WHISPER))
    compute_type = "int8_float16" if device == "cuda" else "int8"
    adapter = FasterWhisperAdapter(
        model_path=str(model_path), device=device, compute_type=compute_type
    )
    adapter.load()
    return adapter


__all__ = ["run_job", "JobCancelled", "_running"]