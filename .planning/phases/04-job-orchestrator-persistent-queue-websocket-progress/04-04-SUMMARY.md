---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
plan: 04
subsystem: jobs/orchestrator
tags: [orchestrator, state-machine, resume, gap-closure, CR-03]
requires:
  - 04-01-SUMMARY (run_job state machine, infer_resume_point, manifest.update_stage)
  - 04-VERIFICATION (CR-03 gap description)
provides:
  - "run_job advances a crash-window job (both stages file-complete, current_stage != 'done') to done on re-entry"
  - "Regression test test_resume_advances_to_done_when_both_stages_complete"
affects:
  - app/jobs/orchestrator.py
  - tests/test_orchestrator.py
tech-stack:
  added: []
  patterns:
    - "Additive final-branch for previously-unhandled resume_stage value (no existing branch modified)"
key-files:
  created: []
  modified:
    - app/jobs/orchestrator.py
    - tests/test_orchestrator.py
decisions:
  - "Fix is purely additive -- new `if resume_stage == \"done\":` branch after the two `if not skip_*` blocks; the happy-path update_stage('done') and the resume_stage is None early-return are untouched."
  - "No ManifestPatch passed to update_stage('done') in the resume branch -- the manifest already carries the transcribed language patch from the previous (crashed) run."
  - "INFO log `run_job %s: advanced to done via resume` makes the recovery observable in logs."
metrics:
  duration: ~6m
  tasks: 2
  files: 2
  tests: 39 (38 prior + 1 new)
completed: 2026-06-23
---

# Phase 4 Plan 04: CR-03 Gap-Closure Summary

run_job gains a final `if resume_stage == "done":` branch that advances a crash-window job (transcript.json on disk, manifest.current_stage="transcribed", DB status="transcribing") to done on re-entry, publishing the done event -- the state machine no longer has a dead-end state.

## What Was Built

### Task 1: RED regression test (commit 85911bc)

Added `test_resume_advances_to_done_when_both_stages_complete` to `tests/test_orchestrator.py`. The test simulates the crash window between `update_stage("transcribed")` and `update_stage("done")` by:

1. Creating a local-source job (source.mp4 exists -> `is_stage_complete("ingested")=True`).
2. Pre-writing a valid `transcript.json` via `atomic_write_json` with a minimal `Transcript` (one segment) so `is_stage_complete("transcribed")=True`.
3. Forcing `manifest.current_stage="transcribed"` via `write_manifest` + DB `status="transcribing"` via raw `UPDATE jobs` (the post-crash state -- `stage_to_status("transcribed")` maps to `"transcribing"`).
4. Subscribing a recording queue on an `EventBus` and calling `run_job` with a `FakeAdapter`.

Assertions: (a) `read_manifest(...).current_stage == "done"`; (b) fresh `get_job(...).status == "done"`; (c) a `{"type":"done"}` event was published to the bus; (d) `FakeAdapter.call_count == 0` (skip_transcribed=True -- no re-transcription). The test also sanity-asserts `infer_resume_point(...) == "done"` before the call, proving the resume walker's verdict is exactly the previously-unhandled value.

Ran RED against the unfixed orchestrator (commit 85911bc): `current_stage` stayed `"transcribed"` -- the dead-end -- confirming the test exercises CR-03.

### Task 2: GREEN fix (commit fef9716)

Added a final `if resume_stage == "done":` branch in `app/jobs/orchestrator.py`, placed after the `if not skip_transcribed:` block closes and before `except JobCancelled:`. The branch:

- Opens `async with session_factory() as session:` and calls `await update_stage(settings, session, job_id, "done")` (mirrors the happy-path call at line 281, no ManifestPatch -- the transcribed language patch already landed in the previous crashed run).
- Calls `_publish({"type": "done"})` (mirrors the happy-path publish at line 282 so WS clients receive the done event on the derived transition).
- Logs at INFO: `run_job %s: advanced to done via resume` so the recovery is observable.

The branch fires ONLY in the crash window (`resume_stage == "done"`); in the happy path `resume_stage == "transcribed"` (or `"ingested"`) and the branch is skipped; in the no-op path `resume_stage is None` and the function already early-returned at line 207. No `return` is added -- the function falls through to the `finally` block normally (which pops `_running` and unloads the model only if `loaded_by_run`, which is False in the resume-skip path).

## Verification

All acceptance criteria from the plan met:

- `grep -n 'resume_stage == "done"' app/jobs/orchestrator.py` -> 1 match (line 284, the new branch).
- `grep -c 'update_stage(settings, session, job_id, "done")' app/jobs/orchestrator.py` -> 2 (happy path at line 281 + new branch at line 296).
- `grep -c '"type": "done"' app/jobs/orchestrator.py` -> 2 (happy path + new branch).
- `grep -n "resume_stage is None" app/jobs/orchestrator.py` -> 1 match (line 205, the early-return preserved).
- `grep -v '^#' app/jobs/orchestrator.py | grep -c 'if not skip_transcribed'` -> 1 (happy-path block preserved).
- `python -m pytest tests/test_orchestrator.py::test_resume_advances_to_done_when_both_stages_complete -x -q` -> 1 passed (GREEN).
- `python -m pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_cancel.py tests/test_ws.py tests/test_idempotency.py -x -q` -> 39 passed in 4.57s (no regression; expected count 39 = 38 prior + 1 new).

## TDD Gate Compliance

- RED gate: commit `85911bc` (`test(04-04): add CR-03 crash-window regression test (RED)`) -- test FAILED against the unfixed orchestrator (current_stage stayed "transcribed").
- GREEN gate: commit `fef9716` (`fix(04-04): close CR-03 -- run_job advances to done on resume`) -- test PASSED after the fix; full phase suite still passed.

Both gates present in git log in the correct order.

## Deviations from Plan

None - plan executed exactly as written.

## Threat Flags

None. The fix is purely additive (a new branch for a previously-unhandled `resume_stage` value) and does not widen any trust boundary or introduce any new input path. The file-as-truth invariant (`transcript.json` must exist before the done transition) is preserved -- the new branch fires only when `is_stage_complete("transcribed")=True`, which requires a valid `Transcript`-shaped `transcript.json` on disk. The threat register in the plan (T-04-04-01/02/03) assessed all three STRIDE categories as `accept` with no new surface; the implementation matches that assessment.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: app/jobs/orchestrator.py (modified -- new branch at line 284)
- FOUND: tests/test_orchestrator.py (modified -- new test appended)
- FOUND: 85911bc (test(04-04): add CR-03 crash-window regression test (RED))
- FOUND: fef9716 (fix(04-04): close CR-03 -- run_job advances to done on resume)