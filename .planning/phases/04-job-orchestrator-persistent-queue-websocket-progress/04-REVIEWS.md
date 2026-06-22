---
phase: 04
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-06-22T00:00:00Z
plans_reviewed: [04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md]
reviewer_status:
  gemini: failed (IneligibleTierError — Gemini CLI client deprecated; migrate to Antigravity)
  codex: success
  ollama: success (model: kimi-k2.6:cloud)
---

# Cross-AI Plan Review — Phase 04

## Gemini Review

> **Status: FAILED.** The `gemini` binary is present (v0.46.0) but authentication fails with `IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals`. Google has deprecated the standalone Gemini CLI in favor of the Antigravity suite. No review was produced. Re-run `/gsd-review --agy` after installing the Antigravity CLI, or migrate per https://antigravity.google.

---

## Codex Review

## Plan 04-01 Review

### Summary
Plan 04-01 is directionally strong: it correctly establishes the core orchestration contract, preserves the STT adapter boundary, uses file-as-truth stage transitions, and handles cross-thread progress/cancel mechanics carefully. The main risk is that it tries to implement too much of the worker lifecycle inside `run_job` before the queue/cancel layer exists, and there are several likely contract mismatches around stage naming, `run_in_executor` kwargs, model manager usage, and cancellation ownership.

### Strengths
- Correctly anchors transitions on existing `manifest.update_stage` instead of introducing raw DB state mutation.
- Preserves the model boundary by requiring orchestration through `STTAdapter`, not `faster_whisper` or `ctranslate2`.
- Good threading model: `threading.Event` for sync chunker cancellation and `loop.call_soon_threadsafe` for progress publication.
- EventBus design is simple, bounded, and appropriate for a single-process MVP.
- Explicitly incorporates D-04 local-reference ingest without copying source files.
- Adds focused tests for state-machine behavior and EventBus backpressure.

### Concerns
- **HIGH:** `run_in_executor(None, transcribe_file, ..., progress_cb=..., cancel_flag=...)` as written is invalid because `run_in_executor` does not accept keyword arguments directly. The plan should require `functools.partial`.
- **HIGH:** Stage naming appears inconsistent. The roadmap says `queued → ingesting → transcribing → done`, but existing `update_stage` may expect completion stages like `ingested` / `transcribed`. The plan alternates between publishing `ingesting` and calling `update_stage("ingested")`, then `update_stage("transcribed")` before transcription actually runs. That could mark stage completion too early.
- **HIGH:** `run_job` cancellation path calls `cancel_job`, which rmtrees the job directory. That is acceptable for explicit user cancel, but if `JobCancelled` is also used internally by fake adapters/tests or future worker shutdown, the semantics could accidentally delete data.
- **MEDIUM:** Model manager access is vague: "manager.adapter / loaded STT" is not a stable contract unless such an accessor exists. The plan should name the exact existing method/API.
- **MEDIUM:** `JobCancelled` is defined in `orchestrator.py` but imported by `chunker.py`, creating a lower-level STT module depending on the jobs orchestration layer. That is an awkward dependency direction.
- **MEDIUM:** ETA computation is described inside 04-01 but progress snapshots/persistence are not defined. A reconnecting WS in 04-03 may not be able to report current percent unless progress is stored somewhere.
- **LOW:** Adding `Settings.run_worker` in this plan is useful for tests, but it is not directly part of the state-machine contract and could be more naturally owned by 04-02.

### Suggestions
- Define exact stage semantics: use "running stage" statuses only while work is active, and mark completion only after the output file exists.
- Replace `run_in_executor(..., kwargs...)` with `functools.partial(transcribe_file, ..., progress_cb=..., cancel_flag=...)`.
- Move `JobCancelled` to a neutral module such as `app/jobs/errors.py` or `app/models/stt/cancel.py` to avoid STT importing orchestration.
- Specify the exact model manager API used to obtain the loaded STT adapter, or add a small adapter provider seam.
- Add a persistent or in-memory `ProgressTracker` contract if WS snapshot percent/ETA is expected later.
- Add tests for failure ordering: no `transcript.json` on exception, failed row keeps job folder, done only after transcript write.

### Risk Assessment
**MEDIUM-HIGH.** The architecture is sound, but the stage-transition timing and executor/API details are easy to get wrong and could break the core state machine. These are fixable with tighter contracts before implementation.

