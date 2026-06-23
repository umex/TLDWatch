---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
verified: 2026-06-23T01:00:00Z
status: gaps_found
score: 2/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: N/A
  gaps_closed: []
  gaps_remaining: []
  regressions: []
gaps:
  - truth: "SC-1 / state machine: a submitted job moves queued -> ingesting -> transcribing -> done (including the re-entrant resume path)"
    status: failed
    reason: "run_job cannot advance a job to `done` on resume when both `skip_ingested` and `skip_transcribed` are True but `manifest.current_stage != \"done\"`. `update_stage(\"done\")` is only called inside the `if not skip_transcribed:` block (orchestrator.py:280-281); if both stages are already complete (e.g. a crash between update_stage(\"transcribed\") and update_stage(\"done\"), or a transient DB error on the done commit), the orchestrator falls through both `if` blocks and returns. The job is stuck in `transcribing` status forever. CR-03 from 04-REVIEW.md — confirmed against code at app/jobs/orchestrator.py:211-282."
    artifacts:
      - path: "app/jobs/orchestrator.py"
        issue: "No final update_stage(\"done\") advancement when both skip_ingested and skip_transcribed are True. `infer_resume_point` returns \"done\" (because is_stage_complete(\"done\",...) is False when current_stage != \"done\"), run_job does not early-return (only early-returns when resume_stage is None), but neither stage block runs. Function exits without advancing."
    missing:
      - "After the two `if not skip_*` blocks, if `resume_stage == \"done\"` (or `skip_ingested and skip_transcribed and manifest.current_stage != \"done\"`), call `update_stage(settings, session, job_id, \"done\")` and publish `{\"type\":\"done\"}`."
      - "Add a regression test that simulates a crash between update_stage(\"transcribed\") and update_stage(\"done\") and asserts run_job re-enters and advances to done."
  - truth: "SC-2 / restart persistence: in-flight jobs that crash during restart are recovered or swept (no permanently-stuck unrecoverable state)"
    status: failed
    reason: "Two crash windows leave jobs permanently unrecoverable. CR-01: `mark_interrupted_failed` (interrupt.py:78-82) and `run_watchdog` (queue.py:295-300) select only `status IN ('ingesting','transcribing')`. The transient `starting` status set by pull_next's atomic claim (between `UPDATE ... status='starting'` and run_job's first `update_stage(\"ingested\")`) is NOT swept or watched. If the process dies during that window, the job remains `starting` in the DB forever: pull_next skips it (not `queued`), the watchdog never marks it stale, the boot sweep never fails it, and `queue.cancel` cannot recover it after a restart because `_running` is empty (module reloaded) — re-SELECT shows `starting` (not terminal), the function logs a warning and returns without flipping it. CR-02: `mark_interrupted_failed` selects jobs by status without checking whether their stages are actually complete. A job that crashed AFTER `update_stage(\"transcribed\")` (DB status becomes `transcribing` via stage_to_status) but BEFORE `update_stage(\"done\")` has a complete `transcript.json` on disk and `manifest.current_stage == \"transcribed\"`. On restart the sweep sees status=`transcribing` and marks the job `failed` — orphaning the user's completed transcription. `infer_resume_point` would have returned `done` (only the derived done transition remains), but the sweep never consults it. CR-01 + CR-02 confirmed against app/jobs/interrupt.py:78-82 and app/jobs/queue.py:295-300."
    artifacts:
      - path: "app/jobs/interrupt.py"
        issue: "SELECT filters to `status IN ('ingesting','transcribing')` — excludes `starting`. No `infer_resume_point` / `read_manifest` check before marking a job failed, so completed-but-not-done transcriptions are orphaned."
      - path: "app/jobs/queue.py"
        issue: "run_watchdog SELECT filters to `status IN ('ingesting','transcribing')` — excludes `starting`. A stuck `starting` job is never marked stale."
    missing:
      - "Add `'starting'` to the SELECT status filters in both `mark_interrupted_failed` and `run_watchdog` (or have run_job call `update_stage(\"ingested\")` as the very first DB write so the `starting` window is zero-width)."
      - "In `mark_interrupted_failed`, before calling mark_failed, consult `infer_resume_point(settings, job_id, manifest)` for each swept job. If `resume_point is None or resume_point == 'done'`, advance the job to `done` instead of failing it (the stages are actually complete; only the derived done transition remains)."
      - "Add regression tests: (a) a job in `starting` at boot is swept to failed; (b) a job with transcript.json on disk + manifest.current_stage='transcribed' at boot is advanced to done, not marked failed."
  - truth: "SC-4 / cancel: the user can cancel a queued OR running job via the API; cancellation is idempotent and partial files are cleaned up deterministically (D-06 cooperative cancel)"
    status: failed
    reason: "The cooperative `queue.cancel` (sets the threading.Event cancel_flag for running jobs, lets the orchestrator's JobCancelled path do clean cancel_job + rmtree — no double-rmtree) is implemented and tested (tests/test_cancel.py passes) but is NOT wired to any API route. The existing `POST /jobs/{job_id}/cancel` route (`post_cancel` at routes_jobs.py:131-155) calls `cleanup.cancel_job` directly, which marks the DB row cancelled and rmtrees the folder. For a RUNNING job, this rmtrees the folder out from under the orchestrator — the orchestrator's subsequent `atomic_write_json(transcript.json)` fails (directory gone), the exception handler calls `mark_failed` (which may conflict with the already-cancelled row), and the model is unloaded in the finally block. This is destructive and non-cooperative, not the D-06 contract the phase promises. JOB-04 is only partially satisfied: queued cancel works through the API; running cancel through the API is destructive. WR-04 from 04-REVIEW.md — confirmed: `queue.cancel` is not imported into routes_jobs.py (grep returns nothing)."
    artifacts:
      - path: "app/api/routes_jobs.py"
        issue: "`post_cancel` calls `cleanup.cancel_job` directly instead of `queue.cancel`. The cooperative cancel path (queue.cancel -> _running flag.set() -> orchestrator's JobCancelled path) is unreachable from the API."
    missing:
      - "Wire `post_cancel` to call `queue.cancel(job_id, session, settings)` (the cooperative path). Map the returned `{status, id}` dict to a JobResponse. Handle the {} -> 404 and terminal-no-op cases."
      - "Add an API-level integration test that cancels a running job via POST /jobs/{id}/cancel and asserts the orchestrator's JobCancelled path fires (status -> cancelled, no partial transcript.json, no double-rmtree)."
