"""Tests for :mod:`app.jobs.orchestrator` -- the run_job state-machine driver.

Phase 4 plan 04-01. Wave 0 stubs (TDD RED-first):

- ``test_state_machine`` (Task 2 GREEN): a submitted job moves
  ``queued -> ingesting -> transcribing -> done``; the transcript
  exists at ``transcript_path`` and parses as a :class:`Transcript`.
- ``test_restart_rejoin`` (Task 2 GREEN): a job that "crashes" during
  transcribing (no ``transcript.json``) re-enters at transcribing via
  :func:`infer_resume_point` and re-transcribes from scratch (D-02).
- ``test_heartbeat_during_transcribing`` (Task 3 GREEN, Fix 2): a long
  transcription with refreshed ``progress.json`` is NOT marked stale by
  :func:`is_stale` even though wall-clock-equivalent time exceeds the
  10-min threshold -- the watchdog sees the fresh ``progress.json``
  mtime because ``_STAGE_FILE_NAMES`` now includes it.
- ``test_progress_snapshot_persisted`` (Task 3 GREEN, Fix 9): after a
  run_job, ``progress.json`` exists at ``job_dir/progress.json`` and
  contains ``chunks_done`` / ``chunks_total`` / ``percent`` / ``eta_s``
  / ``updated_at``.

These stubs import from ``app.jobs.orchestrator`` which does not exist
yet -- Task 2 creates ``run_job``. Until then pytest collection fails
RED on the import (the TDD RED gate).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.jobs.errors import JobCancelled  # noqa: F401  (Task 1a contract)
from app.jobs.manifest import empty_manifest, read_manifest, write_manifest
from app.jobs.orchestrator import run_job  # RED until Task 2
from app.jobs.progress import EventBus
from app.jobs.resume import infer_resume_point
from app.jobs.service import create_job, get_job
from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.models.transcript import Transcript
from app.storage.fs import ensure_job_dir, job_dir, transcript_path
from tests._stt_fake import FakeAdapter


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_data_dir / "data"),
        backend=GpuBackend.CPU,
        run_worker=False,
    )


async def _session_factory(settings: Settings):
    """Build a session factory against the project's engine + migrations.

    Mirrors the lifespan's ``make_engine`` / ``make_sessionmaker`` +
    ``apply_migrations`` path so the orchestrator tests get a real
    ``jobs`` table without spinning up the whole FastAPI app.
    """
    from app.storage.db import apply_migrations, make_engine, make_sessionmaker

    engine = make_engine(settings)
    await apply_migrations(engine)
    return make_sessionmaker(engine)


@pytest.mark.asyncio
async def test_state_machine(tmp_data_dir: Path) -> None:
    """A submitted job moves queued -> ingesting -> transcribing -> done.

    A FakeAdapter returning a 2-segment Transcript is wired through
    ``run_job``; after the call the DB row's ``status == "done"``,
    ``current_stage == "done"``, and ``transcript.json`` exists at
    ``transcript_path`` and parses as a :class:`Transcript`.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    # Create a local-source job (D-04 reference-in-place -- no copy).
    async with sf() as session:
        # Write a real source file the orchestrator validates.
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        # Patch the manifest to carry a source_path pointing at a real
        # non-empty file in the job dir (D-04: reference in place).
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        # Reflect source_path on the DB row so get_job sees it.
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # FakeAdapter: 2-segment transcript (fast path, single call).
    fake = FakeAdapter()
    bus = EventBus()

    await run_job(s, sf, job_id, bus=bus, adapter=fake)

    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "done"
    assert row.current_stage == "done"

    tpath = transcript_path(s, job_id)
    assert tpath.exists(), "transcript.json must exist after run_job"
    transcript = Transcript.model_validate_json(tpath.read_text(encoding="utf-8"))
    assert transcript.job_id == job_id
    assert len(transcript.segments) >= 1