## Plan 04-02 Review

### Summary
Plan 04-02 covers the persistent queue, restart handling, cancel behavior, and watchdog with a pragmatic single-worker design that matches the hardware and MVP constraints. It is mostly well-scoped, but the queue design under-specifies atomic job claiming and may race with cancellation or multiple lifespan starts. The plan also conflicts with itself around queued cancellation cleanup and returning rows after directory removal.

### Strengths
- Correctly keeps worker concurrency at one and enforces FIFO ordering.
- Correctly distinguishes queued jobs, which should rejoin after restart, from active jobs, which should be marked failed.
- Lifespan ordering is well thought out: `reconcile_all → interrupted sweep → worker/watchdog`.
- Running cancel delegates to the orchestrator's cooperative cancel flag, avoiding double cleanup.
- Reuses existing `cleanup.py` helpers for cancellation and stale handling.
- Good teardown requirement: cancel worker/watchdog before disposing DB engine.

### Concerns
- **HIGH:** `pull_next` only selects the next queued job. It does not atomically claim the job before running. If two workers are accidentally started, or if tests/lifespan duplicate tasks, the same job can be run twice.
- **HIGH:** `run_worker` waits indefinitely on `_work_signal.wait()` with no poll fallback, despite research recommending hybrid event + polling. Queued jobs present at startup or missed signals could stall.
- **HIGH:** Queued cancel calls `cancel_job`, which rmtrees the job directory, then the plan says "return row." If `cancel_job` deletes or mutates the row/state, the return semantics need to be explicit.
- **MEDIUM:** `enqueue` updates status to `queued` directly. That may be fine, but it risks re-queueing terminal or active jobs unless guarded by status conditions.
- **MEDIUM:** The interrupted sweep marks active DB statuses failed, but does not mention updating the manifest. If manifest remains at an active stage, `reconcile_all` on the next boot may undo or confuse the failed status.
- **MEDIUM:** `run_worker(settings.run_worker=False) -> return immediately` is fine for lifespan, but a manually driven test worker may need a separate function that processes one job regardless of that flag.
- **MEDIUM:** Stale watchdog uses filesystem freshness but queued jobs may appear stale if included. The plan says non-terminal; it should probably exclude `queued` unless stale queued jobs are intentionally failed.
- **LOW:** Module-level `_work_signal` can be problematic if multiple app instances/tests share process state.

### Suggestions
- Add an atomic claim step: `UPDATE jobs SET status='starting'` or similar with `WHERE id=:id AND status='queued'`, then only run if one row changed. If no new status exists, at least claim by transitioning through existing `update_stage` immediately and rechecking.
- Use hybrid wakeup: `await asyncio.wait_for(_work_signal.wait(), timeout=2.0)` and always poll on timeout.
- Clarify cancel return behavior: return the post-cancel `JobResponse` or a normalized row snapshot, even if the job folder is removed.
- Guard `enqueue` so it only affects valid statuses, or document when it is legal to call.
- Ensure `mark_interrupted_failed` updates both DB and manifest, or explicitly documents why DB-only will not be reverted by later reconciliation.
- Exclude `queued` from stale watchdog unless the product wants queued jobs to fail after 10 minutes.

### Risk Assessment
**MEDIUM.** The high-level design is right, but queue correctness depends on atomic claiming and reliable wakeup. Without those, duplicate execution or stuck queued jobs are plausible.

## Plan 04-03 Review

### Summary
Plan 04-03 addresses the remaining user-visible phase goals: WebSocket progress and idempotent submit. It is clear about scope and avoids recomputing ETA or rebuilding the EventBus. The biggest issues are around the idempotency transaction ordering, WebSocket state access, snapshot data availability, and possible mismatch with the no-auth/single-user context.

### Strengths
- Correctly implements per-job WebSocket rather than a global stream.
- Snapshot-on-connect is the right choice for refresh/reconnect behavior.
- Subscriber cap and bounded EventBus queues address the main DoS risks for WS.
- Idempotency key validation is strict and simple.
- Migration is minimal and uses the existing migration style.
- Correctly treats content-hash dedupe as out of scope.