deferred: []
human_verification: []
---

# Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress Verification Report

**Phase Goal:** In-process job runner, SQLite-backed queue with restart persistence, state machine with file-as-truth, real-time progress broadcast.
**Verified:** 2026-06-23T01:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| #   | Truth (Roadmap SC) | Status | Evidence |
| --- | --- | --- | --- |
| SC-1 | Submitting a job returns a job ID; the job moves through `queued → ingesting → transcribing → done` with atomic transitions guarded by stage-output files on disk. | PARTIAL → FAILED | Happy path works (`test_state_machine` GREEN; `update_stage` write-manifest-first/commit-DB-last; stage completion recorded only after output file exists per Fix 4 — orchestrator.py:269-281). BUT CR-03: run_job cannot advance a job to `done` on resume when both `skip_ingested` and `skip_transcribed` are True but `current_stage != "done"`. `update_stage("done")` is only inside the `if not skip_transcribed:` block (orchestrator.py:280-281). A crash between `update_stage("transcribed")` and `update_stage("done")` leaves the job stuck in `transcribing` forever — the state machine has a dead-end state. |
| SC-2 | The job queue persists across back-end restarts — queued and in-flight jobs are re-joinable, with the orchestrator inferring the resume point from existing files. | PARTIAL → FAILED | Queued re-join works (`test_restart_rejoin_boot` GREEN; FIFO order, hybrid wakeup, atomic claim). BUT CR-01: jobs that crash in the transient `starting` status (between pull_next's atomic claim and run_job's first update_stage) are never swept — `mark_interrupted_failed` and `run_watchdog` both SELECT only `('ingesting','transcribing')` (interrupt.py:78-82, queue.py:295-300), so a stuck `starting` job is permanently unrecoverable (pull_next skips it, watchdog never marks it stale, cancel cannot flip it after restart). AND CR-02: a job that crashed after `update_stage("transcribed")` but before `update_stage("done")` has a complete `transcript.json` on disk but is marked `failed` on restart without checking stage completion — the user's completed transcription is orphaned. |
| SC-3 | A WebSocket endpoint broadcasts per-job progress events (current stage, percent, ETA) that the front-end can subscribe to. | VERIFIED | `app/api/routes_ws.py` implements `/ws/jobs/{job_id}/events`; snapshot on connect sourced from job row + manifest + 04-01 `progress.json` (Fix 9 — `_read_progress_snapshot` at routes_ws.py:105-128 reads `percent`+`eta_s`); live EventBus relay (routes_ws.py:191-204); SubscriberRegistry class on app.state (routes_ws.py:57-102); subscriber cap enforced (T-04-02). `test_ws.py` 8 tests GREEN. Warnings WR-01/WR-02 noted below (snapshot sent before bus.subscribe; registry.add outside try/finally) — edge cases, not blockers. |
| SC-4 | The user can cancel a queued or running job; cancellation is idempotent and the job's partial files are cleaned up deterministically. | PARTIAL → FAILED | The cooperative `queue.cancel` (queue.py:176-263) is implemented and tested (`test_cancel.py` 3 tests GREEN): queued -> cancel_job + _work_signal.set; running -> set _running threading.Event, let orchestrator's JobCancelled path do cancel_job (no double-rmtree); terminal -> no-op returning row. BUT WR-04: `queue.cancel` is NOT wired to any API route. The actual `POST /jobs/{job_id}/cancel` route (routes_jobs.py:131-155) calls `cleanup.cancel_job` directly, which rmtrees the folder out from under a running orchestrator — destructive, non-cooperative, non-deterministic post-rmtree orchestrator behavior. The user-facing API does not deliver the D-06 cooperative-cancel contract for running jobs. |
| SC-5 | The double-submit problem is handled — a `POST /jobs` with the same idempotency key returns the existing job ID instead of creating a duplicate. | VERIFIED | `app/api/idempotency.py` implements `validate_idempotency_key` (regex `^[A-Za-z0-9_-]{1,128}$`, 128 cap, ValueError->422), `resolve_or_create` (atomic key-first reservation — INSERT idempotency_keys row BEFORE create_job; IntegrityError catch re-reads existing job_id, no orphan duplicate), `run_janitor` (TTL delete). `migrations/0008_idempotency_keys.sql` uses column `idempotency_key TEXT PRIMARY KEY` (NOT `key` — Fix 7). `post_job` (routes_jobs.py:50-96) reads Idempotency-Key header, calls resolve_or_create, returns 201/200/422 per-response. `test_idempotency.py` 8 tests GREEN. |

