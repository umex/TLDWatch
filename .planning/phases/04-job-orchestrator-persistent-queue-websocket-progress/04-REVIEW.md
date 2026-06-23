---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - app/api/idempotency.py
  - app/api/routes_jobs.py
  - app/api/routes_ws.py
  - app/jobs/errors.py
  - app/jobs/interrupt.py
  - app/jobs/orchestrator.py
  - app/jobs/progress.py
  - app/jobs/queue.py
  - app/jobs/resume.py
  - app/jobs/service.py
  - app/main.py
  - app/models/job.py
  - app/models/settings.py
  - app/models/stt/adapter.py
  - app/models/stt/chunker.py
  - app/models/stt/protocol.py
  - app/storage/fs.py
  - migrations/0008_idempotency_keys.sql
findings:
  critical: 3
  warning: 4
  info: 5
  total: 12
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 04 delivers the job orchestrator state machine, persistent SQLite queue, boot sweep, cooperative cancel, watchdog, WebSocket progress endpoint, and idempotent job submission. The architecture is generally sound and the cross-AI review concerns (Fix 1-9) were largely addressed: `functools.partial` for executor kwargs, `threading.Event` for cross-loop cancel, `progress.json` in `_STAGE_FILE_NAMES` for heartbeat, horizontal `JobCancelled` import, atomic `pull_next` claim, hybrid Event+poll wakeup, key-first idempotency reservation, `idempotency_key` column name, and `app.state` accessors.

However, three BLOCKER-class correctness gaps remain in the restart-resume lifecycle. The boot sweep (`mark_interrupted_failed`) and watchdog select only `status IN ('ingesting','transcribing')` and never check whether the job's stages are actually complete -- a job that crashed after `update_stage("transcribed")` but before `update_stage("done")` has a complete `transcript.json` on disk yet gets marked `failed` on the next boot. Jobs that crash during the transient `starting` status (between `pull_next` and the first `update_stage`) are never swept at all and become permanently stuck with no recovery path. And `run_job` itself cannot advance a job to `done` on resume -- if both `skip_ingested` and `skip_transcribed` are True but `current_stage != "done"`, the orchestrator returns without calling `update_stage("done")`, leaving the job in `transcribing` status indefinitely.

The WebSocket endpoint has a snapshot-to-subscribe race (terminal events published between snapshot read and `bus.subscribe` are lost, leaving clients stuck) and a subscriber-registry leak (the snapshot send is outside the `try/finally` that cleans up the registry). The `progress.json` `updated_at` field uses naive local time instead of UTC, inconsistent with the rest of the app. The new cooperative `queue.cancel` is implemented and tested but not wired to any API route -- the existing cancel route rmtrees the folder out from under a running orchestrator instead of setting the cancel flag.

## Critical Issues

### CR-01: Jobs stuck in "starting" status are never recovered

