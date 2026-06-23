---
phase: 04-job-orchestrator-persistent-queue-websocket-progress
plan: 05
subsystem: job-orchestrator
tags: [restart-persistence, interrupt-sweep, watchdog, resume, gap-closure, CR-01, CR-02]
requires:
  - 04-01 (orchestrator run_job, _running, JobCancelled path)
  - 04-02 (mark_interrupted_failed, run_watchdog, pull_next atomic claim)
  - 04-04 (CR-03 run_job-side resume_stage == "done" advance — complementary)
provides:
  - "CR-01 closed: boot-sweep + watchdog SELECT widened to include 'starting' so a crashed-in-claim job is recovered on the next boot"
  - "CR-02 closed: mark_interrupted_failed consults infer_resume_point per swept job and advances to done (via update_stage) when resume_point is None or 'done', preserving the user's completed transcription"
affects:
  - app/jobs/interrupt.py
  - app/jobs/queue.py
  - tests/test_orchestrator.py
tech-stack:
  added: []
  patterns:
    - "file-as-truth resume consultation at the boot sweep (infer_resume_point verdict drives fail-vs-advance decision)"
    - "write-manifest-first / commit-DB-last advance via update_stage (mirrors orchestrator happy path)"
key-files:
  created: []
  modified:
    - app/jobs/interrupt.py
    - app/jobs/queue.py
    - tests/test_orchestrator.py
decisions:
  - "Filter-widening approach chosen over zero-width 'starting' window (run_job calling update_stage('ingested') first) to avoid changing 04-01's orchestrator wiring and conflicting with 04-04."
  - "CR-02 advance uses update_stage('done') (write-manifest-first / commit-DB-last) — the SAME call the orchestrator happy path makes — so reconcile_all stays consistent for the advanced row."
  - "The manifest-less FileNotFoundError branch is preserved (fail DB-row only); infer_resume_point requires a manifest so no resume consultation is attempted for a manifest-less job."
  - "A 'starting' job is correctly FAILED, not advanced: infer_resume_point returns 'ingested' (no source file, manifest.source_path=None), not None/'done' — asserted by test_starting_job_swept_to_failed."
metrics:
  duration: 10m
  tasks: 2
  files: 3
  completed: 2026-06-23
---

# Phase 4 Plan 5: CR-01 + CR-02 Restart-Persistence Gap Closure Summary

Boot-sweep + watchdog SELECT widened to include the transient `starting` status (CR-01), and `mark_interrupted_failed` now consults `infer_resume_point` per swept job, advancing to `done` (via `update_stage`) when the resume walker says the stages are file-complete — preserving the user's completed transcription instead of orphaning it (CR-02).

## What Was Built

### Task 1 — TDD RED: two regression tests (commit b416ab2)

Appended two tests to `tests/test_orchestrator.py` (behind the existing `_QUEUE_AVAILABLE` xfail guard, mirroring `test_boot_interrupted_sweep` conventions):

- `test_starting_job_swept_to_failed` (CR-01): creates a job via `create_job` (NOT `_make_local_job` — no source file, `manifest.source_path=None`), forces DB status to `starting`, runs the boot sweep, and asserts `swept == 1` AND `get_job(...).status == "failed"` (NOT `"done"`). This verifies the widened SELECT catches the `starting` row AND that the `infer_resume_point` consultation does NOT advance a starting job (the walker returns `"ingested"`, not None/`"done"`).
- `test_transcribed_job_advanced_to_done_on_boot` (CR-02): uses `_make_local_job`, pre-writes a valid `transcript.json` (Transcript-shape, non-empty segments) at `transcript_path(s, job_id)`, forces `manifest.current_stage="transcribed"` + DB status=`transcribing`, runs the boot sweep, and asserts `get_job(...).status == "done"` AND `read_manifest(...).current_stage == "done"` AND `read_manifest(...).status == "done"` AND `transcript_path(...).exists()` AND `manifest.error != "interrupted (backend restarted)"`. This verifies the advance-to-done branch fires and the user's completed transcription is preserved.

Both tests confirmed RED against the unfixed code: CR-01 `swept == 0` (starting excluded from SELECT), CR-02 `status == "failed"` (sweep marked the transcribed job failed without consulting the resume walker).

### Task 2 — GREEN: SELECT widening + infer_resume_point consultation (commit 5d5cad5)

**CR-01 — `app/jobs/interrupt.py::mark_interrupted_failed`** SELECT widened from `status IN ('ingesting','transcribing')` to `status IN ('starting','ingesting','transcribing')`. The transient `starting` status set by `pull_next`'s atomic claim is now swept at boot.

**CR-01 — `app/jobs/queue.py::run_watchdog`** SELECT widened identically. A stuck `starting` job is now eligible for the stale check (after the 600s `is_stale` threshold). The `is_stale` + `mark_stale` logic is unchanged.

**CR-02 — `app/jobs/interrupt.py::mark_interrupted_failed`** loop restructured:

1. Read the manifest FIRST (try/except FileNotFoundError). On a missing manifest, log the warning, `await mark_failed(session, job_id, _INTERRUPTED_ERROR)`, `swept += 1`, `continue` — no resume consultation is possible (infer_resume_point requires a manifest).
2. On a successful read, consult `resume_point = infer_resume_point(settings, job_id, manifest)`.
3. If `resume_point is None or resume_point == "done"`: call `await update_stage(settings, session, job_id, "done")` (write-manifest-first / commit-DB-last — the SAME call the orchestrator happy path makes at orchestrator.py:281), log at INFO, `swept += 1`, `continue` (skip `mark_failed` + the failed-manifest `atomic_write_json`).
4. Otherwise (`resume_point` is a real incomplete stage like `"ingested"` / `"transcribed"`): proceed as before — `await mark_failed(session, job_id, _INTERRUPTED_ERROR)` then `atomic_write_json` the manifest to failed (`status='failed'`, `current_stage='failed'`, `error=_INTERRUPTED_ERROR`).

