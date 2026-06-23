---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - app/jobs/orchestrator.py
  - app/jobs/interrupt.py
  - app/jobs/queue.py
  - app/api/routes_jobs.py
findings:
  critical: 0
  warning: 2
  info: 6
  total: 8
warning_resolved: 2
status: resolved
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Re-reviewed the four gap-closure files for phase 04: the CR-03 resume dead-end fix
in `orchestrator.py` (the new `if resume_stage == "done"` advance branch), the
CR-01/CR-02 widened SELECT filters + `infer_resume_point` advance branch in
`interrupt.py` and `queue.py`, and the WR-04 post_cancel rewiring to
`queue.cancel` in `routes_jobs.py`. The core logic is sound: the CR-03 advance
correctly handles the crash window between `update_stage("transcribed")` and
`update_stage("done")`, the CR-02 sweep correctly advances file-complete jobs
instead of failing them, and the cancel rewiring delegates to the cooperative
path as designed.

Two real correctness gaps survived the closure:

1. **WR-01** — `cancel_job`'s DB UPDATE has no status guard. The queued-cancel
   path in `queue.cancel` races with the worker's atomic claim: if
   `pull_next` flips a queued row to `'starting'` between the cancel route's
   SELECT and `cancel_job`'s unconditional UPDATE, the cancel silently flips a
   running job to `'cancelled'`, which the orchestrator then overwrites on its
   next `update_stage` call. The user's cancel is lost and the job runs to
   completion. The docstring at `queue.py:185-188` claims the path is safe
   because the atomic claim "prevents double-run" — true, but it does NOT
   prevent the cancel-loss direction of the race.
2. **WR-02** — the CR-03 advance branch in `orchestrator.py` (lines 284-297)
   never checks `cancel_flag.is_set()`. If a user cancels a job that is in the
   CR-03 resume window (transcript.json on disk, `current_stage='transcribed'`,
   DB status still `'transcribing'`), the orchestrator advances the job to
   `'done'` anyway, dropping the cancel intent on the floor.

The remaining findings are quality / robustness nits (redundant exception
tuple, redundant final commit, wasted re-query in the cancel route, narrow
manifest-delete race in the sweep, `_running` overwrite on double-run).

## Critical Issues

_None._ The gap-closure logic is correct on the happy paths and the documented
crash windows. The two race conditions below are real but narrow-window and
silent-failure rather than crash/data-loss — classified as WARNING.

## Warnings

### WR-01: Queued-cancel race silently loses the cancel (`cancel_job` has no status guard) — RESOLVED

**File:** `app/jobs/queue.py:215-222` (queued branch) and `app/jobs/cleanup.py:57-63` (`cancel_job` UPDATE)
**Status:** resolved (fix(04-review): WR-01 guard queued-cancel against claim race — commit 925fe17; regression test `test_cancel_queued_race_routes_to_active` GREEN)
**Issue:** The cancel route's queued branch flow is:

1. `queue.cancel` SELECTs the row, sees `status='queued'`, enters the queued branch.
2. Calls `cancel_job(session, settings, job_id)`, which runs
   `UPDATE jobs SET status='cancelled' WHERE id = :id` — **no status guard**.
3. `cancel_job` commits, then rmtree's the folder.

The single worker's `pull_next` does a conditional
`UPDATE jobs SET status='starting' WHERE id = :id AND status='queued'` and
commits. If the worker's claim commits **between** step 1 and step 2 above,
`cancel_job`'s unconditional UPDATE flips the now-`'starting'` row to
`'cancelled'` out from under the running worker. The orchestrator then runs
`update_stage("ingested")` which overwrites `status` to `'ingesting'`, then
`'transcribing'`, then `'done'`. The user's cancel is silently lost and the
job runs to completion (its folder was rmtree'd by `cancel_job`, so the
orchestrator may also fail mid-run when it cannot find `transcript.json`'s
parent — depending on timing the job can end `'failed'` with a misleading
error, or `'done'` if the folder was re-created by `atomic_write_json`'s
tmp/replace path).