**Score:** 2/5 SCs fully verified (SC-3, SC-5). 3 SCs have gaps (SC-1, SC-2, SC-4) — all BLOCKER-class.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `app/jobs/errors.py` | `JobCancelled(Exception)` with `job_id` attribute (Fix 5 neutral module) | VERIFIED | `class JobCancelled(Exception)` at line 20; chunker imports horizontally from `app.jobs.errors` (Fix 5). |
| `app/jobs/orchestrator.py` | `run_job` state-machine driver with infer_resume_point stage-skip + functools.partial executor + graceful in-flight shutdown + heartbeat + progress snapshot | WIRED but BUGGY | `async def run_job` exists; `infer_resume_point` called at top (line 204); `functools.partial` (line 257); `asyncio.wait_for(future, timeout=30.0)` in finally (line 306); `_persist_progress` writes progress.json (lines 131-163). CR-03: no `update_stage("done")` advancement when both skip flags True. |
| `app/jobs/progress.py` | EventBus pub/sub + drop-oldest backpressure (maxsize=32) | VERIFIED | `class EventBus` at line 37; `subscribe`/`publish`/`unsubscribe`/`has_subscribers`; QueueFull drop-oldest. `test_event_bus.py` 7 tests GREEN. |
| `app/models/stt/protocol.py` | ChunkProgress + STTAdapter.transcribe kw-only progress_cb/cancel_flag | VERIFIED | `class ChunkProgress` at line 79; `progress_cb` + `cancel_flag` kw-only at lines 140-141. |
| `app/models/stt/adapter.py` | FasterWhisperAdapter.transcribe accepts kw-only pair (Fix 8) | VERIFIED | Accepts `progress_cb`/`cancel_flag` for Protocol conformance (does not consult them; chunker owns cancel/progress). |
| `app/models/stt/chunker.py` | transcribe_file kw-only pair; per-chunk emit + cancel check at loop top; imports JobCancelled from app.jobs.errors | VERIFIED | `progress_cb`/`cancel_flag` at lines 94-95; cancel check at loop top (line 195); progress emit after chunk_count (line 236); `from app.jobs.errors import JobCancelled`. |
| `app/jobs/resume.py` | D-04 generalized ingested check (manifest.source_path OR source.<ext>) | VERIFIED | `is_stage_complete("ingested", ...)` at lines 157-181: FIRST manifest.source_path resolves to non-empty file, THEN source.<ext> glob fallback. |
| `app/storage/fs.py` | `_STAGE_FILE_NAMES` includes `progress.json` (Fix 2 root cause) | VERIFIED | `_STAGE_FILE_NAMES` includes `"progress.json"` at line 56. |
| `app/jobs/queue.py` | SQLite FIFO queue with atomic claiming + single-worker hybrid-wakeup loop + cancel + watchdog | WIRED but BUGGY | `run_worker`, `enqueue`, `pull_next` (atomic claim — Fix 6), `cancel`, `run_watchdog` all exist. CR-01: watchdog + boot sweep SELECT exclude `starting`. |
| `app/jobs/interrupt.py` | Boot interrupted-job sweep — updates DB AND manifest | WIRED but BUGGY | `mark_interrupted_failed` exists; updates DB via mark_failed + manifest via atomic_write_json (Codex MEDIUM — update_stage rejects 'failed' so documented fallback used). CR-01: excludes `starting`. CR-02: no infer_resume_point consultation. |
| `app/main.py` | Lifespan wiring of sweep/worker/watchdog with ordered teardown + app.state | VERIFIED | `mark_interrupted_failed` called after reconcile_all (line 229); `app.state.bus/settings/session_factory/subscribers` established (lines 244-252); worker+watchdog+janitor tasks created guarded by `run_worker` (lines 262-291); teardown cancels tasks before engine.dispose (lines 308-316). |
| `app/api/routes_ws.py` | WebSocket endpoint + SubscriberRegistry + snapshot from progress.json (Fix 9) | VERIFIED (with warnings) | `class SubscriberRegistry` (line 57); `@router.websocket("/ws/jobs/{job_id}/events")` (line 131); snapshot reads progress.json (line 179). WR-01/WR-02 edge cases noted. |
| `app/api/idempotency.py` | validate_idempotency_key + resolve_or_create (atomic key-first) + run_janitor | VERIFIED | All three functions present; key-first reservation flow at lines 140-243; `_is_integrity_error` handles both SQLAlchemy + sqlite3 forms. |
| `migrations/0008_idempotency_keys.sql` | idempotency_keys table with column `idempotency_key` | VERIFIED | `CREATE TABLE IF NOT EXISTS idempotency_keys (idempotency_key TEXT PRIMARY KEY, ...)`; index on created_at. Auto-discovered (no db.py change). |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| orchestrator.py | manifest.py::update_stage | `await update_stage(settings, session, job_id, stage, ManifestPatch(...))` | WIRED | Every stage transition via update_stage; no raw `UPDATE jobs` (grep returns 0). |
| orchestrator.py | chunker.py::transcribe_file | `loop.run_in_executor(None, functools.partial(transcribe_file, ...))` | WIRED | Fix 3 — functools.partial wraps kwargs (orchestrator.py:255-266). |
| orchestrator.py | progress.py::EventBus.publish | `loop.call_soon_threadsafe(_publish, event)` | WIRED | Progress marshalled from worker thread to asyncio loop (orchestrator.py:197). |
| orchestrator.py | resume.py::infer_resume_point | `infer_resume_point(settings, job_id, manifest)` at top | WIRED | Line 204. CR-03: result not fully acted on when resume_stage == "done". |
| chunker.py | errors.py::JobCancelled | `from app.jobs.errors import JobCancelled` (horizontal) | WIRED | Fix 5 preserved (grep confirms not imported from orchestrator). |
| main.py lifespan | interrupt.py::mark_interrupted_failed | `await mark_interrupted_failed(session, settings, session_factory)` | WIRED | Line 229; runs after reconcile_all, before worker. |
| main.py lifespan | queue.py::run_worker | `asyncio.create_task(run_worker(settings, session_factory, bus=bus))` | WIRED | Line 265; guarded by `settings.run_worker`. |
| queue.py::pull_next | atomic claim | `UPDATE jobs SET status='starting' WHERE id=:id AND status='queued'` + rowcount check | WIRED | Fix 6 — only rowcount==1 proceeds (queue.py:109-117). |
| queue.py::run_worker | hybrid wakeup | `asyncio.wait_for(_work_signal.wait(), timeout=2.0)` | WIRED | Fix 1 (queue.py:160). |
| queue.py::cancel (running) | orchestrator.py::_running | `from app.jobs.orchestrator import _running; _running[job_id].set()` | WIRED (at queue level) | queue.py:228-232. BUT NOT wired to any API route — see next row. |
| routes_jobs.py::post_cancel | queue.py::cancel | should call `queue.cancel(job_id, session, settings)` | NOT WIRED | post_cancel (routes_jobs.py:131-155) calls `cleanup.cancel_job` directly. CRITICAL: cooperative cancel unreachable from API. |
| routes_jobs.py::post_job | idempotency.py::resolve_or_create | `await resolve_or_create(request, session, settings, ...)` | WIRED | routes_jobs.py:76; 201/200/422 per-response. |
| routes_ws.py | progress.py::EventBus via app.state.bus | `bus.subscribe(job_id)` + relay loop | WIRED | routes_ws.py:191. WR-01: subscribe AFTER snapshot send (race window). |
| routes_ws.py | job row + manifest + progress.json | snapshot on connect | WIRED | routes_ws.py:148-188; Fix 9 `_read_progress_snapshot` reads percent/eta. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| orchestrator.py progress.json write | `snapshot` dict (chunks_done, chunks_total, percent, eta_s, updated_at) | ChunkProgress from chunker -> `_on_progress` -> `_persist_progress` -> `atomic_write_json(job_dir/progress.json, ...)` | Yes — driven by real chunk callbacks | FLOWING |
| routes_ws.py snapshot | `snapshot` dict (stage, percent, eta, status) | `get_job` (DB row) + `read_manifest` + `_read_progress_snapshot(progress.json)` | Yes — reads the file orchestrator wrote | FLOWING |
| idempotency.py resolve_or_create | `(response, status_code)` | `validate_idempotency_key` -> `INSERT INTO idempotency_keys` -> `create_job_fn(job_id=pending)` -> return (response, 201) OR IntegrityError catch -> SELECT existing -> `get_job` -> return (existing, 200) | Yes — DB-backed reservation | FLOWING |
| queue.py run_worker | `job_id` from `pull_next` | `SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1` -> conditional `UPDATE ... SET status='starting' WHERE id=:id AND status='queued'` | Yes — DB queue | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase 4 test suite collects | `python -m pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_cancel.py tests/test_ws.py tests/test_idempotency.py --co -q` | 38 tests collected | PASS |
| Phase 4 tests pass | `python -m pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_cancel.py tests/test_ws.py tests/test_idempotency.py -x -q` | 38 passed in 4.97s | PASS |
| JobCancelled lives in errors.py | `grep -n "class JobCancelled" app/jobs/errors.py` | line 20 | PASS |
| chunker imports JobCancelled horizontally | `grep "from app.jobs.orchestrator import JobCancelled" app/models/stt/chunker.py` | no match | PASS (Fix 5 preserved) |
| No raw UPDATE jobs in orchestrator | `grep -c "UPDATE jobs" app/jobs/orchestrator.py` | 0 | PASS |
| progress.json in _STAGE_FILE_NAMES | `grep "progress.json" app/storage/fs.py` | line 56 | PASS |
| idempotency_key column name | `grep "idempotency_key TEXT PRIMARY KEY" migrations/0008_idempotency_keys.sql` | matches | PASS |
| queue.cancel NOT imported into routes_jobs | `grep "from app.jobs.queue import cancel\|queue.cancel" app/api/routes_jobs.py` | no match | FAIL (WR-04 — cooperative cancel not wired to API) |
| `starting` excluded from boot sweep | `grep "status IN" app/jobs/interrupt.py` | `('ingesting','transcribing')` only | FAIL (CR-01) |
| `starting` excluded from watchdog | `grep "status IN" app/jobs/queue.py` | `('ingesting','transcribing')` only | FAIL (CR-01) |
| run_job has no done-advancement when both skip flags True | inspection of orchestrator.py:211-282 | update_stage("done") only at line 281 inside `if not skip_transcribed:` | FAIL (CR-03) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared by the plans. Step 7c: SKIPPED (no probes).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| JOB-02 | 04-01 | Jobs run in the background — user can navigate away and return to status | SATISFIED | run_job drives stages asynchronously; worker task runs in lifespan; status persists in DB. |
| JOB-04 | 04-02 | Job queue state persists across app restarts | BLOCKED | Queued re-join works, but CR-01 (stuck `starting`) and CR-02 (completed transcript orphaned) break restart persistence for in-flight crash windows. |
| JOB-05 | 04-02 | User can cancel a queued or running job | BLOCKED | `queue.cancel` is implemented and tested but NOT wired to the API. The API `POST /jobs/{id}/cancel` calls destructive `cleanup.cancel_job` for running jobs (WR-04). Queued cancel works via API; running cancel is non-cooperative. |
| JOB-06 | 04-03 | User sees per-job progress (current stage, percent, ETA) in real time | SATISFIED | WS endpoint broadcasts snapshot + live events; progress.json + EventBus relay; ETA hidden until chunks_done >= 2 (D-09). (REQUIREMENTS.md marks JOB-06 Pending — that flag is stale; the implementation is in place.) |