### Concerns
- **HIGH:** Idempotency flow creates the job before inserting the idempotency key. If the key insert fails due to a race, the just-created duplicate job remains unless explicitly cleaned up. Catching `IntegrityError` and returning the existing job does not undo the duplicate.
- **HIGH:** The migration uses table name/column `key`, which can be awkward because `KEY` is SQL-reserved-ish across dialects. SQLite may allow it, but using `idempotency_key` would be safer and clearer.
- **HIGH:** WebSocket access to `session_factory` and `settings` through `app.state` is assumed but not established in prior plans except for `bus`. The plan should explicitly ensure these are stored or use existing app dependency patterns.
- **MEDIUM:** Snapshot requires percent/ETA, but 04-01 does not clearly persist latest progress. Reading only job row/manifest may not provide 50% progress after reconnect.
- **MEDIUM:** The subscriber cap tracks `set[WebSocket]` module-level. This may leak if disconnect exceptions happen before insertion/subscription ordering is carefully handled, and it is hard to test across app instances.
- **MEDIUM:** Returning 422 from a header validation helper requires mapping `ValueError` to FastAPI `HTTPException`. The plan says this but should require the exact exception path.
- **MEDIUM:** Idempotency TTL deletion plus creation should happen transactionally. Otherwise an expired key delete followed by failed create could lose retry protection.
- **LOW:** `test_eta_null_below_threshold` is described as publishing an early event and asserting `eta_s=null`, but if the published event lacks `eta_s`, the relay "as-is" will not add it. The expected schema should be explicit.
- **LOW:** The threat model mentions auth/session reuse, but project context says single-user no-auth. That should be stated consistently.

### Suggestions
- Make idempotent creation atomic: insert/reserve the idempotency key first with a pending job ID in one transaction, or wrap job creation and key insert in a transaction and delete/cancel the duplicate on collision.
- Rename migration column from `key` to `idempotency_key`.
- Add `app.state.settings` and `app.state.session_factory` explicitly in lifespan if not already present.
- Add a lightweight progress snapshot store updated by EventBus/orchestrator, or persist latest progress in job metadata/manifest if reconnect snapshots must show nonzero percent.
- Replace module-level `SUBSCRIBERS` with a small `SubscriberRegistry` class, ideally attached to `app.state`, so tests and app instances are isolated.
- Define response codes precisely: first idempotent create should be `201`, duplicate should be `200`, invalid header should raise `HTTPException(status_code=422)`.
- Add an explicit test that duplicate-race handling does not leave an extra queued job.

### Risk Assessment
**MEDIUM-HIGH.** The WS relay is straightforward, but idempotency can easily create duplicate jobs under race unless transaction boundaries are tightened. Snapshot progress also depends on state that earlier plans do not clearly store.

## Overall Assessment (Codex)

The three-wave structure is sensible and mostly matches the phase goals: 04-01 builds the state-machine spine, 04-02 adds persistent queue/cancel/restart behavior, and 04-03 exposes progress plus idempotent submit. The main architectural risks are not scope creep; they are ordering and atomicity: stage completion must not be recorded before outputs exist, queued jobs must be claimed atomically, and idempotency must not create an orphan duplicate before detecting a key collision.

Overall phase risk: **MEDIUM-HIGH** until those contracts are tightened. With atomic claim/idempotency changes and clearer progress snapshot persistence, the plan becomes a solid **MEDIUM** implementation risk for an MVP.

---

## Ollama Review

**Summary**

The three-wave Phase 4 plan delivers a well-decomposed job orchestration spine: 04-01 builds the state-machine driver and event bus, 04-02 adds persistent queueing and cancel semantics, and 04-03 exposes progress via WebSocket and idempotent submission. The architecture correctly reuses Phase 1–3 primitives (file-as-truth transitions, `update_stage`, cleanup lifecycle) and respects the strict serial-worker constraint forced by single-GPU residency. However, there are material gaps in **long-running stage heartbeat management**, **worker loop resilience**, **concrete adapter contract updates**, and **stage-resume logic** that could cause false stale marking, queue stalls, or runtime breakage when the real STT adapter is invoked.

### Strengths

