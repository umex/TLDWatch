---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
plan: 02
subsystem: jobs
tags: [queue, sqlite, restart-resume, cancel, watchdog, asyncio, jobs, atomic-claim, hybrid-wakeup]
requires:
  - "Phase 4 plan 04-01: run_job state-machine driver + _running registry + heartbeat + EventBus + JobCancelled + STTAdapter progress_cb/cancel_flag + Settings.run_worker"
  - "Phase 1: update_stage / cancel_job / mark_failed / is_stale / mark_stale / reconcile_all / atomic_write_json"
provides:
  - "app.jobs.queue.run_worker -- single asyncio worker draining the FIFO queue (D-10 strict serial)"
  - "app.jobs.queue.enqueue -- status-aware re-queue guard (Codex MEDIUM)"
  - "app.jobs.queue.pull_next -- atomic claim via conditional UPDATE WHERE status='queued' (Fix 6)"
  - "app.jobs.queue.cancel -- idempotent queued/running/terminal cancel (D-06)"
  - "app.jobs.queue.run_watchdog -- 60s stale-sweep excluding queued (Codex MEDIUM, D-11)"
  - "app.jobs.interrupt.mark_interrupted_failed -- boot sweep updating DB + manifest (Codex MEDIUM)"
  - "app.main lifespan wiring (sweep + worker + watchdog + ordered teardown + app.state)"
  - "'starting' added to JobStatus Literal (transient atomic-claim state)"
affects:
  - "app/main.py -- lifespan now starts worker+watchdog and establishes app.state.bus/settings/session_factory (Fix 7-partial)"
  - "app/models/job.py -- JobStatus Literal gained 'starting'"
tech-stack:
  added:
    - "asyncio.Event module-level _work_signal for hybrid Event+poll wakeup (Fix 1)"
    - "asyncio.wait_for(_work_signal.wait(), timeout=2.0) self-healing poll fallback"
    - "Conditional UPDATE ... WHERE id=:id AND status='queued' with rowcount check (Fix 6 atomic claim)"
    - "threading.Event cross-loop cancel via 04-01 _running registry (D-06)"
    - "atomic_write_json manifest fallback for 'failed' stage (update_stage maps 'failed' -> 'queued' incorrectly)"
  patterns:
    - "DB-first cancel_job on queued path; running path sets _running flag only (no double-rmtree, T-04-06)"
    - "Boot sequence: reconcile_all -> mark_interrupted_failed -> run_worker -> run_watchdog (D-03)"
    - "Teardown cancels worker+watchdog (return_exceptions=True) BEFORE engine.dispose"
    - "Watchdog SELECT filters to ingesting/transcribing only (excludes queued, Codex MEDIUM)"
    - "enqueue guards status IN ('created','queued') so terminal/active rows are not re-queued (T-04-12)"
key-files:
  created:
    - app/jobs/queue.py
    - app/jobs/interrupt.py
    - tests/test_cancel.py
  modified:
    - app/main.py
    - app/models/job.py
    - tests/conftest.py
    - tests/test_orchestrator.py
decisions:
  - "update_stage cannot be used for the 'failed' stage because stage_to_status('failed') falls through to the defensive 'queued' mapping (the stage map only covers active processing stages). The boot sweep writes the manifest directly via atomic_write_json with status='failed' / current_stage='failed' / error set -- the documented fallback path from the plan."
  - "'starting' was added to the JobStatus Literal because pull_next's atomic claim sets status='starting' as a transient claim state; without it, get_job raised ValidationError during the claim window (Rule 1 bug fix). The API can now represent the transient state."
  - "The worker loop catches exceptions from run_job so one failed job does not kill the worker task and stall the whole queue (Rule 2 -- missing error handling). run_job already mark_failed + bus.publish('failed') + re-raise; the worker logs and continues."
  - "Module-level _work_signal is an asyncio.Event; tests reset it via _reset_work_signal() before each worker test because pytest-asyncio runs each test in a fresh event loop and the module-level Event can carry stale waiters from a prior loop."
  - "cancel returns a plain dict {status, id} rather than a JobResponse to avoid the ValidationError surface during the transient 'starting' state; the route layer (04-03 / future) maps it to a response."
metrics:
  duration: "~23 min"
  tasks: 4
  files: 7
---

# Phase 4 Plan 02: SQLite FIFO Queue + Boot Sweep + Cancel + Watchdog Summary