No orphaned requirements — all four IDs (JOB-02, JOB-04, JOB-05, JOB-06) appear in plan frontmatter and are mapped to truths.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| app/jobs/orchestrator.py | 156 | `datetime.now().isoformat()` (naive local time) | Warning (WR-03) | `progress.json` `updated_at` not comparable to other UTC timestamps in the app (`utcnow_iso()` is the convention). |
| app/api/idempotency.py | 141 | `import uuid` (unused) | Info (IN-01) | Dead code. |
| app/api/idempotency.py | 172 | `except (SAIntegrityError, Exception) as exc:` (redundant) | Info (IN-02) | SAIntegrityError is a subclass of Exception; dual listing suggests uncertainty. |
| app/jobs/interrupt.py | 43-47 | `session_factory` parameter unused | Info (IN-03) | Dead parameter. |
| app/models/settings.py | 95-101 | `ws_subscriber_cap`/`idempotency_ttl_hours` lack range validators | Info (IN-04) | Negative values cause edge-case breakage via settings file edit. |
| app/api/idempotency.py | 193-204 | Race edge: row deleted between collision and SELECT creates a new job (201) | Info (IN-05) | Idempotency contract violated in an impossible-in-practice race. |

No TBD/FIXME/XXX debt markers found in modified files. Step 7 debt-marker gate: PASS.