New imports: `from app.jobs.manifest import read_manifest, update_stage` (update_stage added) and `from app.jobs.resume import infer_resume_point`.

The `starting` case: `manifest.source_path` is None and no source file exists → `is_stage_complete("ingested")=False` → `infer_resume_point` returns `"ingested"` (not None, not `"done"`) → the sweep proceeds to `mark_failed`. The starting job is correctly FAILED, not advanced (asserted by `test_starting_job_swept_to_failed`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module docstring + SELECT line-wrapping blocked acceptance grep**
- **Found during:** Task 2 verification
- **Issue:** The plan's acceptance grep `grep -v '^#' app/jobs/interrupt.py | grep -c "IN ('ingesting','transcribing')"` expects 0 (old narrow filter entirely gone). The original module docstring at line 4 still contained the literal `` ``status IN ('ingesting','transcribing')`` `` describing the OLD behavior, which would have left a stale reference and failed the grep. Separately, the widened SELECT was initially split across two source lines (`"WHERE status IN "` + `"('starting','ingesting','transcribing')"`) which broke the `grep -c "IN ('starting','ingesting','transcribing')"` acceptance check for `queue.py` (returned 0 instead of 1).
- **Fix:** Rewrote the module docstring to describe the widened SELECT and the CR-02 advance-to-done behavior; collapsed both SELECT string literals (interrupt.py + queue.py) onto a single source line so the acceptance grep matches the actual code.
- **Files modified:** app/jobs/interrupt.py, app/jobs/queue.py
- **Commit:** 5d5cad5

### Test-count note

The plan's acceptance criterion expected "40 total" tests after adding 2 new ones to a 38-test baseline. The actual count is **41 passed**: the baseline is 39, not 38, because plan 04-04 already added `test_resume_advances_to_done_when_both_stages_complete` to the same file. 04-05 adds 2 on top of that 39 → 41. No regression — all 41 pass.

## Verification

All acceptance criteria verified:

- `grep -v '^#' app/jobs/interrupt.py | grep -c "IN ('starting','ingesting','transcribing')"` → 3 (docstring + code) ✓
- `grep -v '^#' app/jobs/queue.py | grep -c "IN ('starting','ingesting','transcribing')"` → 1 ✓
- `grep -c "infer_resume_point" app/jobs/interrupt.py` → 6 (import + docstring/comments + call) ✓ (≥2)
- `grep -c "update_stage" app/jobs/interrupt.py` → 11 (import + docstring + call) ✓ (≥2)
- `grep -c 'update_stage(settings, session, job_id, "done")' app/jobs/interrupt.py` → 1 ✓
- `grep -v '^#' app/jobs/interrupt.py | grep -c "IN ('ingesting','transcribing')"` → 0 ✓ (old filter gone)
- `grep -v '^#' app/jobs/queue.py | grep -c "IN ('ingesting','transcribing')"` → 0 ✓ (old filter gone)
- `python -m pytest tests/test_orchestrator.py::test_starting_job_swept_to_failed -x -q` → passes (starting job swept to failed, NOT advanced) ✓
- `python -m pytest tests/test_orchestrator.py::test_transcribed_job_advanced_to_done_on_boot -x -q` → passes (transcribed job advanced to done, transcript.json preserved) ✓
- `python -m pytest tests/test_orchestrator.py::test_boot_interrupted_sweep -x -q` → passes (no regression — existing ingesting/transcribing sweep still fails both) ✓
- `python -m pytest tests/test_orchestrator.py tests/test_cancel.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py -q` → **41 passed** (39 prior + 2 new; no regression) ✓

## TDD Gate Compliance

- RED gate (commit b416ab2, `test(04-05):`): both new tests failed against the unfixed code for the right reasons — CR-01 `swept == 0` (starting excluded), CR-02 `status == "failed"` (sweep marked the transcribed job failed without consulting the resume walker).
- GREEN gate (commit 5d5cad5, `fix(04-05):`): both new tests pass after the SELECT widening + infer_resume_point consultation; the existing 39-test suite still passes.

## Threat Model

All five threats in the plan's `<threat_model>` are `accept` or `mitigate` (via existing validation). No new trust boundary introduced. T-04-05-04 (corrupt transcript.json) is mitigated by the existing `parse_stage_file(path, model_cls=Transcript)` validation — a corrupt file fails `is_stage_complete("transcribed")`, so `infer_resume_point` returns `"transcribed"` (not `"done"`) and the sweep proceeds to `mark_failed`. T-04-05-05 (starting job accidentally advanced) is mitigated by `test_starting_job_swept_to_failed` — a starting job has no source file, `infer_resume_point` returns `"ingested"`, the advance branch does NOT fire.

## Known Stubs

None. The advance-to-done branch calls the real `update_stage` (write-manifest-first / commit-DB-last) — the same primitive the orchestrator happy path uses. No placeholder data, no mock wiring.

## Threat Flags

None. No new network endpoint, auth path, file access pattern, or schema change at a trust boundary. The fix widens two existing SELECT filters and adds a per-row consultation of an already-trusted resume walker; the file-as-truth invariant (transcript.json must parse as `Transcript` before the done transition) is preserved.

## Self-Check: PASSED

- app/jobs/interrupt.py — FOUND (modified, SELECT widened + advance branch)
- app/jobs/queue.py — FOUND (modified, watchdog SELECT widened)
- tests/test_orchestrator.py — FOUND (two new tests appended)
- Commit b416ab2 — FOUND (RED gate)
- Commit 5d5cad5 — FOUND (GREEN gate)