@pytest.mark.asyncio
async def test_restart_rejoin(tmp_data_dir: Path) -> None:
    """A crashed transcribe (no transcript.json) re-transcribes from scratch (D-02).

    Run run_job to ingesting, "crash" by raising before transcribing,
    re-invoke run_job -- infer_resume_point re-enters at transcribing
    and the job completes (no transcript.json -> re-transcribes whole).
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # First run: use a fake that raises mid-transcribing (after ingesting
    # recorded, before transcript.json is written). The simplest way to
    # "crash during transcribing" is to pass an adapter whose transcribe
    # raises -- run_job marks failed, but we then re-invoke with a
    # healthy adapter and the resume walker re-enters at transcribing
    # (no transcript.json on disk).
    crashing = FakeAdapter()
    crashing.transcribe_side_effect = RuntimeError("simulated crash mid-transcribe")

    with pytest.raises(RuntimeError, match="simulated crash"):
        await run_job(s, sf, job_id, bus=EventBus(), adapter=crashing)

    # No transcript.json was written -> infer_resume_point re-enters at
    # transcribing (ingested is already complete because the source file
    # validated and update_stage("ingested") ran).
    from app.jobs.manifest import read_manifest

    manifest = await read_manifest(s, job_id)
    resume = infer_resume_point(s, job_id, manifest)
    assert resume == "transcribed"

    # Re-invoke with a healthy adapter -- re-transcribes from scratch.
    healthy = FakeAdapter()
    await run_job(s, sf, job_id, bus=EventBus(), adapter=healthy)

    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "done"
    assert transcript_path(s, job_id).exists()


@pytest.mark.asyncio
async def test_heartbeat_during_transcribing(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A long transcription with refreshed progress.json is NOT stale (Fix 2).

    Simulate a long transcription whose wall-clock-equivalent time
    exceeds the 10-min ``is_stale`` threshold: the throttled
    ``progress.json`` rewrite refreshes its mtime, and because
    ``_STAGE_FILE_NAMES`` now includes ``progress.json``,
    :func:`last_stage_mtime` consults it -- so ``is_stale`` returns
    False (the watchdog does NOT false-positive on active transcription).
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    # Drive run_job with a healthy fake (the fast path emits one progress
    # event, which writes progress.json).
    await run_job(s, sf, job_id, bus=EventBus(), adapter=FakeAdapter())

    # Now simulate "a long time has passed" by backdating every stage
    # file EXCEPT progress.json. Before Fix 2, ``last_stage_mtime`` did
    # not consult progress.json, so backdating manifest.json +
    # transcript.json + source.mp4 would make ``is_stale`` true (the
    # watchdog saw only the stale manifest mtime). After Fix 2 the
    # fresh progress.json mtime keeps the job fresh because
    # ``_STAGE_FILE_NAMES`` now includes ``progress.json``.
    import os
    import time

    fresh_mtime = time.time()
    # Backdate EVERY stage file except progress.json to 1 hour ago.
    old_mtime = fresh_mtime - 3600
    for name in ("manifest.json", "transcript.json"):
        p = job_dir(s, job_id) / name
        if p.exists():
            os.utime(p, (old_mtime, old_mtime))
    # Also backdate the source file so the ONLY fresh file left is
    # progress.json -- this isolates the Fix 2 root cause (without
    # Fix 2, last_stage_mtime would return the old source mtime and
    # is_stale would true-positive).
    src_file = job_dir(s, job_id) / "source.mp4"
    if src_file.exists():
        os.utime(src_file, (old_mtime, old_mtime))
    # progress.json was just written by run_job -- its mtime is fresh.
    assert (job_dir(s, job_id) / "progress.json").exists()

    from app.jobs.cleanup import is_stale

    assert is_stale(s, job_id, threshold_s=600) is False


@pytest.mark.asyncio
async def test_progress_snapshot_persisted(tmp_data_dir: Path) -> None:
    """After a run_job, progress.json exists with the required fields (Fix 9).

    ``progress.json`` carries ``chunks_done`` / ``chunks_total`` /
    ``percent`` / ``eta_s`` / ``updated_at`` so a reconnecting WS
    client reads a nonzero snapshot instead of a stale zero.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        from app.jobs.manifest import read_manifest

        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        from sqlalchemy import text

        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()

    await run_job(s, sf, job_id, bus=EventBus(), adapter=FakeAdapter())

    progress_file = job_dir(s, job_id) / "progress.json"
    assert progress_file.exists(), "progress.json must exist after run_job"
    snapshot = json.loads(progress_file.read_text(encoding="utf-8"))
    for field in ("chunks_done", "chunks_total", "percent", "eta_s", "updated_at"):
        assert field in snapshot, f"progress.json missing {field}"
    assert snapshot["chunks_done"] >= 1
    assert snapshot["chunks_total"] >= 1