### Human Verification Required

None. All gaps are observable programmatically in the code; the failures do not require human UI/UX testing to confirm.

### Gaps Summary

Three BLOCKER-class gaps block the phase goal. They cluster around the "restart persistence" and "state machine with file-as-truth" pillars of the phase goal:

1. **CR-03 (state machine dead-end):** `run_job` cannot advance a job to `done` on resume when both `skip_ingested` and `skip_transcribed` are True but `manifest.current_stage != "done"`. `update_stage("done")` is only inside the `if not skip_transcribed:` block. A crash between `update_stage("transcribed")` and `update_stage("done")` leaves the job stuck in `transcribing` forever. The state machine's file-as-truth invariant is undermined: the file says transcribed is complete, but the orchestrator never records the derived `done` transition. Fix: add an explicit `resume_stage == "done"` branch that calls `update_stage("done")` and publishes the done event.

2. **CR-01 + CR-02 (restart persistence holes):** `mark_interrupted_failed` and `run_watchdog` SELECT only `status IN ('ingesting','transcribing')`, excluding the transient `starting` status set by `pull_next`'s atomic claim. A crash during that window leaves the job permanently unrecoverable (pull_next skips it, watchdog never marks it stale, cancel cannot flip it after restart). Additionally, the sweep marks jobs failed based on status alone without consulting `infer_resume_point` — a job with a complete `transcript.json` on disk but DB status `transcribing` gets marked failed, orphaning the user's completed transcription. Fix: include `'starting'` in both SELECT filters, and consult `infer_resume_point` per swept job (if `resume_point is None or "done"`, advance to done instead of failing).