**File:** `app/jobs/interrupt.py:78-82`, `app/jobs/queue.py:295-300`
**Issue:** Both `mark_interrupted_failed` (boot sweep) and `run_watchdog` select `status IN ('ingesting','transcribing')` only. The transient `starting` status (set by `pull_next`'s atomic claim, between `UPDATE ... status='starting'` and the first `update_stage("ingested")`) is NOT included. If the process is killed during that window (read_manifest + infer_resume_point + source-file check), the job remains `starting` in the DB forever. The `cancel()` function in `queue.py` also cannot recover it after a restart: the `_running` registry is empty (module reloaded), so `flag = _running.get(job_id)` returns None, the re-SELECT shows `starting` (not terminal), and the function logs a warning and returns without cancelling. The job is irrecoverable without manual DB intervention.

The window is narrow (the ingest pre-check is fast), but the consequence is permanent: a stuck job that blocks the FIFO (it is not `queued` so `pull_next` skips it, but it is not terminal so the user cannot re-submit with the same id, and cancel cannot flip it).

**Fix:** Include `'starting'` in the sweep and watchdog SELECT statements, OR have `run_job` call `update_stage("ingested")` (or an equivalent that sets status to `ingesting`) as the very first DB write before any other work, so the `starting` window is zero-width. The simplest fix is to add `'starting'` to the sweeps:

```python
# app/jobs/interrupt.py
"SELECT id FROM jobs WHERE status IN ('starting','ingesting','transcribing')"

# app/jobs/queue.py run_watchdog
"SELECT id FROM jobs WHERE status IN ('starting','ingesting','transcribing')"
```

### CR-02: Completed transcript marked failed on restart

**File:** `app/jobs/interrupt.py:78-82`
**Issue:** `mark_interrupted_failed` selects jobs by status (`ingesting`/`transcribing`) without checking whether their stages are actually complete. If the process crashes after `update_stage("transcribed")` (DB status becomes `transcribing` via `stage_to_status`) but before `update_stage("done")`, the `transcript.json` is on disk and `manifest.current_stage` is `transcribed`. On restart, the sweep sees status=`transcribing` and marks the job `failed` -- even though `infer_resume_point` would return `done` (transcribed is complete, only the derived `done` transition remains). The user's completed transcription is orphaned: the folder is kept (mark_failed does not rmtree) but the job is `failed` and inaccessible through the API. The user must re-submit from scratch.

The window is narrow (two sequential SQL commits), but the consequence is data loss from the user's perspective.

**Fix:** Before marking a job failed, check whether its stages are actually complete via `infer_resume_point`. If the resume point is `done` (or `None` -- all complete), advance the job to `done` instead of failing it:

```python
for job_id in ids:
    try:
        manifest = await read_manifest(settings, job_id)
    except FileNotFoundError:
        await mark_failed(session, job_id, _INTERRUPTED_ERROR)
        swept += 1
        continue
    resume_point = infer_resume_point(settings, job_id, manifest)
    if resume_point is None or resume_point == "done":
        # Stages are complete -- advance to done, do not fail.
        async with session_factory() as s:
            await update_stage(settings, s, job_id, "done")
        continue
    await mark_failed(session, job_id, _INTERRUPTED_ERROR)
    # ... manifest write ...
```

### CR-03: run_job cannot advance to "done" on resume

**File:** `app/jobs/orchestrator.py:211-282`
**Issue:** `run_job` computes `skip_ingested` and `skip_transcribed` and only calls `update_stage("done")` inside the `if not skip_transcribed:` block (line 280-281). If both stages are already complete (`skip_ingested=True`, `skip_transcribed=True`) but `manifest.current_stage != "done"` (e.g., a crash between `update_stage("transcribed")` and `update_stage("done")` that was NOT swept, or a transient DB error on the `done` commit), the orchestrator falls through both `if` blocks and returns without calling `update_stage("done")`. The job remains in `transcribing` status forever. `pull_next` will not re-claim it (it is not `queued`), and the watchdog sees it as active but not stale (if `progress.json` mtime is fresh).

This means even if CR-02 is fixed (sweep does not mark the job failed), the worker cannot recover the job -- it skips both stages and returns without advancing.

**Fix:** After the two `if not skip_*` blocks, check whether the resume point was `done` and advance:

```python
# After the transcribing stage block, before the except clauses:
if skip_ingested and skip_transcribed and manifest.current_stage != "done":
    async with session_factory() as session:
        await update_stage(settings, session, job_id, "done")
    _publish({"type": "done"})
```

Or restructure to handle `resume_stage == "done"` explicitly at the top of the function.

## Warnings

### WR-01: WebSocket snapshot sent before EventBus subscribe -- terminal events can be missed

**File:** `app/api/routes_ws.py:179-191`
**Issue:** The WS handler sends the state snapshot (line 188) BEFORE subscribing to the EventBus (line 191). If a `done`/`failed`/`cancelled` event is published between the snapshot read (`get_job` at line 149) and `bus.subscribe(job_id)` (line 191), the client misses it. The client receives a snapshot showing an active state (e.g., `transcribing`) but no terminal event ever arrives, so it waits indefinitely. The only recovery is a manual reconnect.

This is the classic subscribe-then-read vs read-then-subscribe race. The correct pattern is to subscribe FIRST, then read the snapshot, then relay queued events (the client may see a stale event followed by the snapshot's state, but it will always receive the terminal event).

**Fix:** Subscribe to the bus before reading the snapshot:

```python
queue = bus.subscribe(job_id)
try:
    # read snapshot (job row + manifest + progress.json)
    ...
    await websocket.send_json(snapshot)
    # live relay
    while True:
        event = await queue.get()
        await websocket.send_json(event)
except WebSocketDisconnect:
    pass
except Exception:
    _log.info("ws relay ended for %s", job_id, exc_info=True)
finally:
    registry.remove(job_id, websocket)
    bus.unsubscribe(job_id, queue)
```

### WR-02: WebSocket subscriber registry leak if snapshot send fails

**File:** `app/api/routes_ws.py:162-204`
**Issue:** `registry.add(job_id, websocket, cap)` is called at line 162, but the snapshot `send_json` at line 188 is OUTSIDE the `try/finally` block (line 192-204) that calls `registry.remove`. If the snapshot send raises (client disconnected between accept and snapshot, or a transport error), the exception propagates out of the handler without removing the subscriber from the registry. The dead `WebSocket` object remains in the registry's set for that `job_id`. Over time, accumulated dead subscribers can fill the registry up to `ws_subscriber_cap`, after which all new subscribers for that job are rejected with `subscriber_cap` -- a localized DoS.

**Fix:** Move `registry.add` inside the `try` block, or extend the `try/finally` to cover the snapshot send:

```python
if not registry.add(job_id, websocket, settings.ws_subscriber_cap):
    await websocket.send_json({"type": "error", "code": "subscriber_cap"})
    await websocket.close(code=1008)
    return

queue = None
try:
    # snapshot
    ...
    await websocket.send_json(snapshot)
    # live relay
    queue = bus.subscribe(job_id)
    while True:
        event = await queue.get()
        await websocket.send_json(event)
except WebSocketDisconnect:
    pass
except Exception:
    _log.info("ws relay ended for %s", job_id, exc_info=True)
finally:
    registry.remove(job_id, websocket)
    if queue is not None:
        bus.unsubscribe(job_id, queue)
```

### WR-03: progress.json updated_at uses naive local time instead of UTC

**File:** `app/jobs/orchestrator.py:156`
**Issue:** `_persist_progress` writes `"updated_at": datetime.now().isoformat()` which produces a naive local-time timestamp (no timezone suffix). The rest of the app uses `utcnow_iso()` (`datetime.now(timezone.utc).isoformat()`, producing `+00:00`-suffixed UTC). This inconsistency means `progress.json`'s `updated_at` is not comparable to other timestamps in the system (job `created_at`, `updated_at`, manifest `stage_timestamps`) and could confuse consumers that assume all timestamps are UTC ISO 8601.

**Fix:** Use the existing UTC helper:

```python
from app.util.time import utcnow_iso
...
"updated_at": utcnow_iso(),
```

### WR-04: Cooperative cancel (queue.cancel) is not wired to any API route

**File:** `app/api/routes_jobs.py:131-155`, `app/jobs/queue.py:176-263`
**Issue:** The new cooperative `cancel()` function in `queue.py` (which sets the `_running` threading.Event flag for running jobs, letting the chunker exit at the next chunk boundary via `JobCancelled`) is implemented and tested but NOT wired to any API route. The existing `POST /jobs/{id}/cancel` route (`post_cancel`) calls `cleanup.cancel_job` directly, which marks the DB row cancelled and rmtrees the folder. For a RUNNING job, this rmtrees the folder out from under the orchestrator -- the orchestrator's subsequent `atomic_write_json(transcript.json)` fails (directory gone), the exception handler calls `mark_failed` (which may fail or conflict with the already-cancelled row), and the model is unloaded in the finally block. This is destructive and non-cooperative.

The Phase 4 cooperative cancel (setting the flag, letting the orchestrator's `JobCancelled` path do `cancel_job` cleanly) is inaccessible via the API. JOB-04 (cancel requirement) is only partially satisfied: queued cancel works, running cancel is destructive.

**Fix:** Wire `post_cancel` to `queue.cancel` (or add a new route) so the cooperative cancel path is used for active jobs:

```python
@router.post("/{job_id}/cancel", response_model=JobResponse)
async def post_cancel(job_id, session, settings):
    canonical_id = validate_job_id(job_id)  # 400 on invalid
    from app.jobs.queue import cancel
    result = await cancel(canonical_id, session, settings)
    if not result:  # {} -> 404
        raise HTTPException(status_code=404, detail="job not found")
    refreshed = await get_job(session, canonical_id)
    ...
```

## Info

### IN-01: Unused `import uuid` in idempotency.py

**File:** `app/api/idempotency.py:141`
**Issue:** `import uuid` is imported inside `resolve_or_create` but never used. The pending job id comes from `new_job_id()` (imported from `app.jobs.ids` at line 143). Dead code.
**Fix:** Remove `import uuid`.

### IN-02: Redundant SAIntegrityError in except clause

**File:** `app/api/idempotency.py:172`
**Issue:** `except (SAIntegrityError, Exception) as exc:` -- `SAIntegrityError` is a subclass of `Exception`, so listing both is redundant. The subsequent `_is_integrity_error(exc)` check handles the distinction. The dual listing suggests the author was uncertain about the catch scope.
**Fix:** Use `except Exception as exc:` and rely on `_is_integrity_error`.

### IN-03: Unused session_factory parameter in mark_interrupted_failed

**File:** `app/jobs/interrupt.py:43-47`
**Issue:** `mark_interrupted_failed(session, settings, session_factory)` accepts `session_factory` but never uses it -- all DB work uses the `session` argument. The call site in `main.py` passes it, but it is dead.
**Fix:** Remove the parameter, or use it if a per-job session is needed in a future fix (e.g., CR-02's `update_stage` call would need its own session).

### IN-04: No validation on ws_subscriber_cap and idempotency_ttl_hours

**File:** `app/models/settings.py:95-101`
**Issue:** `ws_subscriber_cap: int = 16` and `idempotency_ttl_hours: int = 24` have no validators. A negative `ws_subscriber_cap` (e.g., -1) causes `SubscriberRegistry.add` to reject all subscribers (`len(subs) >= cap` is `0 >= -1` = True). A negative `idempotency_ttl_hours` causes the janitor to delete all rows immediately. A `ws_subscriber_cap` of 0 blocks all WS connections. These are edge cases via settings file edit, but the model is `extra="forbid"` with no range guard.
**Fix:** Add `field_validator` or `Field(ge=1)` / `Field(ge=1)` constraints.

### IN-05: Idempotency contract violated in rare edge case (row deleted between collision and SELECT)

**File:** `app/api/idempotency.py:193-204`
**Issue:** In the race path (IntegrityError on INSERT), if the SELECT for the existing `job_id` returns None (the winning row was deleted between the collision and the SELECT -- e.g., by the janitor or manual DB intervention), the code creates a NEW job with a fresh id and returns 201. This breaks the idempotency contract: a duplicate `Idempotency-Key` request returns a different job (201) instead of the original (200). In practice this is extremely unlikely (the janitor only deletes rows older than `idempotency_ttl_hours`, and the row was just inserted by the winner), but it is a contract violation.
**Fix:** Retry the reservation (DELETE + INSERT) or return 409/503 instead of creating a new job. Alternatively, document that this path is acceptable degradation for an impossible-in-practice race.

---

_Reviewed: 2026-06-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_