04-02 builds the persistent SQLite-backed FIFO queue, restart-resume boot sweep, cooperative cancel, and stale-sweep watchdog on top of 04-01's orchestrator state-machine driver. The worker drains the queue strictly serially (D-10) with an atomic claim (Fix 6 -- conditional `UPDATE ... WHERE status='queued'` + rowcount check) and a hybrid Event+poll wakeup (Fix 1 -- `asyncio.wait_for(_work_signal.wait(), timeout=2.0)` self-heals a missed signal). The boot sweep marks ingesting/transcribing jobs failed in BOTH DB and manifest (Codex MEDIUM -- `update_stage` cannot write 'failed' so the documented `atomic_write_json` fallback is used); queued jobs re-join the FIFO (D-03). Cancel is idempotent across queued/running/terminal (D-06); the running path sets 04-01's `threading.Event` cancel flag and lets the orchestrator's `JobCancelled` path do `cancel_job` (no double-rmtree, T-04-06). The watchdog marks stale active jobs every 60s, excluding queued (Codex MEDIUM); 04-01's heartbeat keeps active transcribing jobs fresh (Fix 2). The lifespan wires reconcile_all -> mark_interrupted_failed -> run_worker -> run_watchdog with ordered teardown (worker+watchdog cancelled before engine.dispose) and establishes `app.state.bus/settings/session_factory` (Fix 7-partial for 04-03).

## What Was Built

### Task 1 -- Wave 0 test scaffolding (commit 37d9ada)
- `tests/conftest.py`: `fake_stt` fixture (reuses 04-01 `FakeAdapter` honoring `progress_cb`/`cancel_flag`) + `run_worker_off` sanity-alias fixture asserting `run_worker=False`. The existing `client` fixture already does NOT auto-start the worker (lifespan only starts one when `run_worker=True`; `tmp_data_dir` writes `run_worker=False`).
- `tests/test_cancel.py`: 3 parametrized cancel tests (queued/running/terminal) -- xfail until Task 3.
- `tests/test_orchestrator.py`: 6 new tests added alongside 04-01's existing 4 -- `test_restart_rejoin_boot`, `test_boot_interrupted_sweep`, `test_serial_no_concurrency`, `test_watchdog_stale`, `test_atomic_claim_two_workers` (Fix 6), `test_hybrid_wakeup_no_signal` (Fix 1) -- all xfail until Tasks 2-4. Wave-0 import guards (`_QUEUE_AVAILABLE` / `_CANCEL_AVAILABLE`) so collection succeeds before the modules land.

### Task 2 -- SQLite FIFO worker + boot sweep (commit 4eeda0b)
- `app/jobs/queue.py`: async module with module-level `asyncio.Event _work_signal`.
  - `enqueue(job_id, session)`: status-aware guard `UPDATE ... WHERE id=:id AND status IN ('created','queued')` (Codex MEDIUM -- no re-queueing terminal/active, T-04-12); commits then `_work_signal.set()`.
  - `pull_next(session) -> str | None` (Fix 6): `SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1` (FIFO, D-10); conditional `UPDATE jobs SET status='starting' WHERE id=:id AND status='queued'`; checks `result.rowcount` -- only the worker with `rowcount==1` proceeds; `rowcount==0` returns None (lost the race). The 'starting' status is a transient claim state; 04-01's `run_job` transitions it via `update_stage`.
  - `run_worker(settings, session_factory, bus=None)`: guard `if not settings.run_worker: return`; single asyncio task, NO `asyncio.gather` of multiple jobs (D-10); when `pull_next` returns None: `await asyncio.wait_for(_work_signal.wait(), timeout=2.0)` (Fix 1 -- 2s poll self-heals a missed signal), `_work_signal.clear()`, continue; else `await run_job(settings, session_factory, job_id, bus=bus)`. Catches run_job exceptions so one failed job does not stall the queue.
- `app/jobs/interrupt.py`: `mark_interrupted_failed(session, settings, session_factory) -> int`. `SELECT id FROM jobs WHERE status IN ('ingesting','transcribing')` (NOT 'queued', D-03). For each: `mark_failed(session, id, "interrupted (backend restarted)")` (DB row) + `atomic_write_json(manifest_path, {status='failed', current_stage='failed', error=...})` (Codex MEDIUM -- `update_stage` maps 'failed' to 'queued' incorrectly, so the documented `atomic_write_json` fallback is used). Keeps the folder (no rmtree). Returns count.
- `app/models/job.py`: `'starting'` added to `JobStatus` Literal (Rule 1 -- `get_job` raised ValidationError during the atomic-claim window).
- Tests: xfail removed from Task 2 tests; `_worker_settings` (run_worker=True) + `_reset_work_signal` helpers for test isolation.