- **Clean wave decomposition.** Each wave has a single, well-defined responsibility and explicitly declares what it consumes from prior waves, avoiding scope overlap.
- **Strong reuse of existing primitives.** The plan wisely builds on `update_stage`, `cancel_job`, `mark_failed`, `reconcile_all`, and `infer_resume_point` rather than reinventing persistence or failure semantics.
- **Security-conscious defaults.** Idempotency keys are validated pre-DB (charset + length), subscriber caps prevent WS DoS, and race conditions are handled via `IntegrityError` catch.
- **Hardware constraints respected.** Worker=1 strict FIFO, JIT model load, no concurrent model residency, and no external broker keep the MVP feasible on the 8 GB laptop target.
- **Test-driven scaffolding.** RED/GREEN tasking with explicit xfail markers and `run_worker=False` for manual test control gives good coverage confidence.

### Concerns

- **HIGH — Stale sweep will false-positive on long transcriptions.** The 10-minute `is_stale` threshold is checked by a watchdog every 60 s, but the orchestrator never updates a heartbeat or stage file *during* the `transcribing` stage. A 20-minute video will be incorrectly marked stale while still chunking through the GPU. *(Severity: HIGH — directly kills legitimate jobs)*
- **MEDIUM — Worker loop omits the poll fallback for missed signals.** 04-02 relies on a pure `asyncio.Event` (`await _work_signal.wait(); _work_signal.clear()`). Per the project's own RESEARCH.md Pitfall 1, this can stall if the signal fires before the worker awaits. The recommended hybrid (Event + 2 s poll) is not present. *(Severity: MEDIUM — queue can deadlock on race)*
- **MEDIUM — `run_job` lacks explicit stage-skip / resume logic.** The 04-01 test expects that crashing during ingest and re-invoking `run_job` will re-enter at `transcribing`, but the implementation bullets do not describe calling `infer_resume_point` or conditionally skipping completed stages. Without this, `run_job` may attempt to re-run `update_stage('ingested')` on an already-ingested job. *(Severity: MEDIUM — incorrect re-entrant behavior)*
- **MEDIUM — Concrete STT adapter is not updated for new kwargs.** 04-01 extends the `STTAdapter` Protocol with keyword-only `progress_cb` and `cancel_flag`, and updates `tests/_stt_fake.py`, but there is **no task to update the real `FasterWhisperAdapter`** (or any other concrete implementation). Production code will raise `TypeError` on the new signature. *(Severity: MEDIUM — runtime breakage on real transcription)*
- **MEDIUM — Abrupt worker shutdown during `run_in_executor`.** The lifespan teardown cancels the worker task, but the sync transcription thread inside `run_in_executor` cannot be killed. The `finally` block may unload the model while the thread is still executing, leading to use-after-free or partial writes. *(Severity: MEDIUM — unclean shutdown / potential crash on exit)*
- **LOW — No janitor for expired idempotency keys.** Expired keys are deleted inline on duplicate lookup, but there is no periodic cleanup; the table will grow indefinitely. Mitigated by single-user local use, but still a hygiene gap. *(Severity: LOW)*
- **LOW — Inverted dependency for `JobCancelled`.** Placing `JobCancelled` in `app/jobs/orchestrator.py` forces `app/models/stt/chunker.py` to import upward into the jobs layer, violating the project's directional boundary. *(Severity: LOW)*

### Suggestions

- **Add a heartbeat mechanism for long stages.** Between chunks (and in the progress callback path), touch a `heartbeat` file in the job directory or update a lightweight `updated_at` column so `is_stale` does not kill active transcriptions. Alternatively, document that `is_stale` must be disabled/ignored for `transcribing` jobs until mid-stage heartbeats are implemented.
- **Use the hybrid Event + poll fallback in the worker loop.** Change `pull_next` to: try the Event with a short timeout, else poll every 2 s. This matches RESEARCH.md Pattern 4 and eliminates the missed-signal stall risk.
- **Explicitly integrate `infer_resume_point` into `run_job`.** At the top of `run_job`, call `infer_resume_point(job_id)` to determine the resume stage. Branch so that completed stages are skipped rather than blindly re-executed. This is required to make the 04-01 `test_restart_rejoin` meaningful.
- **Add a 04-01 task to update the concrete adapter.** `FasterWhisperAdapter.transcribe` must accept `*, progress_cb=None, cancel_flag=None` (or `**kwargs`) and forward them to `transcribe_file`. Without this, the Phase 3 adapter will not satisfy the Phase 4 Protocol.
- **Graceful shutdown for in-flight transcription.** Before cancelling the worker task, set the `cancel_flag` and `await` the `run_in_executor` future with a timeout (or let the chunker exit cleanly). Only then proceed to model unload and engine disposal.
- **Move `JobCancelled` to a shared exceptions module** (e.g., `app/jobs/errors.py` or `app/models/shared.py`) so `chunker.py` imports horizontally rather than upward into the orchestrator.
- **Consider persisting transient progress to the manifest** (optional, future). If the WS snapshot is meant to show accurate percent/ETA on reconnect, write a lightweight `progress.json` atomically on each progress event so `read_manifest` can source it. For MVP, document that reconnecting clients see stale percent until the next live event.

