---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
plan: 01
subsystem: jobs
tags: [orchestrator, state-machine, event-bus, stt-protocol, threading, heartbeat, progress-snapshot]
requires:
  - "Phase 1: update_stage / infer_resume_point / cancel_job / mark_failed / is_stale / last_stage_mtime"
  - "Phase 2: ModelManager.load / ensure_downloaded / device_for"
  - "Phase 3: STTAdapter Protocol / FasterWhisperAdapter / chunker.transcribe_file"
provides:
  - "app.jobs.orchestrator.run_job -- the state-machine driver 04-02/04-03 build on"
  - "app.jobs.progress.EventBus -- the in-process pub/sub 04-03 WS handler subscribes to"
  - "app.jobs.errors.JobCancelled -- the shared cancel exception (Fix 5 neutral module)"
  - "STTAdapter.transcribe kw-only progress_cb/cancel_flag superset (Fix 8)"
  - "ChunkProgress dataclass + per-chunk progress emit from the chunker"
  - "_running: dict[str, threading.Event] registry for the 04-02 cancel route"
  - "Settings.run_worker toggle for the 04-02 lifespan auto-start"
affects:
  - "app.storage.fs._STAGE_FILE_NAMES -- progress.json added (Fix 2 root cause)"
  - "app.jobs.resume.is_stage_complete('ingested') -- D-04 generalized check"
tech-stack:
  added:
    - "threading.Event cancel_flag (NOT asyncio.Event) for cross-loop cancel"
    - "functools.partial to wrap kwargs for loop.run_in_executor (Fix 3)"
    - "loop.call_soon_threadsafe to marshal progress events from the worker thread"
    - "asyncio.wait_for(future, timeout=30.0) graceful in-flight shutdown (Fix 3)"
    - "throttled atomic_write_json(progress.json) heartbeat (Fix 2 + Fix 9)"
  patterns:
    - "file-as-truth stage transitions via update_stage (write-manifest-first / commit-DB-last)"
    - "stage completion recorded ONLY AFTER the output file exists (Fix 4)"
    - "infer_resume_point at top of run_job to skip completed stages (Fix 4 re-entrant)"
    - "EventBus pub/sub with drop-oldest backpressure (maxsize=32, Pitfall 2)"
    - "horizontal import: chunker imports JobCancelled from app.jobs.errors (NOT upward, Fix 5)"
key-files:
  created:
    - app/jobs/errors.py
    - app/jobs/progress.py
    - app/jobs/orchestrator.py
    - tests/test_event_bus.py
    - tests/test_orchestrator.py
  modified:
    - app/models/stt/protocol.py
    - app/models/stt/adapter.py
    - app/models/stt/chunker.py
    - app/models/settings.py
    - app/jobs/resume.py
    - app/storage/fs.py
    - tests/_stt_fake.py
    - tests/conftest.py
decisions:
  - "JobCancelled lives in the neutral app/jobs/errors.py (Fix 5) -- chunker imports horizontally, orchestrator re-exports for convenience; source of truth is errors.py"
  - "FasterWhisperAdapter.transcribe accepts the kw-only progress_cb/cancel_flag superset but does NOT consult them -- the chunker loop owns cancel-check + progress emit at its boundary; the adapter acceptance is purely for Protocol conformance / no-TypeError (Fix 8)"
  - "Cancel flag is a threading.Event (NOT asyncio.Event) so the asyncio side can set it without crossing loop boundaries; the chunker (off-loop in a worker thread) observes it at the next chunk boundary (D-06 cooperative cancel)"
  - "run_job re-raises non-cancel exceptions after mark_failed (so the 04-02 worker can log/surface them) but swallows JobCancelled (cancel is an expected flow, not an error)"
  - "Heartbeat is satisfied automatically by the throttled progress.json mtime + _STAGE_FILE_NAMES inclusion -- NO os.utime(job_dir) (the job-dir mtime is not consulted by last_stage_mtime, Fix 2)"
  - "test_heartbeat_during_transcribing backdates EVERY stage file except progress.json (including source.mp4) so the test isolates the Fix 2 root cause -- without Fix 2 last_stage_mtime returns the old source/manifest mtime and is_stale true-positives"
metrics:
  duration: "~23 min"
  tasks: 4
  files: 13
---

# Phase 4 Plan 01: Orchestrator State-Machine + EventBus + Progress Heartbeat Summary

