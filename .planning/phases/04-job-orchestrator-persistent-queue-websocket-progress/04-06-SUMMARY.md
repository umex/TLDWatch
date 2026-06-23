---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
plan: 06
subsystem: api
tags: [cancel, api, cooperative-cancel, gap-closure, WR-04, fastapi, httpx]

# Dependency graph
requires:
  - phase: 04-job-orchestrator-persistent-queue-websocket-progress (plan 02)
    provides: cooperative queue.cancel (queued / running / terminal three-state behavior, D-06-compliant)
  - phase: 04-job-orchestrator-persistent-queue-websocket-progress (plans 04 + 05)
    provides: CR-01/CR-02/CR-03 gap-closure fixes on the main tree (clean regression baseline)
provides:
  - POST /jobs/{id}/cancel wired to queue.cancel (cooperative cancel) -- WR-04 closed
  - Three API integration tests covering running/queued/terminal cancel via the API
affects: [phase-05, job-orchestrator, cancel-flow, JOB-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "API route maps a cooperative-cancel dict result to a JobResponse; {} -> 404, terminal-no-op -> 200 with unchanged row (D-06 idempotent), running -> 200 with current row (orchestrator flips asynchronously)"

key-files:
  created: []
  modified:
    - app/api/routes_jobs.py
    - tests/test_cancel.py

key-decisions:
  - "post_cancel calls queue.cancel (alias queue_cancel) instead of cleanup.cancel_job directly -- the cooperative path. The route fetches the row via get_job after queue.cancel returns {status, id}; the dict is only used for the {} -> 404 check (empty dict is falsy)."
  - "cancel_job import removed from routes_jobs.py (mark_stale kept -- still used by post_stale_check); queue.cancel owns the queued-cancel path internally via its own cancel_job import."
  - "validate_job_id -> 400 path unchanged; response_model=JobResponse unchanged; no new status codes -- terminal-no-op and running both return 200 with the row's current status."

patterns-established:
  - "Cooperative cancel at the API boundary: the route never rmtrees out from under a running orchestrator; it sets the _running flag via queue.cancel and returns the current row, letting the orchestrator's JobCancelled path do cancel_job + rmtree."

requirements-completed: [JOB-05]

# Metrics
duration: 8min
completed: 2026-06-23
---

# Phase 04 Plan 06: WR-04 Cooperative Cancel API Wiring Summary

**POST /jobs/{id}/cancel rewired from destructive cleanup.cancel_job to cooperative queue.cancel -- running jobs set the _running flag (orchestrator's JobCancelled path does the rmtree), terminal jobs are a 200 no-op (D-06 idempotent), missing jobs return 404.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-23
- **Completed:** 2026-06-23
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- WR-04 closed: the user-facing cancel API now delivers the D-06 cooperative-cancel contract for running jobs (no destructive out-from-under rmtree).
- Three API integration tests added (running / queued / terminal via POST /jobs/{id}/cancel) covering the full WR-04 surface, including idempotent terminal cancel and the orchestrator's JobCancelled path completion.
- Full phase suite green: 44 tests (41 prior + 3 new), no regression.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add API integration tests for WR-04 (running/queued/terminal cancel via POST /jobs/{id}/cancel)** - `2b007fe` (test, TDD RED)
2. **Task 2: Fix WR-04 -- rewire post_cancel to call queue.cancel (cooperative path) with {} -> 404 and terminal-no-op handling** - `d51b57f` (fix, TDD GREEN)

## Files Created/Modified
- `app/api/routes_jobs.py` - post_cancel rewired to call `queue.cancel(canonical_id, session, settings)` (aliased `queue_cancel`); `cancel_job` import removed, `mark_stale` kept; `{}` -> 404; terminal-no-op returns 200 with the unchanged row; running returns 200 with the current row (orchestrator flips asynchronously); validate_job_id -> 400 path unchanged.
- `tests/test_cancel.py` - three new API integration tests appended (`test_cancel_queued_via_api`, `test_cancel_running_via_api`, `test_cancel_terminal_via_api_idempotent`) reusing the existing `_settings` / `_session_factory` / `_make_local_job` / `_set_status` helpers and the `client` + `tmp_data_dir` fixtures from conftest.py.

## Decisions Made
- Aliased the import as `queue_cancel` to avoid shadowing the route function name `post_cancel` and the cleanup `cancel_job` symbol.
- The route fetches the row via `get_job` after `queue.cancel` returns (rather than returning the dict directly) so the `response_model=JobResponse` is satisfied; the dict is only used for the `{}` -> 404 check (`if not result:` -- empty dict is falsy).
- The queued-cancel API test passes under both the old and new implementations (cancel_job for a queued job does the same DB+rmtree either way); the running and terminal tests are the WR-04 discriminators (flag.is_set() and 200-not-404 for terminal).

## Deviations from Plan

None - plan executed exactly as written. The plan anticipated the queued test passing under both implementations; the RED gate was carried by the running + terminal tests (the `-x` suite failed RED before Task 2, GREEN after).

## TDD Gate Compliance

- RED gate: `test(04-06): ...` commit `2b007fe` -- the new test suite failed against the unfixed `post_cancel` (running: `flag.is_set()` False because `cancel_job` does not set the flag; terminal: would map `cancel_job`'s `False` return to 404 instead of 200).
- GREEN gate: `fix(04-06): ...` commit `d51b57f` -- the same suite passes after the rewire; full 44-test phase suite green.
- REFACTOR gate: not needed -- the rewire is a minimal 1-function change.

## Verification

- `python -m pytest tests/test_cancel.py::test_cancel_queued_via_api tests/test_cancel.py::test_cancel_running_via_api tests/test_cancel.py::test_cancel_terminal_via_api_idempotent -x -q` -> 3 passed.
- `python -m pytest tests/test_cancel.py tests/test_orchestrator.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py -x -q` -> 44 passed.
- `grep -c "from app.jobs.queue import cancel" app/api/routes_jobs.py` -> 1.
- `grep -c "from app.jobs.cleanup import cancel_job" app/api/routes_jobs.py` -> 0.
- `grep -c "queue_cancel" app/api/routes_jobs.py` -> 2 (import + usage).
- `grep -v '^#' app/api/routes_jobs.py | grep -c "await cancel_job"` -> 0.
- `validate_job_id` still present in `post_cancel` (400 path preserved).

## Self-Check: PASSED

- FOUND: app/api/routes_jobs.py
- FOUND: tests/test_cancel.py
- FOUND: commit 2b007fe (test)
- FOUND: commit d51b57f (fix)

## Next Phase Readiness
- WR-04 (the last BLOCKER from 04-VERIFICATION.md) is closed. CR-01/CR-02/CR-03 were closed by plans 04-04 + 04-05. Phase 04 is ready for re-verification (`/gsd-verify-phase 4`).
- JOB-05 (cancel queued or running job via the API) is now fully satisfied end-to-end.
- No blockers for Phase 05.

---
*Phase: 04-job-orchestrator-persistent-queue-websocket-progress*
*Completed: 2026-06-23*