### Risk Assessment

**Overall Risk Level: MEDIUM**

**Justification:** The architectural skeleton is sound and correctly scoped, but the plans carry **real operational risks** that could surface immediately in MVP usage: the stale watchdog will kill long transcriptions, the worker can stall on a missed signal, and the production STT adapter will throw on the new Protocol signature. None of these require scope expansion—each is fixable within the existing wave structure (heartbeat touch, poll fallback, adapter kwargs). The plan should be accepted **with the above amendments** before execution begins, particularly the heartbeat and worker-loop changes, which are one-line/two-line fixes with outsized impact.

---

## Consensus Summary

Two of three invited reviewers produced substantive reviews. Codex (codex CLI) and Ollama (kimi-k2.6:cloud) independently converged on the same architectural strengths and, more importantly, on the same class of operational correctness risks. Gemini did not produce a review (CLI client deprecated by Google — see status note above).

### Agreed Strengths (raised by 2+ reviewers)

- **Clean three-wave decomposition** — each plan has a single well-defined responsibility and explicitly declares what it consumes from prior waves; no scope overlap. *(Codex, Ollama)*
- **Strong reuse of existing Phase 1–3 primitives** — `manifest.update_stage`, `cancel_job`, `mark_failed`, `reconcile_all`, `infer_resume_point`, `cleanup.py`; no reinvention of persistence/failure semantics. *(Codex, Ollama)*
- **Hardware constraints respected** — worker=1 strict FIFO, single-GPU residency, JIT model load, no external broker, feasible on the 8 GB laptop target. *(Codex, Ollama)*
- **Test-driven scaffolding** — RED/GREEN tasking, explicit xfail markers, `run_worker=False` for manual test control. *(Codex, Ollama)*
- **Security/DoS-conscious defaults** — pre-DB idempotency key validation, WS subscriber caps, bounded EventBus queues. *(Codex, Ollama)*

### Agreed Concerns (raised by 2+ reviewers — highest priority)

1. **HIGH — Worker loop relies on a bare `asyncio.Event` with no poll fallback.** Both reviewers flag this and both cite the project's own `RESEARCH.md` (Pitfall 1 / Pattern 4) recommending a hybrid Event + ~2s poll to survive a signal that fires before the worker awaits. Without it the queue can deadlock on a missed wakeup. *(Codex HIGH, Ollama MEDIUM)*
2. **MEDIUM — `JobCancelled` placement inverts the dependency direction.** Defined in `app/jobs/orchestrator.py` but imported by `app/models/stt/chunker.py`, forcing a lower-level STT module to import upward into the jobs layer. Both recommend relocating it to a neutral shared exceptions module (`app/jobs/errors.py` or `app/models/shared.py`). *(Codex MEDIUM, Ollama LOW)*
3. **MEDIUM — Progress is not persisted, so WS reconnect snapshots cannot report nonzero percent/ETA.** 04-03's snapshot-on-connect depends on state that 04-01 never writes. Both suggest a lightweight persistent progress store (`progress.json` in the job dir or a manifest field) or explicitly documenting that reconnecting clients see stale percent until the next live event. *(Codex MEDIUM, Ollama — suggestion)*
4. **MEDIUM — `run_in_executor` threading hazards.** Codex flags that passing kwargs to `run_in_executor` is invalid (needs `functools.partial`); Ollama flags the related shutdown hazard — the sync transcription thread inside the executor cannot be killed, so lifespan teardown may unload the model mid-execution (use-after-free / partial writes). Both want graceful, cooperative shutdown of the in-flight transcription future. *(Codex HIGH, Ollama MEDIUM)*