# ---------------------------------------------------------------------------
# Phase 4 plan 04-02 -- Wave 0 test scaffolding (TDD RED-first).
#
# The tests below cover the 04-02 surface: the SQLite-backed FIFO worker
# (atomic claim -- Fix 6, hybrid Event + poll wakeup -- Fix 1, strict
# serial D-10), the boot interrupted-job sweep (mark_interrupted_failed --
# DB AND manifest, excludes queued per Codex MEDIUM), and the stale-sweep
# watchdog (excludes queued -- Codex MEDIUM; 04-01 heartbeat keeps active
# transcribing jobs fresh -- Fix 2).
#
# Imports of ``app.jobs.queue`` (enqueue / pull_next / run_worker / cancel /
# run_watchdog) and ``app.jobs.interrupt`` (mark_interrupted_failed) are
# guarded behind try/except or done lazily so collection succeeds before
# Tasks 2-4 land. The xfail markers stop pytest from failing on the missing
# symbols; once a task lands the relevant xfail is removed (Task 2 removes
# the queue/interrupt xfails, Task 3 the cancel/watchdog ones, Task 4 the
# lifespan-wiring one).
# ---------------------------------------------------------------------------

try:  # Wave-0 import guard: queue + interrupt land in Tasks 2/3.
    from app.jobs.queue import (  # noqa: F401
        enqueue,
        pull_next,
        run_worker,
    )
    from app.jobs.interrupt import mark_interrupted_failed  # noqa: F401

    _QUEUE_AVAILABLE = True
except ImportError:  # pragma: no cover - resolved once Task 2/3 land
    _QUEUE_AVAILABLE = False

try:
    from app.jobs.queue import cancel, run_watchdog  # noqa: F401

    _CANCEL_AVAILABLE = True
except ImportError:  # pragma: no cover - resolved once Task 3 lands
    _CANCEL_AVAILABLE = False


async def _sf(s: Settings):
    """Build a session factory against a fresh engine + migrations (04-02 helper)."""
    from app.storage.db import apply_migrations, make_engine, make_sessionmaker

    engine = make_engine(s)
    await apply_migrations(engine)
    return make_sessionmaker(engine)


def _worker_settings(tmp_data_dir: Path) -> Settings:
    """Settings with ``run_worker=True`` for tests that drive the worker loop.

    The 04-01 ``_settings`` helper sets ``run_worker=False`` (those tests call
    ``run_job`` directly). The 04-02 worker tests call ``run_worker``, which
    guards on ``settings.run_worker`` -- so they need it True to actually run.
    """
    return Settings(
        data_dir=str(tmp_data_dir / "data"),
        backend=GpuBackend.CPU,
        run_worker=True,
    )


def _reset_work_signal() -> None:
    """Reset the module-level ``_work_signal`` for test isolation.

    pytest-asyncio runs each test in a fresh event loop; the module-level
    ``asyncio.Event`` created at import time can carry waiters / value from
    a prior test's loop. Recreating it before each worker test guarantees a
    clean signal bound to the current test's loop.
    """
    import app.jobs.queue as queue_mod

    queue_mod._work_signal = asyncio.Event()