### Task 3 -- Cooperative cancel + watchdog (commit d5a01d5)
- `app/jobs/queue.py` `cancel(job_id, session, settings) -> dict`: SELECT status; if terminal -> return row no-op (D-06); if 'queued' -> `cancel_job` (DB-first + rmtree) + `_work_signal.set()`; if 'starting'/'ingesting'/'transcribing' -> import `_running` from orchestrator, `flag.set()` (threading.Event -- 04-01 chunker checks at next chunk boundary and raises `JobCancelled`; orchestrator's `JobCancelled` path does `cancel_job` -- NO double-call, T-04-06). Race handling (T-04-09): if `_running.get(job_id)` is None, re-SELECT; if now terminal, return no-op. Returns `{status, id}`.
- `app/jobs/queue.py` `run_watchdog(settings, session_factory)`: guard `if not settings.run_worker: return`; loop: `await asyncio.sleep(60)`; `SELECT id FROM jobs WHERE status IN ('ingesting','transcribing')` (Codex MEDIUM -- excludes queued); for each `if is_stale(settings, job_id): await mark_stale(session, settings, job_id)` (reuses cleanup; status-aware gate short-circuits terminal). Single asyncio task; cancellable via Task 4 teardown.
- Tests: xfail removed from cancel + watchdog tests; watchdog switched to `_worker_settings` + `_reset_work_signal`.

### Task 4 -- Lifespan wiring (commit bf75ee4)
- `app/main.py` lifespan: AFTER `reconcile_all` and BEFORE `print("ready")`:
  1. `mark_interrupted_failed(session, settings, session_factory)` -- boot sweep (D-03, after reconcile, before worker).
  2. `app.state.bus = EventBus(); app.state.settings = settings; app.state.session_factory = session_factory` (Fix 7-partial for 04-03 WS handler).
  3. `worker_task = asyncio.create_task(run_worker(settings, session_factory, bus=bus))` + `watchdog_task = asyncio.create_task(run_watchdog(settings, session_factory))` guarded by `if settings.run_worker:`.
  4. Teardown (finally): cancel worker_task + watchdog_task (`return_exceptions=True`) BEFORE `engine.dispose()`. 04-01's graceful in-flight shutdown (`asyncio.wait_for(future, timeout=30.0)` + `cancel_flag.set()`) handles the sync thread exit before model unload.
- `asyncio` import added to main.py.

## Verification

- `pytest tests/test_cancel.py tests/test_orchestrator.py -x` -- 15 green (5 cancel + 10 orchestrator)
- Full suite: 240 passed (229 baseline + 11 new)
- `python -c "import ast; ast.parse(open('app/main.py').read())"` -- OK
- Boot sequence: reconcile_all -> mark_interrupted_failed -> run_worker -> run_watchdog (verifiable via lifespan order in app/main.py)
- Teardown: worker_task.cancel() + watchdog_task.cancel() (return_exceptions=True) BEFORE engine.dispose
- `grep "asyncio.gather" app/jobs/queue.py` -- only in comments (no concurrent job execution)
- `grep "status='queued'" app/jobs/queue.py` -- matches in pull_next atomic claim (Fix 6)
- `grep "wait_for.*_work_signal" app/jobs/queue.py` -- matches in run_worker (Fix 1)
- `grep "IN ('ingesting','transcribing')" app/jobs/interrupt.py app/jobs/queue.py` -- matches in both (sweep + watchdog)
- `grep "cancel_job" app/jobs/queue.py` -- only the queued-cancel path (running path sets _running flag, does NOT call cancel_job)
- `grep "app.state.bus\|app.state.settings\|app.state.session_factory" app/main.py` -- all three established (Fix 7-partial)
- No scope overlap: `grep "class EventBus\|def run_job\|progress_cb\|class JobCancelled\|heartbeat\|progress.json" app/jobs/queue.py app/jobs/interrupt.py` matches only a docstring reference to `progress.json` (no code)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added 'starting' to JobStatus Literal**
- **Found during:** Task 2
- **Issue:** `pull_next`'s atomic claim sets `status='starting'` as a transient claim state. `JobResponse.status` (a `JobStatus` Literal) did not include `'starting'`, so `get_job` raised `pydantic.ValidationError` during the claim window (between pull_next and run_job's first `update_stage`).
- **Fix:** Added `'starting'` to the `JobStatus` Literal in `app/models/job.py`. The API can now represent the transient claim state.
- **Files modified:** `app/models/job.py`
- **Commit:** 4eeda0b

