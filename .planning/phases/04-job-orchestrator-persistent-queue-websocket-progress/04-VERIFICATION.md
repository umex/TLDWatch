---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
verified: 2026-06-23T11:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/5
  gaps_closed:
    - "SC-1 / state machine dead-end (CR-03): run_job now advances a crash-window job to done on resume via the new `if resume_stage == 'done':` branch (orchestrator.py:284-297). Regression test test_resume_advances_to_done_when_both_stages_complete GREEN."
    - "SC-2 / restart persistence holes (CR-01 + CR-02): boot sweep and watchdog SELECT widened to include 'starting'; mark_interrupted_failed now consults infer_resume_point per swept job and advances file-complete jobs to done instead of failing them. Regression tests test_starting_job_swept_to_failed + test_transcribed_job_advanced_to_done_on_boot GREEN."
    - "SC-4 / cooperative cancel not API-wired (WR-04): POST /jobs/{id}/cancel now calls queue.cancel (cooperative path) instead of destructive cleanup.cancel_job. API integration tests test_cancel_queued_via_api + test_cancel_running_via_api + test_cancel_terminal_via_api_idempotent GREEN."
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
human_verification: []
---

# Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress Verification Report

**Phase Goal:** The job state machine, persistent queue, and real-time progress broadcast exist as the spine of the app, so every later feature is just "add a stage."
**Verified:** 2026-06-23T11:00:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plans 04-04, 04-05, 04-06)

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| #   | Truth (Roadmap SC) | Status | Evidence |
| --- | --- | --- | --- |
| SC-1 | Submitting a job returns a job ID; the job moves through `queued → ingesting → transcribing → done` with atomic transitions guarded by stage-output files on disk. | VERIFIED | `update_stage` write-manifest-first/commit-DB-last; stage completion recorded only after output file exists (orchestrator.py:269-281). CR-03 CLOSED: new `if resume_stage == "done":` branch (orchestrator.py:284-297) advances a crash-window job (transcript.json on disk, manifest.current_stage="transcribed", DB status="transcribing") to done on re-entry, publishing the done event. Regression test `test_resume_advances_to_done_when_both_stages_complete` GREEN. Happy-path `test_state_machine` GREEN. |
| SC-2 | The job queue persists across back-end restarts — queued and in-flight jobs are re-joinable, with the orchestrator inferring the resume point from existing files. | VERIFIED | Queued re-join works (`test_restart_rejoin_boot` GREEN; FIFO order, hybrid wakeup, atomic claim). CR-01 CLOSED: `mark_interrupted_failed` SELECT (interrupt.py:97) and `run_watchdog` SELECT (queue.py:297-299) widened to `status IN ('starting','ingesting','transcribing')` — the transient `starting` status set by pull_next's atomic claim is now swept/watched. CR-02 CLOSED: `mark_interrupted_failed` consults `infer_resume_point` per swept job (interrupt.py:127-144); if `resume_point is None or "done"`, advances to done via `update_stage` (preserving the user's completed transcription) instead of failing. Regression tests `test_starting_job_swept_to_failed` (starting → failed, not advanced) and `test_transcribed_job_advanced_to_done_on_boot` (transcribed → done, transcript.json preserved) GREEN. |
| SC-3 | A WebSocket endpoint broadcasts per-job progress events (current stage, percent, ETA) that the front-end can subscribe to. | VERIFIED (regression) | `app/api/routes_ws.py` implements `/ws/jobs/{job_id}/events`; snapshot on connect sourced from job row + manifest + progress.json (Fix 9); live EventBus relay; SubscriberRegistry on app.state; subscriber cap enforced. 8 `test_ws.py` tests GREEN. Pre-existing edge-case warnings (snapshot-before-subscribe; registry.add outside try/finally) noted in original verification — not blockers, retained as follow-up. |
| SC-4 | The user can cancel a queued or running job; cancellation is idempotent and the job's partial files are cleaned up deterministically. | VERIFIED | WR-04 CLOSED: `post_cancel` (routes_jobs.py:132-170) now calls `queue.cancel` (imported as `queue_cancel` at line 30, called at line 164) — the cooperative D-06 path. The destructive `cleanup.cancel_job` import was removed from routes_jobs.py. `queue.cancel` three-state behavior: queued → cancel_job + _work_signal.set; running → set _running threading.Event (orchestrator's JobCancelled path does cancel_job + rmtree at next chunk boundary — no out-from-under rmtree); terminal → no-op returning row (D-06 idempotent); {} → 404. API integration tests `test_cancel_queued_via_api`, `test_cancel_running_via_api`, `test_cancel_terminal_via_api_idempotent` GREEN. |
| SC-5 | The double-submit problem is handled — a `POST /jobs` with the same idempotency key returns the existing job ID instead of creating a duplicate. | VERIFIED (regression) | `app/api/idempotency.py::resolve_or_create` (atomic key-first reservation — INSERT idempotency_keys row BEFORE create_job; IntegrityError catch re-reads existing job_id, no orphan duplicate); `validate_idempotency_key` (regex `^[A-Za-z0-9_-]{1,128}$`, 128 cap, ValueError→422); `run_janitor` (TTL delete). `migrations/0008_idempotency_keys.sql` uses `idempotency_key TEXT PRIMARY KEY` (Fix 7). `post_job` reads Idempotency-Key header, returns 201/200/422 per-response. 8 `test_idempotency.py` tests GREEN. |