async def _make_local_job(s: Settings, sf) -> str:
    """Create a local-source job with a real non-empty source file (D-04)."""
    from sqlalchemy import text

    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        m = await read_manifest(s, job_id)
        m = m.model_copy(update={"source_path": str(src)})
        await write_manifest(s, m)
        await session.execute(
            text("UPDATE jobs SET source_path = :p WHERE id = :id"),
            {"p": str(src), "id": job_id},
        )
        await session.commit()
    return job_id


async def _force_status(sf, job_id: str, status: str) -> None:
    """Force a job row to ``status`` (bypasses the state machine -- test only)."""
    from sqlalchemy import text

    async with sf() as session:
        await session.execute(
            text("UPDATE jobs SET status = :s WHERE id = :id"),
            {"s": status, "id": job_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_restart_rejoin_boot(tmp_data_dir: Path) -> None:
    """Queued jobs survive a restart and re-join the FIFO on boot (SC-2, D-02).

    Insert two queued rows (simulating a backend restart), run the boot sweep
    (mark_interrupted_failed -- a no-op for queued), then drive the worker
    (run_worker) once and assert BOTH jobs complete to ``done`` in FIFO order.
    """
    if not _QUEUE_AVAILABLE:
        pytest.xfail("Task 2: app.jobs.queue + app.jobs.interrupt not implemented yet")
    _reset_work_signal()
    s = _worker_settings(tmp_data_dir)
    sf = await _sf(s)
    j1 = await _make_local_job(s, sf)
    j2 = await _make_local_job(s, sf)

    # Boot sweep runs AFTER reconcile_all and BEFORE the worker (Task 4
    # wiring). For queued jobs it is a no-op (D-03 -- queued re-join FIFO).
    async with sf() as session:
        swept = await mark_interrupted_failed(session, s, sf)
    assert swept == 0

    # Monkeypatch the STT loader so run_job does not hit a real model.
    import app.jobs.orchestrator as orch

    orig_loader = orch._load_stt_adapter
    orch._load_stt_adapter = lambda _settings: _async_return(FakeAdapter())

    # Drive the worker manually (run_worker is a single-pass drain here via a
    # short timeout): pull_next -> run_job -> done, twice.
    bus = EventBus()
    import asyncio

    task = asyncio.create_task(run_worker(s, sf, bus=bus))
    try:
        # Give the worker time to drain both queued jobs.
        async with sf() as session:
            for _ in range(40):
                r1 = await get_job(session, j1)
                r2 = await get_job(session, j2)
                if r1 and r2 and r1.status == "done" and r2.status == "done":
                    break
                await asyncio.sleep(0.1)
    finally:
        orch._load_stt_adapter = orig_loader
    task.cancel()
    try:
        await asyncio.gather(task, return_exceptions=True)
    except Exception:
        pass

    async with sf() as session:
        r1 = await get_job(session, j1)
        r2 = await get_job(session, j2)
    assert r1 is not None and r1.status == "done"
    assert r2 is not None and r2.status == "done"


@pytest.mark.asyncio
async def test_boot_interrupted_sweep(tmp_data_dir: Path) -> None:
    """Boot sweep marks only ingesting/transcribing failed in DB AND manifest (D-03).

    Queued jobs are NOT swept (they re-join FIFO). The sweep updates BOTH the
    DB row and the manifest so a subsequent ``reconcile_all`` does not revert
    the change (Codex MEDIUM -- manifest is the source of truth).
    """
    if not _QUEUE_AVAILABLE:
        pytest.xfail("Task 2: app.jobs.interrupt not implemented yet")
    s = _settings(tmp_data_dir)
    sf = await _sf(s)
    ingesting_id = await _make_local_job(s, sf)
    transcribing_id = await _make_local_job(s, sf)
    queued_id = await _make_local_job(s, sf)
    await _force_status(sf, ingesting_id, "ingesting")
    await _force_status(sf, transcribing_id, "transcribing")
    # queued_id stays ``queued`` (create_job default).

    async with sf() as session:
        swept = await mark_interrupted_failed(session, s, sf)

    assert swept == 2
    async with sf() as session:
        rows = {
            j: (await get_job(session, j)).status
            for j in (ingesting_id, transcribing_id, queued_id)
        }
    assert rows[ingesting_id] == "failed"
    assert rows[transcribing_id] == "failed"
    assert rows[queued_id] == "queued"  # NOT swept (D-03)
    # Manifest is also failed for the swept jobs (Codex MEDIUM).
    m_ing = await read_manifest(s, ingesting_id)
    m_tr = await read_manifest(s, transcribing_id)
    assert m_ing.status == "failed"
    assert m_tr.status == "failed"
    assert m_ing.error == "interrupted (backend restarted)"
    assert m_tr.error == "interrupted (backend restarted)"
    # Source folders are preserved (mark_failed keeps the folder; no rmtree).
    assert job_dir(s, ingesting_id).exists()
    assert job_dir(s, transcribing_id).exists()


@pytest.mark.asyncio
async def test_serial_no_concurrency(tmp_data_dir: Path) -> None:
    """Worker=1 strict serial: 3 enqueued jobs run strictly one-at-a-time (D-10).

    A semaphore-asserting FakeAdapter fails if more than one transcribe is
    in-flight simultaneously. With a single asyncio worker task there is no
    ``asyncio.gather`` of multiple jobs, so the semaphore is never >1.
    """
    if not _QUEUE_AVAILABLE:
        pytest.xfail("Task 2: app.jobs.queue not implemented yet")
    _reset_work_signal()
    import asyncio
    import threading

    inflight = 0
    max_inflight = 0
    lock = threading.Lock()

    class _SerialFakeAdapter:
        """Wraps FakeAdapter with a concurrency guard (mirrors the adapter Protocol)."""

        def __init__(self) -> None:
            self._inner = FakeAdapter()
            self.loaded = False

        def load(self) -> None:
            self._inner.load()
            self.loaded = self._inner.loaded

        def unload(self) -> None:
            self._inner.unload()
            self.loaded = self._inner.loaded

        def decode_audio(self, path):  # noqa: ANN001
            return self._inner.decode_audio(path)

        def detect_language(self, audio):  # noqa: ANN001
            return self._inner.detect_language(audio)

        def transcribe(self, audio, language=None, vad_filter=True, condition_on_previous_text=True, *, progress_cb=None, cancel_flag=None):  # noqa: ANN001
            nonlocal inflight, max_inflight
            with lock:
                inflight += 1
                max_inflight = max(max_inflight, inflight)
            try:
                return self._inner.transcribe(
                    audio,
                    language=language,
                    vad_filter=vad_filter,
                    condition_on_previous_text=condition_on_previous_text,
                    progress_cb=progress_cb,
                    cancel_flag=cancel_flag,
                )
            finally:
                with lock:
                    inflight -= 1

    s = _worker_settings(tmp_data_dir)
    sf = await _sf(s)
    ids = [await _make_local_job(s, sf) for _ in range(3)]

    # The worker pulls a queued job and calls run_job, which loads the STT
    # adapter via the production path when ``adapter is None``. To keep this
    # test hermetic, monkeypatch the orchestrator's ``_load_stt_adapter`` to
    # return our SerialFakeAdapter.
    import app.jobs.orchestrator as orch

    fake = _SerialFakeAdapter()
    orig_loader = orch._load_stt_adapter
    orch._load_stt_adapter = lambda _settings: _async_return(fake)

    bus = EventBus()
    task = asyncio.create_task(run_worker(s, sf, bus=bus))
    try:
        async with sf() as session:
            for _ in range(60):
                rows = [await get_job(session, j) for j in ids]
                if all(r is not None and r.status == "done" for r in rows):
                    break
                await asyncio.sleep(0.1)
        assert max_inflight <= 1, f"worker ran >1 transcribe concurrently: {max_inflight}"
    finally:
        orch._load_stt_adapter = orig_loader
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _async_return(value):
    """Tiny coroutine returning ``value`` (for monkeypatching async loaders)."""
    return value


class _SerialFakeAdapterAdapter:  # pragma: no cover - retained for forward compat
    """Holder that exposes a single shared SerialFakeAdapter instance.

    Retained as a named wrapper in case a future test needs to attach extra
    knobs to the fake without subclassing. The current serial-concurrency
    test returns the bare :class:`_SerialFakeAdapter` from the monkeypatched
    ``_load_stt_adapter``.
    """

    def __init__(self, inner) -> None:
        self._inner = inner


@pytest.mark.asyncio
async def test_watchdog_stale(tmp_data_dir: Path) -> None:
    """Watchdog marks stale active jobs every 60s; excludes queued (Codex MEDIUM).

    A job in ``transcribing`` whose ``last_stage_mtime`` is older than the
    600s threshold is marked stale (``mark_stale`` reuses the status-aware
    gate from cleanup). A terminal job short-circuits. A QUEUED job is NOT
    swept (the watchdog SELECT filters to ``status IN
    ('ingesting','transcribing')`` -- Codex MEDIUM).
    """
    if not _CANCEL_AVAILABLE:
        pytest.xfail("Task 3: app.jobs.queue.run_watchdog not implemented yet")
    _reset_work_signal()
    import asyncio
    import os
    import time

    s = _worker_settings(tmp_data_dir)
    sf = await _sf(s)
    active_id = await _make_local_job(s, sf)
    terminal_id = await _make_local_job(s, sf)
    queued_id = await _make_local_job(s, sf)
    await _force_status(sf, active_id, "transcribing")
    await _force_status(sf, terminal_id, "done")
    # queued_id stays ``queued``.

    # Backdate every stage file for the active job so is_stale returns True.
    old = time.time() - 3600
    for name in ("manifest.json", "transcript.json"):
        p = job_dir(s, active_id) / name
        if p.exists():
            os.utime(p, (old, old))
    src = job_dir(s, active_id) / "source.mp4"
    if src.exists():
        os.utime(src, (old, old))

    from app.jobs.cleanup import is_stale

    assert is_stale(s, active_id, threshold_s=600) is True

    # Drive the watchdog once with a very short sleep override. We cannot
    # wait 60s in a test, so we call the internal tick directly by
    # monkeypatching asyncio.sleep to a no-op and cancelling after one tick.
    import app.jobs.queue as queue_mod

    real_sleep = asyncio.sleep
    sleep_calls = []

    async def _fast_sleep(secs):
        sleep_calls.append(secs)
        # One real yield so the loop can cancel cleanly.
        await real_sleep(0)

    queue_mod.asyncio.sleep = _fast_sleep  # type: ignore[attr-defined]

    task = asyncio.create_task(run_watchdog(s, sf))
    # Let one tick fire.
    await real_sleep(0.2)
    task.cancel()
    try:
        await asyncio.gather(task, return_exceptions=True)
    finally:
        queue_mod.asyncio.sleep = real_sleep  # type: ignore[attr-defined]

    async with sf() as session:
        active_row = await get_job(session, active_id)
        terminal_row = await get_job(session, terminal_id)
        queued_row = await get_job(session, queued_id)
    assert active_row is not None and active_row.status == "failed"
    assert terminal_row is not None and terminal_row.status == "done"
    assert queued_row is not None and queued_row.status == "queued"


@pytest.mark.asyncio
async def test_atomic_claim_two_workers(tmp_data_dir: Path) -> None:
    """Two concurrent pull_next calls on the same queued job -> only one wins (Fix 6).

    The atomic claim is a conditional ``UPDATE jobs SET status='starting'
    WHERE id=:id AND status='queued'``; only the worker whose UPDATE changes
    exactly one row proceeds. The other gets ``rowcount == 0`` and returns
    ``None`` (re-poll or exit).
    """
    if not _QUEUE_AVAILABLE:
        pytest.xfail("Task 2: app.jobs.queue.pull_next not implemented yet")
    import asyncio

    s = _settings(tmp_data_dir)
    sf = await _sf(s)
    job_id = await _make_local_job(s, sf)

    async with sf() as session_a, sf() as session_b:
        # Race two pull_next calls against the same single queued row.
        a, b = await asyncio.gather(
            pull_next(session_a), pull_next(session_b)
        )

    # Exactly one of (a, b) is the job_id; the other is None.
    winners = [x for x in (a, b) if x is not None]
    assert len(winners) == 1, f"both workers claimed the same job: {a=}, {b=}"
    assert winners[0] == job_id


@pytest.mark.asyncio
async def test_hybrid_wakeup_no_signal(tmp_data_dir: Path) -> None:
    """A missed _work_signal self-heals via the 2s poll timeout (Fix 1).

    Start the worker so it awaits ``_work_signal.wait()``; the test then
    enqueues a job WITHOUT calling ``_work_signal.set()`` (simulating a missed
    signal -- the enqueue fired before the worker awaited). The 2s poll
    timeout in ``run_worker`` catches the new job and drains it.
    """
    if not _QUEUE_AVAILABLE:
        pytest.xfail("Task 2: app.jobs.queue.run_worker not implemented yet")
    _reset_work_signal()
    import asyncio

    s = _worker_settings(tmp_data_dir)
    sf = await _sf(s)
    job_id = await _make_local_job(s, sf)
    # Park the job in ``starting`` so the worker's first pull_next does NOT
    # find it (simulate an empty queue at worker start). The test then
    # flips it to ``queued`` WITHOUT calling ``_work_signal.set()`` to
    # simulate a missed signal (enqueue fired but the set() was lost).
    await _force_status(sf, job_id, "starting")

    import app.jobs.orchestrator as orch
    import app.jobs.queue as queue_mod

    orig_loader = orch._load_stt_adapter
    orch._load_stt_adapter = lambda _settings: _async_return(FakeAdapter())

    bus = EventBus()
    task = asyncio.create_task(run_worker(s, sf, bus=bus))
    try:
        # Let the worker reach the wait (pull_next returns None -> await).
        await asyncio.sleep(0.1)
        # Flip the job to ``queued`` WITHOUT firing _work_signal (simulate
        # the missed-signal race: enqueue's set() was lost / never fired).
        await _force_status(sf, job_id, "queued")
        queue_mod._work_signal.clear()
        # The 2s poll timeout should wake the worker and drain the job.
        async with sf() as session:
            for _ in range(40):
                row = await get_job(session, job_id)
                if row and row.status == "done":
                    break
                await asyncio.sleep(0.1)
        async with sf() as session:
            row = await get_job(session, job_id)
        assert row is not None and row.status == "done"
    finally:
        orch._load_stt_adapter = orig_loader
        task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Phase 4 plan 04-04 -- CR-03 gap-closure regression test (TDD RED-first).
#
# ``test_resume_advances_to_done_when_both_stages_complete`` simulates the
# crash window between ``update_stage("transcribed")`` and
# ``update_stage("done")``: transcript.json is on disk (file-as-truth says
# transcribed is complete) AND manifest.current_stage == "transcribed", but
# the derived done transition was never recorded (DB status stays
# "transcribing"). Without the 04-04 fix run_job falls through both
# ``if not skip_*`` blocks and exits without advancing -- the job stuck in
# "transcribing" forever. The fix adds a final ``if resume_stage == "done":``
# branch that records the derived done transition + publishes the done event.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_advances_to_done_when_both_stages_complete(
    tmp_data_dir: Path,
) -> None:
    """CR-03: a crash-window job (both stages file-complete, current_stage !=
    "done") advances to done when run_job re-enters (no re-transcription).

    Simulates the crash between ``update_stage("transcribed")`` and
    ``update_stage("done")``: pre-write a valid transcript.json, force
    manifest.current_stage="transcribed" + DB status="transcribing" (the
    post-crash state), then call run_job. The resume walker returns
    ``"done"`` (ingested + transcribed are file-complete but
    is_stage_complete("done") is False because current_stage != "done").
    Before the 04-04 fix run_job ignored that verdict, fell through both
    ``if not skip_*`` blocks, and exited without advancing. After the fix
    the new ``if resume_stage == "done":`` branch records the derived done
    transition and publishes the done event.
    """
    s = _settings(tmp_data_dir)
    sf = await _session_factory(s)

    # 1. Create a local-source job (D-04 reference-in-place -- the source
    #    file already exists so is_stage_complete("ingested") is True).
    job_id = await _make_local_job(s, sf)

    # 2. Pre-write a valid transcript.json (file-as-truth says transcribed
    #    is complete) and force manifest.current_stage="transcribed" +
    #    DB status="transcribing" -- the post-crash state where
    #    update_stage("transcribed") committed but the subsequent
    #    update_stage("done") did not.
    from app.models.transcript import Transcript, TranscriptSegment
    from app.storage.atomic import atomic_write_json

    transcript = Transcript(
        job_id=job_id,
        language="en",
        segments=[TranscriptSegment(start_s=0.0, end_s=1.0, text="hi")],
    )
    await atomic_write_json(
        transcript_path(s, job_id), transcript.model_dump(mode="json")
    )

    m = await read_manifest(s, job_id)
    m = m.model_copy(update={"current_stage": "transcribed"})
    await write_manifest(s, m)

    from sqlalchemy import text

    async with sf() as session:
        await session.execute(
            text("UPDATE jobs SET status = :s WHERE id = :id"),
            {"s": "transcribing", "id": job_id},
        )
        await session.commit()

    # Sanity: the resume walker returns "done" in this crash window.
    manifest_before = await read_manifest(s, job_id)
    assert infer_resume_point(s, job_id, manifest_before) == "done"

    # 3. Subscribe a recording queue so we can assert the done event was
    #    published to the bus.
    bus = EventBus()
    q = bus.subscribe(job_id)

    # 4. Wire a FakeAdapter and assert it was NOT called (skip_transcribed
    #    is True -- the transcript is already on disk, no re-transcription).
    fake = FakeAdapter()

    # 5. Re-enter run_job -- the 04-04 fix advances the job to done.
    await run_job(s, sf, job_id, bus=bus, adapter=fake)

    # 6. Assertions:
    # (a) manifest.current_stage == "done" (the derived done transition
    #     was recorded by the new resume_stage == "done" branch).
    m_after = await read_manifest(s, job_id)
    assert m_after.current_stage == "done"
    # (b) DB status == "done".
    async with sf() as session:
        row = await get_job(session, job_id)
    assert row is not None
    assert row.status == "done"
    # (c) The bus received {"type": "done"} (same event the happy path
    #     publishes at orchestrator.py:282).
    events: list[dict] = []
    while True:
        try:
            events.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert any(ev.get("type") == "done" for ev in events), (
        f"expected a 'done' event on the bus, got: {events}"
    )
    # (d) The FakeAdapter.transcribe was NOT called (skip_transcribed=True
    #     -- the transcript is already on disk, no re-transcription).
    assert fake.call_count == 0, (
        "FakeAdapter.transcribe should not be called when transcript.json "
        "already exists (skip_transcribed=True)"
    )