**2. [Rule 2 - Critical] Worker loop catches run_job exceptions**
- **Found during:** Task 2
- **Issue:** The plan's `run_worker` loop calls `await run_job(...)` which re-raises non-cancel exceptions. Without a try/except, one failed job would kill the worker task and stall the entire queue (every subsequent queued job would never run).
- **Fix:** Wrapped the `run_job` call in `try/except Exception` with a warning log. `run_job` already does `mark_failed` + `bus.publish("failed")` before re-raising; the worker logs and continues to the next job.
- **Files modified:** `app/jobs/queue.py`
- **Commit:** 4eeda0b

**3. [Rule 1 - Bug] update_stage maps 'failed' to 'queued' -- used documented atomic_write_json fallback**
- **Found during:** Task 2
- **Issue:** The plan's primary path for `mark_interrupted_failed` was `update_stage(settings, session, id, "failed", ManifestPatch(error=...))`. But `stage_to_status("failed", manifest)` returns `_STAGE_STATUS_MAP.get("failed", "queued")` = `"queued"` (the stage map only covers active processing stages; 'failed' is a terminal status set directly by `mark_failed`/`cancel_job`, never via `update_stage`). Calling `update_stage("failed", ...)` would set the manifest status to `"queued"` -- corrupting the state.
- **Fix:** Used the documented fallback: `atomic_write_json(manifest_path, payload)` with `status='failed'`, `current_stage='failed'`, `error='interrupted (backend restarted)'` set directly on the manifest dict. The plan explicitly prescribes this fallback "if -- and only if -- update_stage rejects 'failed'".
- **Files modified:** `app/jobs/interrupt.py`
- **Commit:** 4eeda0b

**4. [Rule 3 - Blocking] Test isolation: module-level _work_signal across event loops**
- **Found during:** Task 2
- **Issue:** pytest-asyncio runs each test in a fresh event loop. The module-level `asyncio.Event _work_signal` created at import time could carry stale waiters / value from a prior test's loop, causing the hybrid-wakeup test to fail when run after the serial-concurrency test.
- **Fix:** Added `_reset_work_signal()` helper that recreates `queue_mod._work_signal = asyncio.Event()` before each worker test. Called at the top of `test_restart_rejoin_boot`, `test_serial_no_concurrency`, `test_hybrid_wakeup_no_signal`, and `test_watchdog_stale`.
- **Files modified:** `tests/test_orchestrator.py`
- **Commit:** 4eeda0b

## Known Stubs

None. The production adapter-load path (`_load_stt_adapter` in 04-01) is exercised by the worker tests via monkeypatching (tests inject a `FakeAdapter`); the real production path (model manager + `FasterWhisperAdapter`) is NOT exercised here -- it is exercised once the full app boots with a real GPU. The `cancel` function returns a plain `dict {status, id}` rather than a `JobResponse`; the route layer (04-03 or a future cancel route) will map it to a typed response.

## Threat Flags

None. All trust boundaries in the plan's `<threat_model>` are mitigated as specified:
- T-04-04: `_TERMINAL_STATUSES` gate first; terminal cancel = no-op.
- T-04-05: sweep selects `ingesting`/`transcribing` only (NOT `queued`); runs after reconcile, before worker; updates DB + manifest.
- T-04-06: running cancel sets `_running` flag only; orchestrator's `JobCancelled` path does `cancel_job` (no double-rmtree).
- T-04-07: watchdog SELECT filters to `ingesting`/`transcribing`; `mark_stale` has status-aware gate.
- T-04-08: single asyncio task, no `asyncio.gather` of jobs, strict FIFO `ORDER BY created_at`.
- T-04-09: if `_running.get(job_id)` is None, re-SELECT; terminal -> no-op.
- T-04-10: atomic claim via conditional UPDATE + rowcount check.
- T-04-11: hybrid Event+poll wakeup (2s timeout self-heals missed signal).
- T-04-12: enqueue guards `status IN ('created','queued')`.

## Self-Check: PASSED

- `app/jobs/queue.py` FOUND
- `app/jobs/interrupt.py` FOUND
- `tests/test_cancel.py` FOUND
- `app/main.py` contains `mark_interrupted_failed` + `run_worker` + `run_watchdog` + `app.state.bus` FOUND
- `app/models/job.py` contains `'starting'` in JobStatus FOUND
- commit 37d9ada FOUND
- commit 4eeda0b FOUND
- commit d5a01d5 FOUND
- commit bf75ee4 FOUND