**Score:** 5/5 SCs verified. All 3 previous BLOCKER gaps (CR-01, CR-02, CR-03) and the 1 previous BLOCKER gap (WR-04) closed; no regressions.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/jobs/errors.py` | `JobCancelled(Exception)` with `job_id` attribute (Fix 5 neutral module) | VERIFIED | `class JobCancelled(Exception)` at line 20; chunker imports horizontally from `app.jobs.errors`. |
| `app/jobs/orchestrator.py` | `run_job` state-machine driver with infer_resume_point stage-skip + functools.partial executor + graceful in-flight shutdown + heartbeat + progress snapshot + CR-03 resume-advance | VERIFIED | `async def run_job` exists; `infer_resume_point` at top (line 204); `functools.partial` (line 257); `asyncio.wait_for(future, timeout=30.0)` in finally (line 321); `_persist_progress` writes progress.json; CR-03 advance branch at lines 284-297. |
| `app/jobs/progress.py` | EventBus pub/sub + drop-oldest backpressure (maxsize=32) | VERIFIED | `class EventBus`; subscribe/publish/unsubscribe/has_subscribers; QueueFull drop-oldest. 7 `test_event_bus.py` tests GREEN. |
| `app/models/stt/protocol.py` | ChunkProgress + STTAdapter.transcribe kw-only progress_cb/cancel_flag | VERIFIED | `class ChunkProgress`; `progress_cb`/`cancel_flag` kw-only. |
| `app/models/stt/adapter.py` | FasterWhisperAdapter.transcribe accepts kw-only pair (Fix 8) | VERIFIED | Accepts `progress_cb`/`cancel_flag` for Protocol conformance. |
| `app/models/stt/chunker.py` | transcribe_file kw-only pair; per-chunk emit + cancel check at loop top; imports JobCancelled from app.jobs.errors | VERIFIED | `progress_cb`/`cancel_flag` kw-only; cancel check at loop top; progress emit after chunk_count; `from app.jobs.errors import JobCancelled`. |
| `app/jobs/resume.py` | D-04 generalized ingested check (manifest.source_path OR source.<ext>) | VERIFIED | `is_stage_complete("ingested", ...)` — manifest.source_path first, then source.<ext> glob fallback. |
| `app/storage/fs.py` | `_STAGE_FILE_NAMES` includes `progress.json` (Fix 2) | VERIFIED | `_STAGE_FILE_NAMES` includes `"progress.json"`. |
| `app/jobs/queue.py` | SQLite FIFO queue with atomic claiming + single-worker hybrid-wakeup loop + cancel + watchdog (SELECT includes 'starting') | VERIFIED | `run_worker`, `enqueue`, `pull_next` (atomic claim), `cancel` (cooperative three-state), `run_watchdog` (SELECT widened to include 'starting'). |
| `app/jobs/interrupt.py` | Boot interrupted-job sweep — SELECT includes 'starting'; consults infer_resume_point; advances file-complete jobs to done | VERIFIED | `mark_interrupted_failed` SELECT covers `('starting','ingesting','transcribing')`; per-job `infer_resume_point` consultation; advance-to-done branch when `resume_point is None or "done"`; mark_failed + failed-manifest fallback otherwise. |
| `app/main.py` | Lifespan wiring of sweep/worker/watchdog with ordered teardown + app.state | VERIFIED | `mark_interrupted_failed` after reconcile_all; `app.state.bus/settings/session_factory/subscribers`; worker+watchdog+janitor tasks guarded by `run_worker`; teardown cancels tasks before engine.dispose. |
| `app/api/routes_ws.py` | WebSocket endpoint + SubscriberRegistry + snapshot from progress.json (Fix 9) | VERIFIED | `class SubscriberRegistry`; `@router.websocket("/ws/jobs/{job_id}/events")`; snapshot reads progress.json. Pre-existing edge-case warnings retained as follow-up (not blockers). |
| `app/api/idempotency.py` | validate_idempotency_key + resolve_or_create (atomic key-first) + run_janitor | VERIFIED | All three functions present; key-first reservation flow; `_is_integrity_error` handles SQLAlchemy + sqlite3. |
| `app/api/routes_jobs.py` | `post_cancel` wired to `queue.cancel` (cooperative path); `cancel_job` import removed | VERIFIED | Line 30 `from app.jobs.queue import cancel as queue_cancel`; line 164 `await queue_cancel(canonical_id, session, settings)`; no `cancel_job` import from cleanup; `{}` → 404, terminal → 200 no-op, running → 200 current row. |
| `migrations/0008_idempotency_keys.sql` | idempotency_keys table with column `idempotency_key` | VERIFIED | `CREATE TABLE IF NOT EXISTS idempotency_keys (idempotency_key TEXT PRIMARY KEY, ...)`; index on created_at. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| orchestrator.py | manifest.py::update_stage | `await update_stage(settings, session, job_id, stage, ManifestPatch(...))` | WIRED | Every stage transition via update_stage; no raw `UPDATE jobs` in orchestrator (grep returns 0). |
| orchestrator.py | chunker.py::transcribe_file | `loop.run_in_executor(None, functools.partial(transcribe_file, ...))` | WIRED | Fix 3 — functools.partial wraps kwargs. |
| orchestrator.py | progress.py::EventBus.publish | `loop.call_soon_threadsafe(_publish, event)` | WIRED | Progress marshalled from worker thread to asyncio loop. |
| orchestrator.py | resume.py::infer_resume_point | `infer_resume_point(settings, job_id, manifest)` at top + CR-03 advance on `"done"` | WIRED | Line 204; resume_stage == "done" branch at line 284 now advances. |
| chunker.py | errors.py::JobCancelled | `from app.jobs.errors import JobCancelled` (horizontal) | WIRED | Fix 5 preserved. |
| main.py lifespan | interrupt.py::mark_interrupted_failed | `await mark_interrupted_failed(session, settings, session_factory)` | WIRED | Runs after reconcile_all, before worker. |
| main.py lifespan | queue.py::run_worker | `asyncio.create_task(run_worker(settings, session_factory, bus=bus))` | WIRED | Guarded by `settings.run_worker`. |
| queue.py::pull_next | atomic claim | `UPDATE jobs SET status='starting' WHERE id=:id AND status='queued'` + rowcount check | WIRED | Fix 6 — only rowcount==1 proceeds. |
| queue.py::run_worker | hybrid wakeup | `asyncio.wait_for(_work_signal.wait(), timeout=2.0)` | WIRED | Fix 1. |
| queue.py::cancel (running) | orchestrator.py::_running | `from app.jobs.orchestrator import _running; _running[job_id].set()` | WIRED | queue.py:228-232. |
| routes_jobs.py::post_cancel | queue.py::cancel | `await queue_cancel(canonical_id, session, settings)` | WIRED | WR-04 CLOSED — routes_jobs.py:164. `cancel_job` import removed; no destructive direct call. |
| routes_jobs.py::post_job | idempotency.py::resolve_or_create | `await resolve_or_create(request, session, settings, ...)` | WIRED | 201/200/422 per-response. |
| routes_ws.py | progress.py::EventBus via app.state.bus | `bus.subscribe(job_id)` + relay loop | WIRED | Pre-existing snapshot-before-subscribe race noted as follow-up (not a blocker). |
| routes_ws.py | job row + manifest + progress.json | snapshot on connect | WIRED | Fix 9 `_read_progress_snapshot` reads percent/eta. |
| interrupt.py::mark_interrupted_failed | resume.py::infer_resume_point + manifest.py::update_stage | `resume_point = infer_resume_point(...)`; `await update_stage(settings, session, job_id, "done")` | WIRED | CR-02 closed — advance-to-done branch at interrupt.py:127-144. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| orchestrator.py progress.json write | `snapshot` dict (chunks_done, chunks_total, percent, eta_s, updated_at) | ChunkProgress from chunker -> `_on_progress` -> `_persist_progress` -> `atomic_write_json` | Yes — driven by real chunk callbacks | FLOWING |
| routes_ws.py snapshot | `snapshot` dict (stage, percent, eta, status) | `get_job` (DB row) + `read_manifest` + `_read_progress_snapshot(progress.json)` | Yes — reads the file orchestrator wrote | FLOWING |
| idempotency.py resolve_or_create | `(response, status_code)` | `validate_idempotency_key` -> `INSERT INTO idempotency_keys` -> `create_job_fn(job_id=pending)` -> return (201) OR IntegrityError catch -> SELECT existing -> (200) | Yes — DB-backed reservation | FLOWING |
| queue.py run_worker | `job_id` from `pull_next` | `SELECT ... WHERE status='queued' ORDER BY created_at LIMIT 1` -> conditional `UPDATE ... SET status='starting' WHERE id=:id AND status='queued'` | Yes — DB queue | FLOWING |
| interrupt.py mark_interrupted_failed | `resume_point` per swept job | `read_manifest` -> `infer_resume_point(settings, job_id, manifest)` -> advance-to-done or mark_failed | Yes — file-as-truth resume walker drives the decision | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase 4 full suite collects | `python -m pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_cancel.py tests/test_ws.py tests/test_idempotency.py --co -q` | 44 tests collected | PASS |
| Phase 4 full suite passes | `python -m pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_cancel.py tests/test_ws.py tests/test_idempotency.py -q` | 44 passed, 3 warnings in 4.95s | PASS |
| CR-03 regression test passes | `python -m pytest tests/test_orchestrator.py::test_resume_advances_to_done_when_both_stages_complete -x -q` | 1 passed | PASS |
| CR-01 regression test passes | `python -m pytest tests/test_orchestrator.py::test_starting_job_swept_to_failed -x -q` | 1 passed | PASS |
| CR-02 regression test passes | `python -m pytest tests/test_orchestrator.py::test_transcribed_job_advanced_to_done_on_boot -x -q` | 1 passed | PASS |
| WR-04 API integration tests pass | `python -m pytest tests/test_cancel.py::test_cancel_queued_via_api tests/test_cancel.py::test_cancel_running_via_api tests/test_cancel.py::test_cancel_terminal_via_api_idempotent -v` | 3 passed | PASS |
| JobCancelled lives in errors.py | `grep -n "class JobCancelled" app/jobs/errors.py` | line 20 | PASS |
| chunker imports JobCancelled horizontally | `grep "from app.jobs.orchestrator import JobCancelled" app/models/stt/chunker.py` | no match | PASS (Fix 5 preserved) |
| No raw UPDATE jobs in orchestrator | `grep -c "UPDATE jobs" app/jobs/orchestrator.py` | 0 | PASS |
| progress.json in _STAGE_FILE_NAMES | `grep "progress.json" app/storage/fs.py` | match | PASS |
| idempotency_key column name | `grep "idempotency_key TEXT PRIMARY KEY" migrations/0008_idempotency_keys.sql` | match | PASS |
| post_cancel wired to queue.cancel | `grep -c "from app.jobs.queue import cancel" app/api/routes_jobs.py` | 1 | PASS (WR-04 closed) |
| post_cancel no longer calls cleanup.cancel_job | `grep -c "from app.jobs.cleanup import cancel_job" app/api/routes_jobs.py` | 0 | PASS (WR-04 closed) |
| 'starting' included in boot sweep SELECT | `grep -c "IN ('starting','ingesting','transcribing')" app/jobs/interrupt.py` | matches (docstring + code) | PASS (CR-01 closed) |
| 'starting' included in watchdog SELECT | `grep "IN ('starting','ingesting','transcribing')" app/jobs/queue.py` | match at line 298 | PASS (CR-01 closed) |
| infer_resume_point consulted in sweep | `grep -c "infer_resume_point" app/jobs/interrupt.py` | 6 (import + docstring + call) | PASS (CR-02 closed) |
| CR-03 advance branch present | `grep -n 'resume_stage == "done"' app/jobs/orchestrator.py` | 1 match at line 284 | PASS (CR-03 closed) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared by the plans. Step 7c: SKIPPED (no probes).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| JOB-02 | 04-01 | Jobs run in the background — user can navigate away and return to status | SATISFIED | run_job drives stages asynchronously; worker task runs in lifespan; status persists in DB. REQUIREMENTS.md marks Complete. |
| JOB-04 | 04-02 (CR-01/CR-02 closure in 04-05) | Job queue state persists across app restarts | SATISFIED | Queued re-join works; in-flight crash windows (starting status, transcribed-but-not-done) now recovered via widened SELECT + infer_resume_point consultation. REQUIREMENTS.md marks Complete. |
| JOB-05 | 04-02 (WR-04 closure in 04-06) | User can cancel a queued or running job | SATISFIED | POST /jobs/{id}/cancel wired to cooperative queue.cancel; queued/running/terminal three-state behavior; idempotent terminal no-op; API integration tests GREEN. REQUIREMENTS.md marks Complete. |
| JOB-06 | 04-03 | User sees per-job progress (current stage, percent, ETA) in real time | SATISFIED | WS endpoint broadcasts snapshot + live events; progress.json + EventBus relay; ETA hidden until chunks_done >= 2 (D-09). (REQUIREMENTS.md marks Pending — that flag is stale; the implementation is in place and verified.) |

No orphaned requirements — all four IDs (JOB-02, JOB-04, JOB-05, JOB-06) appear in plan frontmatter and are mapped to truths.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| app/jobs/queue.py | 215-222 | WR-01 (04-REVIEW): queued-cancel race silently loses the cancel — `cancel_job`'s UPDATE has no status guard, so a row claimed (`starting`) between SELECT and UPDATE gets flipped to `cancelled` out from under the running worker | Warning (non-blocking) | Narrow window, silent cancel-loss. Does not block the phase goal (the spine is in place). Recommend follow-up: make `cancel_job`'s UPDATE conditional on `status NOT IN ('done','failed','cancelled')`, or have `queue.cancel` re-SELECT-then-UPDATE with `WHERE status='queued'` and route `rowcount == 0` to the active branch. |
| app/jobs/orchestrator.py | 284-297 | WR-02 (04-REVIEW): CR-03 resume-advance branch ignores `cancel_flag` — a cancel during the resume window (transcript.json on disk, current_stage='transcribed') gets dropped; the job advances to done instead of cancelling | Warning (non-blocking) | Narrow window; violates D-06 cooperative-cancel contract in an edge case. Does not block the phase goal. Recommend follow-up: check `cancel_flag.is_set()` before the advance and `raise JobCancelled(...)` to route to the existing except-handler. |
| app/jobs/orchestrator.py | 322 | IN-01: redundant exception tuple `except (asyncio.TimeoutError, JobCancelled, Exception)` (Exception subsumes the others) | Info | Misleading; not a bug. |
| app/api/routes_jobs.py | 164-170 | IN-02: `post_cancel` discards `queue_cancel`'s returned status dict and re-queries via `get_job` — for a running cancel the response shows `status='transcribing'` until the orchestrator flips it | Info | Eventual-consistency UX nit; document or build response from the dict. |
| app/jobs/orchestrator.py | 165-173 | IN-03: `_persist_progress` write may race with `cancel_job`'s rmtree (log noise, caught) | Info | Log noise only. |
| app/jobs/interrupt.py | 158-159 | IN-04: redundant final `session.commit()` in `mark_interrupted_failed` (per-iteration commits already happened) | Info | Misleading; not a bug. |
| app/jobs/orchestrator.py | 119-120 | IN-05: `_running[job_id]` unconditional assignment could orphan a prior flag on double-invoke | Info | D-10 prevents in production; defense-in-depth only. |
| app/jobs/interrupt.py | 127-144 | IN-06: CR-02 advance path does not catch `FileNotFoundError` from `update_stage`'s re-read of manifest | Info | Narrow window; sweep aborts with partial state (re-runnable on next boot). |
| app/jobs/orchestrator.py | 156 | `datetime.now().isoformat()` (naive local time) in progress.json `updated_at` | Info (WR-03 from original verification) | Not comparable to UTC timestamps in the app. Follow-up. |

No TBD/FIXME/XXX debt markers found in modified files. Step 7 debt-marker gate: PASS.

### Human Verification Required

None. All gaps are observable programmatically in the code; the remaining warnings (WR-01/WR-02 from 04-REVIEW) are narrow race conditions that need code-level fixes (not human UI/UX testing) and do not block the phase goal.

### Gaps Summary

No gaps remain. All 4 previous BLOCKER-class gaps are closed with TDD-gated regression tests (RED → GREEN commits present in git log per the gap-closure summaries):

1. **CR-03 (state machine dead-end) — CLOSED by plan 04-04.** `run_job` now has a final `if resume_stage == "done":` branch (orchestrator.py:284-297) that advances a crash-window job to done on re-entry, publishing the done event. Regression test `test_resume_advances_to_done_when_both_stages_complete` GREEN.

2. **CR-01 (stuck `starting` status) — CLOSED by plan 04-05.** `mark_interrupted_failed` (interrupt.py:97) and `run_watchdog` (queue.py:297-299) SELECT filters widened to `('starting','ingesting','transcribing')`. A crashed-in-claim job is now recovered on the next boot. Regression test `test_starting_job_swept_to_failed` GREEN.

3. **CR-02 (completed transcription orphaned) — CLOSED by plan 04-05.** `mark_interrupted_failed` now consults `infer_resume_point` per swept job (interrupt.py:127-144); if the resume walker says the stages are file-complete (`resume_point is None or "done"`), the sweep advances the job to done via `update_stage` instead of failing it — preserving the user's completed transcription. Regression test `test_transcribed_job_advanced_to_done_on_boot` GREEN.

4. **WR-04 (cooperative cancel not API-wired) — CLOSED by plan 04-06.** `POST /jobs/{id}/cancel` now calls `queue.cancel` (routes_jobs.py:30,164) — the cooperative D-06 path. The destructive `cleanup.cancel_job` import was removed. Three API integration tests (queued / running / terminal) GREEN.

The full Phase 4 test suite (44 tests) passes with no regressions. SC-3 (WS broadcast) and SC-5 (idempotent submit) retained their VERIFIED status through the gap-closure work.

### Follow-up Items (non-blocking, do not affect phase goal)

The 04-REVIEW.md code review surfaced two narrow race-condition warnings (WR-01, WR-02) that survived the closure. They are real but narrow-window, silent-failure rather than crash/data-loss, and do not undermine the "spine of the app" phase goal. They are recommended for a future hardening pass (not a Phase 4 blocker):

- **WR-01:** `cancel_job`'s UPDATE has no status guard — a queued-cancel racing the worker's atomic claim can silently flip a `starting` row to `cancelled` out from under the running worker.
- **WR-02:** The CR-03 resume-advance branch never checks `cancel_flag.is_set()` — a cancel during the resume window is dropped on the floor and the job advances to done.

The pre-existing WS edge-case warnings (snapshot-before-subscribe; registry.add outside try/finally) and the naive-local-time `updated_at` in progress.json (WR-03) are also retained as follow-up.

---

_Verified: 2026-06-23T11:00:00Z_
_Verifier: Claude (gsd-verifier)_