The Phase 4 spine: a job can be driven `queued -> ingesting -> transcribing -> done` via a state-machine driver (`run_job`) with file-as-truth stage transitions, an in-process asyncio `EventBus` (pub/sub + drop-oldest backpressure), the kw-only `progress_cb`/`cancel_flag` extension to `STTAdapter` + `transcribe_file` + `FasterWhisperAdapter`, the shared `JobCancelled` exception, per-chunk progress published off-loop via `call_soon_threadsafe`, graceful in-flight shutdown via `asyncio.wait_for(future, timeout=30.0)`, and a throttled `progress.json` snapshot that doubles as the heartbeat (Fix 2 root cause: `progress.json` added to `_STAGE_FILE_NAMES` so the stale-sweep watchdog sees a fresh mtime on long transcriptions and stops false-positive'ing).

## What Was Built

### Task 1a -- Contracts (commit aff9478)
- `app/jobs/errors.py`: neutral `JobCancelled(Exception)` with `job_id` attribute (Fix 5). Single-exception module; no orchestration imports so the chunker imports horizontally, not upward.
- `app/models/stt/protocol.py`: `ChunkProgress` dataclass (`chunks_done`, `chunks_total`, `chunk_start_s`, `within_chunk_percent`); `STTAdapter.transcribe` gains kw-only `progress_cb: Callable[[ChunkProgress], None] | None = None` and `cancel_flag: threading.Event | None = None` after a `*,` marker -- the existing positional call stays valid (backward compatible).
- `app/models/stt/adapter.py`: `FasterWhisperAdapter.transcribe` accepts the same kw-only pair so production never `TypeError`s when a caller passes them (Fix 8). The adapter does NOT consult them -- the chunker loop owns cancel-check + progress emit; the adapter acceptance is purely Protocol conformance.
- `app/models/stt/chunker.py`: `transcribe_file` gains the kw-only pair; cancel check at the TOP of the while loop raises `JobCancelled(job_id)` (horizontal import from `app.jobs.errors`, NOT upward -- Fix 5); per-chunk `progress_cb(ChunkProgress(...))` emit after `chunk_count += 1`; fast-path emits one `ChunkProgress(chunks_done=1, chunks_total=1, chunk_start_s=0.0)`; `total_chunks` computed once before the loop (zero-division guarded).
- `app/jobs/progress.py`: `EventBus` class -- `subscribe(job_id)` returns `asyncio.Queue(maxsize=32)`; `publish` is SYNC (called via `call_soon_threadsafe`), fans out to every subscriber, drop-oldest on `QueueFull` (`get_nowait` then `put_nowait`); `unsubscribe` cleans up the empty list; `has_subscribers` test hook.
- `app/models/settings.py`: `Settings.run_worker: bool = True` field (04-02 worker toggle; defaulted so existing settings files round-trip under `extra="forbid"`).

### Task 1b -- Test scaffolding + fakes (commit e328247)
- `tests/_stt_fake.py`: `FakeAdapter.transcribe` accepts the kw-only pair; emits one `ChunkProgress` per call; raises `JobCancelled` when `cancel_flag.is_set()` (imports from `app.jobs.errors`).
- `tests/conftest.py`: `tmp_data_dir` writes `run_worker=False` so the 04-02 lifespan does not auto-start the worker; `mock_stt_adapter`'s `_WhisperModel.transcribe` accepts the new kwargs.
- `tests/test_event_bus.py`: 5 GREEN tests (roundtrip, drop-oldest on full, unsubscribe cleanup, no-subscriber no-op, multi-subscriber fan-out).
- `tests/test_orchestrator.py`: Wave 0 stubs (`test_state_machine`, `test_restart_rejoin`, `test_heartbeat_during_transcribing`, `test_progress_snapshot_persisted`) -- RED until Task 2/3 land `run_job`.

### Task 2 -- run_job state-machine driver (commit 2d2c7e0)
- `app/jobs/orchestrator.py`: `async def run_job(settings, session_factory, job_id, bus=None, adapter=None) -> None`. At the top, `infer_resume_point(settings, job_id, manifest)` skips completed stages (Fix 4). Every stage transition goes through `update_stage` (no raw `UPDATE jobs`). Stage completion is recorded ONLY AFTER the output file exists (Fix 4): publish `stage_changed` + run the work BEFORE `update_stage`; `atomic_write_json(transcript.json)` BEFORE `update_stage("transcribed")`. The transcribing stage runs off-loop via `loop.run_in_executor(None, functools.partial(transcribe_file, adapter, source_path, language=None, job_id=job_id, progress_cb=_on_progress, cancel_flag=cancel_flag))` (Fix 3 -- `run_in_executor` cannot take kwargs directly). Per-chunk progress is marshalled back via `loop.call_soon_threadsafe(bus.publish, ...)` (T-04-thread). The `finally` block awaits the in-flight future with `asyncio.wait_for(future, timeout=30.0)` before model unload (Fix 3 graceful shutdown). On `JobCancelled`: `cancel_job` + `bus.publish({"type":"cancelled"})` (no `transcript.json` -- Pitfall 4). On any other exception: `mark_failed` + `bus.publish({"type":"failed",...})` + re-raise. The youtube seam raises `NotImplementedError("youtube ingest is Phase 6")` (D-01). `_running: dict[str, threading.Event]` registry for the 04-02 cancel route. Re-exports `JobCancelled` (Fix 5).
- `app/jobs/resume.py`: `is_stage_complete("ingested", ...)` refined per D-04 -- FIRST check `manifest.source_path` resolves to a non-empty file, THEN fall back to the in-job-dir `source.<ext>` glob (generalized check keeps both ingest paths working from the same walker).
- `tests/test_orchestrator.py`: `test_state_machine` + `test_restart_rejoin` GREEN (TDD GREEN gate).

### Task 3 -- Heartbeat + progress snapshot (commit dc18fec)
- `app/storage/fs.py`: `_STAGE_FILE_NAMES` now includes `"progress.json"` (Fix 2 root cause, Ollama HIGH). `last_stage_mtime` consults the progress.json mtime; the throttled `atomic_write_json(progress.json)` rewrite on every chunk callback (<=1/s) refreshes it so a 20-min video actively transcribing for >10 min is NOT marked stale (the watchdog now sees the fresh progress.json mtime, not just the stale manifest.json). No `os.utime(job_dir)` -- the job-dir mtime is not consulted by `last_stage_mtime`, so the heartbeat is satisfied automatically by the progress.json mtime.
- `app/jobs/orchestrator.py`: `_on_progress` computes percent + ETA (D-09 -- ETA hidden until `chunks_done >= 2`), publishes the event to the bus, and schedules a throttled `progress.json` write (Fix 9) with `{chunks_done, chunks_total, percent, eta_s, updated_at}`. Reconnecting WS clients read `progress.json` on connect (04-03) and see a nonzero snapshot even if they missed live events.
- `tests/test_orchestrator.py`: `test_heartbeat_during_transcribing` backdates EVERY stage file except `progress.json` (including `source.mp4`) so the test isolates the Fix 2 root cause; `test_progress_snapshot_persisted` asserts `progress.json` exists with the required fields. Both GREEN.

## Verification

- `pytest tests/test_orchestrator.py tests/test_event_bus.py -x` green (9 tests)
- `grep -rE '^[[:space:]]*(from faster_whisper|import faster_whisper|import ctranslate2)' app/` matches only `app/models/stt/adapter.py` (SC-4 preserved)
- `grep -c 'UPDATE jobs' app/jobs/orchestrator.py` returns 0 (no raw UPDATE -- all transitions via `update_stage`)
- `grep 'from app.jobs.orchestrator import JobCancelled' app/models/stt/chunker.py` returns nothing (Fix 5 -- horizontal import from `errors.py`)
- `grep 'functools.partial' app/jobs/orchestrator.py` matches (Fix 3)
- `grep 'infer_resume_point' app/jobs/orchestrator.py` matches (Fix 4)
- `grep 'progress.json' app/jobs/orchestrator.py` matches (Fix 9)
- `grep 'progress.json' app/storage/fs.py` matches inside `_STAGE_FILE_NAMES` (Fix 2 root cause)
- `grep 'os.utime(job_dir' app/jobs/orchestrator.py` returns nothing (Fix 2 -- no useless job-dir mtime touch)
- CLI regression: `pytest tests/test_cli_transcribe.py tests/test_chunker.py -x` green (23 tests)
- Full suite: 229 passed (225 pre-existing + 4 new orchestrator)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed adapter "forward to transcribe_file" ambiguity**
- **Found during:** Task 1a
- **Issue:** The plan said `FasterWhisperAdapter.transcribe` should "forward them to the `transcribe_file(...)` call it already makes." The adapter does NOT call `transcribe_file` -- the chunker calls the adapter (`adapter.transcribe`), not the other way around. The chunker loop owns cancel-check + per-chunk progress emit at its boundary, so the adapter has nothing to forward to.
- **Fix:** `FasterWhisperAdapter.transcribe` ACCEPTS the kw-only `progress_cb`/`cancel_flag` pair (satisfying the extended Protocol + the no-TypeError contract, Fix 8) but does NOT consult them -- documented inline. This matches the actual call graph and satisfies the acceptance criterion ("signature contains `progress_cb` and `cancel_flag`").
- **Files modified:** `app/models/stt/adapter.py`
- **Commit:** aff9478

**2. [Rule 2 - Critical] Added fast-path cancel check + FakeAdapter in-adapter cancel check**
- **Found during:** Task 1a/1b
- **Issue:** The plan's cancel check was only at the chunked-loop top. The fast path (single call <=30 min) had no cancel observation point, and the FakeAdapter had no cancel handling -- tests that exercise cancel via the adapter directly would not see it.
- **Fix:** Added a pre-call `cancel_flag.is_set()` check in the chunker fast path (raises `JobCancelled` before the single transcribe call) and a `cancel_flag.is_set()` check inside `FakeAdapter.transcribe` (raises `JobCancelled`). Both are within the plan's D-06 "cooperative cancel at the next chunk boundary" contract -- the fast path's "boundary" is "before the single call."
- **Files modified:** `app/models/stt/chunker.py`, `tests/_stt_fake.py`
- **Commit:** aff9478 / e328247

**3. [Rule 1 - Bug] Fixed test_heartbeat_during_transcribing to actually isolate Fix 2**
- **Found during:** Task 3
- **Issue:** The plan's test_heartbeat stub only backdated `manifest.json` + `transcript.json`. `source.mp4` (created by the test setup) was left fresh, so `last_stage_mtime` returned source.mp4's fresh mtime and `is_stale` returned False REGARDLESS of whether `progress.json` was in `_STAGE_FILE_NAMES` -- the test passed for the wrong reason and did not validate Fix 2.
- **Fix:** The test now backdates EVERY stage file except `progress.json` (including `source.mp4`), so the ONLY fresh file is `progress.json`. Without Fix 2, `last_stage_mtime` returns the old source/manifest mtime and `is_stale` true-positives (test fails); with Fix 2, the fresh `progress.json` mtime keeps the job fresh (test passes). This makes the test a proper RED-gate-before-Fix-2 / GREEN-gate-after-Fix-2.
- **Files modified:** `tests/test_orchestrator.py`
- **Commit:** dc18fec

**4. [Rule 3 - Blocking] Resolved `infer_resume_point` signature mismatch**
- **Found during:** Task 2
- **Issue:** The plan said "call `infer_resume_point(settings, job_id)`" but the existing signature is `infer_resume_point(settings, job_id, manifest)` -- it requires the manifest.
- **Fix:** `run_job` reads the manifest first via `read_manifest(settings, job_id)` and passes it to `infer_resume_point(settings, job_id, manifest)`. This is consistent with the existing resume walker contract (the manifest is the source of truth for optional-stage applicability checks).
- **Files modified:** `app/jobs/orchestrator.py`
- **Commit:** 2d2c7e0

## Known Stubs

None. The production adapter-load path (`adapter=None` in `run_job`) is implemented (`_load_stt_adapter` mirrors `app/cli/transcribe.py`: `ensure_downloaded` + `FasterWhisperAdapter(model_path, device, compute_type)` + `adapter.load()`) but is NOT exercised by these tests -- tests pass a `FakeAdapter`. The 04-02 worker wires it live.

## Threat Flags

None. All trust boundaries in the plan's `<threat_model>` are mitigated as specified (T-04-bus drop-oldest, T-04-thread `call_soon_threadsafe` + `threading.Event`, T-04-partial atomic-write-after-return, T-04-boundary horizontal import, T-04-stale-fp progress.json in `_STAGE_FILE_NAMES`, T-04-shutdown bounded `wait_for`, T-04-resume `infer_resume_point` + completion-after-output). No new security-relevant surface introduced beyond the plan.

## Self-Check: PASSED

- `app/jobs/errors.py` FOUND
- `app/jobs/progress.py` FOUND
- `app/jobs/orchestrator.py` FOUND
- `tests/test_event_bus.py` FOUND
- `tests/test_orchestrator.py` FOUND
- `app/storage/fs.py` contains `progress.json` in `_STAGE_FILE_NAMES` FOUND
- `app/jobs/resume.py` D-04 `manifest.source_path` check FOUND
- commit aff9478 FOUND
- commit e328247 FOUND
- commit 2d2c7e0 FOUND
- commit dc18fec FOUND