3. **WR-04 (cooperative cancel not API-wired):** `queue.cancel` (implemented, tested, D-06-compliant) is not wired to any API route. `POST /jobs/{id}/cancel` calls destructive `cleanup.cancel_job` directly, rmtreeing the folder out from under a running orchestrator. The user-facing cancel for a running job is non-cooperative and non-deterministic. Fix: wire `post_cancel` to call `queue.cancel(job_id, session, settings)` and map the returned dict to a JobResponse.

SC-3 (WS broadcast) and SC-5 (idempotent submit) are fully verified with all artifacts substantive and wired. The WS endpoint has two edge-case warnings (WR-01 snapshot-before-subscribe race; WR-02 registry.add outside try/finally) that do not block the phase goal but should be addressed in a follow-up.

The full Phase 4 test suite (38 tests) passes — but the tests do not exercise the three crash-window scenarios above, so the green suite does not contradict the gaps. The gaps are confirmed by direct inspection of `app/jobs/orchestrator.py`, `app/jobs/interrupt.py`, `app/jobs/queue.py`, and `app/api/routes_jobs.py`, and align with the 04-REVIEW.md CR-01/CR-02/CR-03 + WR-04 findings.

Recommend `/gsd-plan-phase --gaps` to close CR-01, CR-02, CR-03, and WR-04 before proceeding to Phase 5.

---

_Verified: 2026-06-23T01:00:00Z_
_Verifier: Claude (gsd-verifier)_