The docstring at `queue.py:185-188` defends the path by arguing the atomic
claim prevents "double-run a cancelled queued job" — which is true — but it
does not address the opposite direction (cancel arriving after the claim).

**Fix:** Make `cancel_job`'s UPDATE conditional on a non-terminal status, so a
row that has already been claimed (`'starting'`) or progressed is NOT
flipped by the queued-cancel path; the active-cancel path (the `_running`
flag branch) handles those:

```python
# app/jobs/cleanup.py -- cancel_job
result = await session.execute(
    text(
        "UPDATE jobs SET status = 'cancelled', updated_at = :now "
        "WHERE id = :id AND status NOT IN ('done','failed','cancelled')"
    ),
    {"now": utcnow_iso(), "id": job_id},
)
```

This still lets the queued-cancel succeed (row is `'queued'`), still lets the
`JobCancelled` path in the orchestrator flip a `'starting'`/`'ingesting'`/
`'transcribing'` row (those are not terminal), but prevents the queued branch
from racing a row the worker has already claimed if the cancel route then
falls back to the active-cancel path via a re-SELECT. Alternatively, the
queued branch in `queue.cancel` should re-SELECT-then-UPDATE with
`WHERE status='queued'` and treat `rowcount == 0` as "lost the race, re-SELECT
and route to the active branch".

### WR-02: CR-03 resume-advance branch ignores `cancel_flag` — RESOLVED

**File:** `app/jobs/orchestrator.py:284-297`
**Status:** resolved (fix(04-review): WR-02 check cancel_flag before CR-03 resume advance — commit e67197d; regression test `test_resume_advance_respects_cancel_flag` GREEN)
**Issue:** The CR-03 advance branch runs `update_stage(..., "done")` and
publishes `{"type": "done"}` unconditionally. It never checks
`cancel_flag.is_set()`. Consider the resume window the branch was added to
fix: transcript.json is on disk, `manifest.current_stage == "transcribed"`,
DB `status == "transcribing"` (the crash happened between the two
`update_stage` calls in the happy path). If the user hits
`POST /jobs/{id}/cancel` while `run_job` is re-driving this job on the next
worker tick, `queue.cancel` sees `status='transcribing'`, looks up
`_running[job_id]`, and sets the flag. The orchestrator's chunker is not
running (the transcribe block is skipped because `skip_transcribed` is True),
so no `JobCancelled` is ever raised. Control reaches line 284, the branch
advances the job to `'done'`, and the cancel intent is dropped on the floor.
The user receives a 200 from the cancel route (still `'transcribing'` at that
instant) but the next poll shows `'done'`.

This is a correctness violation of the cooperative-cancel contract (D-06):
a cancel against an active (`'transcribing'`) job should result in
`'cancelled'`, not `'done'`. The fact that the underlying transcription is
already file-complete is an implementation detail the user did not opt into.

**Fix:** Check the cancel flag before the CR-03 advance and route to the
existing `JobCancelled` path if it is set:

```python
if resume_stage == "done":
    if cancel_flag.is_set():
        # User cancelled during the resume window. Treat the
        # file-complete transcription as cancelled per D-06: raise
        # JobCancelled so the existing except-handler runs cancel_job
        # (DB + rmtree) and publishes {"type": "cancelled"}.
        raise JobCancelled("cancelled during resume-advance")
    async with session_factory() as session:
        await update_stage(settings, session, job_id, "done")
    _publish({"type": "done"})
    _log.info("run_job %s: advanced to done via resume", job_id)
```

(`JobCancelled` is already imported at the top of the module from
`app.jobs.errors`.)

## Info

### IN-01: Redundant exception tuple in finally-block await

**File:** `app/jobs/orchestrator.py:322`
**Issue:** `except (asyncio.TimeoutError, JobCancelled, Exception)` is
equivalent to `except Exception` because `Exception` subsumes both
`asyncio.TimeoutError` and `JobCancelled`. The named exceptions are dead
branch targets that mislead readers into thinking the handler distinguishes
them.
**Fix:** `except Exception:  # noqa: BLE001 -- cancel/timeout/crash all mean "thread is done or past our control"`

### IN-02: `post_cancel` discards `queue_cancel`'s returned status and re-queries