### Divergent Views (worth investigating)

- **Stale-watchdog false positive on long transcriptions (Ollama HIGH, Codex did not raise).** Ollama's highest-severity finding is unique: the 10-minute `is_stale` threshold is checked every 60s, but nothing touches a heartbeat *during* the `transcribing` stage — so a 20-minute video is marked stale and killed while still chunking on the GPU. This directly violates success criterion #2 (restart rejoinability) and would surface immediately in real use. **Recommend adopting Ollama's heartbeat suggestion before execution regardless of Codex's silence.**
- **Stage naming / completion-timing (Codex HIGH, Ollama did not raise).** Codex catches that the plan alternates between publishing `ingesting` and calling `update_stage("ingested")` / `update_stage("transcribed")` *before* the work actually completes — marking stages done too early. Ollama instead frames the related issue as missing `infer_resume_point` integration in `run_job` (stage-skip on re-entry). These are two angles on the same stage-lifecycle contract: **completion must be recorded only after the output file exists, and re-entry must skip completed stages via `infer_resume_point`.**
- **Idempotency race / atomicity (Codex HIGH, Ollama LOW).** Codex raises three distinct HIGH issues in 04-03 — (a) job created before idempotency key inserted → orphan duplicate on collision, (b) column named `key` is SQL-reserved, (c) `app.state` accessors not established in prior plans. Ollama only notes the missing janitor for expired keys (LOW). Codex's idempotency ordering concern is the more operationally dangerous one and should be addressed.
- **Atomic job claiming (Codex HIGH, Ollama did not raise).** Codex flags that `pull_next` selects the next queued job without atomically claiming it, so a duplicate worker (or duplicated lifespan task) can run the same job twice. Worth hardening even for a single-worker MVP as a defensive measure.
- **Concrete adapter not updated for new kwargs (Ollama MEDIUM, Codex did not raise).** Ollama catches that 04-01 extends the `STTAdapter` Protocol and updates the fake, but has no task to update the real `FasterWhisperAdapter` — production will `TypeError` on the new `progress_cb`/`cancel_flag` signature. This is a concrete, easily-missed omission.

### Top Actionable Fixes to Fold Back Into Planning

1. **Hybrid Event + poll worker loop** (04-02) — `asyncio.wait_for(_work_signal.wait(), timeout=2.0)` with poll on timeout. *(both reviewers)*
2. **Heartbeat during long stages** (04-01/04-02) — touch a heartbeat file or `updated_at` between chunks so `is_stale` does not kill active transcriptions; or explicitly exclude `transcribing` from the stale sweep. *(Ollama HIGH)*
3. **`functools.partial` for executor kwargs + graceful in-flight shutdown** (04-01) — cooperative `cancel_flag` then `await` the executor future with timeout before model unload. *(both reviewers)*
4. **Stage completion only after output exists + `infer_resume_point` stage-skip in `run_job`** (04-01) — fixes both the early-completion bug and re-entrant correctness. *(Codex HIGH + Ollama MEDIUM)*
5. **Move `JobCancelled` to a shared exceptions module** (04-01) — remove the STT→orchestration upward import. *(both reviewers)*
6. **Atomic job claiming in `pull_next`** (04-02) — conditional `UPDATE ... WHERE status='queued'`, only run if one row changed. *(Codex HIGH)*
7. **Idempotency: reserve key first in one transaction; rename column `key` → `idempotency_key`; establish `app.state.settings`/`session_factory`** (04-03). *(Codex HIGH)*
8. **Add a task to update `FasterWhisperAdapter` for the new Protocol kwargs** (04-01) — otherwise production transcription throws. *(Ollama MEDIUM)*
9. **Persist a lightweight progress snapshot** (04-01/04-03) — or document stale-percent-on-reconnect behavior explicitly. *(both reviewers)*

**Consensus risk level: MEDIUM-HIGH.** The architecture is sound and correctly scoped; the risk is concentrated in ordering/atomicity and a few operational hazards (stale watchdog, worker wakeup, adapter signature) that are all fixable within the existing wave structure with small, targeted amendments before execution.