**File:** `app/api/routes_jobs.py:164-170`
**Issue:** `queue_cancel` already performs up to two SELECTs and returns
`{"status", "id"}`. The route then ignores that dict (apart from the empty
check) and calls `get_job(session, canonical_id)` to build the response. The
extra query is wasted work, and worse, for the running-cancel path the
returned `JobResponse` will still show `status='transcribing'` (the
orchestrator has not yet flipped it) — the route acknowledges this in its
docstring but a client polling immediately after a "successful" cancel will
see the pre-cancel status, which is confusing UX. Consider building the
`JobResponse` directly from `queue_cancel`'s returned dict, or documenting
the eventual-consistency window in the response body.
**Fix:** Either drop the second `get_job` call and construct `JobResponse`
from the dict, or add a `cancelled_at` / `cancel_pending` flag to the
response so clients know to poll.

### IN-03: `_persist_progress` write may race with `cancel_job`'s rmtree

**File:** `app/jobs/orchestrator.py:165-173, 158-163`
**Issue:** `_on_progress` schedules `_persist_progress` via
`loop.create_task` from the worker thread. If the user cancels mid-transcribe,
the orchestrator's `JobCancelled` path calls `cancel_job` which rmtree's the
job directory. A `_persist_progress` task scheduled just before the rmtree
will run after the directory is gone and fail in `atomic_write_json`. The
exception is caught and logged at WARNING (`progress.json write failed for
%s`), so this is log noise rather than a crash, but it can surface confusing
warnings during normal cancel flows.
**Fix:** No code change required; consider lowering the log level to DEBUG or
gating the write on `not cancel_flag.is_set()`.

### IN-04: Redundant final `session.commit()` in `mark_interrupted_failed`

**File:** `app/jobs/interrupt.py:158-159`
**Issue:** Both `update_stage` (manifest.py:248) and `mark_failed`
(cleanup.py:101) commit internally per call. The `if swept: await
session.commit()` at the end of the sweep is therefore always a no-op. Not a
bug, but it implies a transactional boundary that does not actually exist —
the sweep is per-iteration committed, so a mid-sweep crash leaves partial
state. That partial state is idempotent (next boot re-sweeps the un-swept
rows), so the behavior is fine; the redundant commit just misleads readers
into thinking the sweep is atomic.
**Fix:** Remove the redundant commit, or add a comment noting the sweep is
intentionally per-iteration committed and re-runnable.

### IN-05: `_running[job_id]` overwrite orphans prior cancel flag

**File:** `app/jobs/orchestrator.py:119-120`
**Issue:** `run_job` unconditionally assigns
`_running[job_id] = cancel_flag` at entry. If `run_job` is somehow invoked
twice for the same `job_id` (programmer error, double-enqueue, or a manual
test harness driving the worker while the lifespan worker is also running),
the second assignment orphans the first flag — a cancel routed during the
overlap would set only the second flag, leaving the first run uncancellable.
D-10 (strict serial, single worker) prevents this in production, but the
code offers no defense-in-depth.
**Fix:** Assert `_running.get(job_id) is None` at entry (or log a warning if
a prior entry exists) to make double-invocation a loud failure rather than a
silent orphan.

### IN-06: `mark_interrupted_failed` advance path does not catch `FileNotFoundError` from `update_stage`

**File:** `app/jobs/interrupt.py:127-144`
**Issue:** The advance branch calls `update_stage(settings, session, job_id,
"done")`, which internally calls `read_manifest` and raises `FileNotFoundError`
if the manifest was deleted between the sweep's own `read_manifest` at line
113 and the `update_stage` call at line 136 (narrow window — another process
or a concurrent cancel's rmtree). The exception would propagate up from the
sweep, aborting it with partial state (some jobs advanced, some not, the
remainder never reached). The function already defends `read_manifest` with
a `FileNotFoundError` try/except for the initial read but not for the
`update_stage` re-read.
**Fix:** Wrap the advance `update_stage` in a try/except `FileNotFoundError`
that falls through to the `mark_failed` + failed-manifest write path (the
job's folder is gone anyway).

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_