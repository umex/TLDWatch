---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 07
subsystem: backend-stt-orchestrator + frontend-history-row
tags: [gap-closure, duration, transcript, chunker, orchestrator, history-ui]
requires:
  - 05-04 (manifest projection H3+H4 -- update_stage SET clause carries duration_s)
  - 05-05 (preparing emission block lives in a different orchestrator region; must stay untouched)
provides:
  - Transcript.duration_s additive optional field (source media duration in seconds)
  - Chunker populates duration_s = total_seconds on both fast + chunked return paths
  - Orchestrator transcribed transition projects duration_s to manifest + DB via ManifestPatch
  - HistoryRow regression guards for 00:42 / 02:05 / --:-- rendering
affects:
  - app/models/transcript.py
  - app/models/stt/chunker.py
  - app/jobs/orchestrator.py
  - tests/test_orchestrator.py
  - web/src/components/HistoryRow.test.tsx
tech-stack:
  added: []
  patterns:
    - additive-optional-field-with-default (Pydantic backward-compat for transcript.json)
    - manifest-DB-projection-via-existing-H3+H4-SET-clause (duration_s re-projected on done)
decisions:
  - duration_s semantic = source MEDIA duration (chunker total_seconds), NOT wall-clock processing time
  - No change to done transition or resume->done branch (H3+H4 re-projects existing manifest.duration_s)
  - No change to HistoryRow.tsx (formatDuration already handled non-null correctly; bug was back-end)
  - FE tests pass immediately as regression guards (no RED state for FE -- bug was purely back-end)
key-files:
  created:
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-07-SUMMARY.md
  modified:
    - app/models/transcript.py
    - app/models/stt/chunker.py
    - app/jobs/orchestrator.py
    - tests/test_orchestrator.py
    - web/src/components/HistoryRow.test.tsx
metrics:
  duration: ~9 min
  completed: 2026-06-26
  tasks: 2
  files: 5
---

# Phase 5 Plan 07: Completed-job duration_s population (gap closure) Summary

Propagate the chunker-computed source media duration (`total_seconds = len(audio)/SAMPLE_RATE`) through `Transcript.duration_s`, both `transcribe_file` return paths, and the orchestrator's `transcribed` transition `ManifestPatch` so a completed job's `GET /jobs/{id}` returns a non-null `duration_s` and `HistoryRow` renders `MM:SS` instead of `--:--`. The `done` transition re-projects the already-set value via the existing H3+H4 `update_stage` SET clause (no done-branch change). The 05-05 preparing emission block and 05-04 H3+H4 projection invariant are preserved.

## What Was Built

### Back-end (Task 1)

- **`app/models/transcript.py`**: added `duration_s: float | None = None` to `Transcript` after `language` and before `segments`. Additive, optional, default `None` -- existing `transcript.json` files load with `duration_s=None` (the model is lax for output / internal storage per the module docstring).
- **`app/models/stt/chunker.py`**: both `transcribe_file` return paths pass `duration_s=total_seconds`:
  - Fast path (single-call, <=30 min): `return Transcript(..., duration_s=total_seconds)`.
  - Chunked path (>30 min): `return Transcript(job_id=..., language=lang, segments=merged, duration_s=total_seconds)`.
  - `total_seconds` is computed once at the top of `transcribe_file` (`total_samples / SAMPLE_RATE`) and is the source MEDIA duration, consistent with the field's colocation with `source_sha256`/`source_path` (media metadata) and the failed-jobs `00:42` the user observed.
- **`app/jobs/orchestrator.py`**: the `transcribed` transition's `ManifestPatch` now passes `duration_s=transcript.duration_s` alongside `language=transcript.language`. `ManifestPatch` already had the `duration_s` field (app/models/job.py:66). With `exclude_unset=True` in `update_stage` (manifest.py:209), both fields are applied. The `done` transition (lines 295-296) needs NO change -- `update_stage("done")` reads the current manifest (which now carries `duration_s` from the transcribed transition) and re-projects it via the existing `duration_s = :duration_s` binding (manifest.py:231, 244). The resume->done branch (lines 320-321) also needs NO change: by the time resume reaches "done", the transcribed transition already set `duration_s` on the manifest; if it was never set (a job that crashed before transcribed), `duration_s` stays `None` and `HistoryRow` renders `--:--`, the correct fallback for an incomplete job.
- **`tests/test_orchestrator.py`**: new test `test_done_job_duration_s_populated` mirroring `test_state_machine` (local-source job + `FakeAdapter` fast path). After `await run_job(...)`, asserts `row.status == "done"`, `row.duration_s is not None`, `row.duration_s > 0`, and `manifest.duration_s == row.duration_s` (H3+H4 projection invariant holds for `duration_s`).

### Front-end (Task 2)

- **`web/src/components/HistoryRow.test.tsx`**: new describe block "HistoryRow duration rendering (plan 05-07)" with 3 tests: `00:42` for `duration_s:42`, `02:05` for `duration_s:125`, and `--:--` for `duration_s:null`. The existing `formatDuration` + `formatDuration(job.duration_s)` render at `HistoryRow.tsx:49` already handled non-null correctly -- the bug was purely back-end (the field was always `None` on the happy path). These tests are regression guards: they lock in both the populated and blank rendering so a regression on either side is caught.
- **No change to `web/src/components/HistoryRow.tsx`** -- the existing `formatDuration` is correct.

## TDD Gate Compliance

Task 1 (back-end, `tdd="true`):
- RED: `test(05-07): add failing test for completed-job duration_s population` (commit `d2110d6`) -- the new `test_done_job_duration_s_populated` failed with `row.duration_s == None` (orchestrator transcribed transition passed no `duration_s`).
- GREEN: `feat(05-07): propagate media duration through Transcript + chunker + orchestrator` (commit `a9594c2`) -- added the `Transcript.duration_s` field, populated both chunker paths, and projected through the transcribed `ManifestPatch`. The new test passes; all 282 pre-existing BE tests stay green (283 passed total).

Task 2 (front-end, `tdd="true"`):
- The FE `formatDuration` was already correct -- the bug was purely back-end. The 3 new tests pass immediately as regression guards (no RED state possible for the FE because there was no FE bug to fix). Committed as a single test-addition commit `250eab2`. This is documented in the plan (line 211: "No change to HistoryRow.tsx ... the bug was the back-end never populating the field") -- the TDD RED gate is satisfied by the back-end Task 1 RED, and the FE tests lock the rendering contract.

## Deviations from Plan

None -- plan executed exactly as written. The only nuance is that Task 2's FE tests pass on first run (no RED state) because the FE was already correct; this is explicitly anticipated in the plan's `Artifacts this phase produces` section (line 211).

## Verification

- `python -m pytest tests/test_orchestrator.py::test_done_job_duration_s_populated -x` -- the new orchestrator test passes (`row.duration_s is not None`, `> 0`, `manifest.duration_s == row.duration_s`).
- `python -m pytest tests/ -q` -- full back-end suite green: **283 passed** (282 existing + 1 new). 4 warnings are pre-existing aiosqlite event-loop-closed cleanup noise, not regressions.
- `npx vitest run HistoryRow.test.tsx` -- **6 passed** (3 existing filename + 3 new duration).
- `npx vitest run` -- full FE suite green: **32 passed** (6 test files, 27 prior + 3 new duration tests; one new plan-05-06 test was already present).
- `npx tsc --noEmit` -- clean (no errors).
- `npm run build` -- `vite build` succeeds (89 modules, 537.57 kB main bundle, built in 1.96s).
- Grep checks (from plan `<verification>`):
  - `app/models/transcript.py` `duration_s` count == 1 (field added).
  - `app/models/stt/chunker.py` `duration_s=total_seconds` count == 2 (both return paths).
  - `app/jobs/orchestrator.py` `duration_s=transcript.duration_s` count == 1 (transcribed transition).

## Invariant Preservation

- **05-05 preparing emission block untouched**: the `stage_changed(preparing)` block (orchestrator.py:251-263) was NOT edited -- this plan touched only the `transcribed`/`done` transition region (orchestrator.py:290-296). `test_preparing_event_emitted_before_transcribing_on_production_path` and `test_preparing_event_not_emitted_on_test_path` both passed in the full back-end run.
- **05-04 H3+H4 manifest projection preserved**: `update_stage` (app/jobs/manifest.py) SET clause still binds `duration_s = :duration_s` (line 231) and param `new_manifest.duration_s` (line 244). No change to manifest.py. The `done` transition re-projects `duration_s` through this existing SET clause -- the H3+H4 invariant is preserved (the new test asserts `manifest.duration_s == row.duration_s`).
- **duration_s semantics**: = source MEDIA duration (chunker `total_seconds = len(audio)/SAMPLE_RATE`), consistent with the failed-jobs `00:42` the user observed and the field's colocation with `source_sha256`/`source_path`. Not redefined as wall-clock processing time.
- **Backward compatibility**: existing `transcript.json` files load with `duration_s=None` (additive optional field with default None). No existing test or fixture required updating.

## Threat Flags

None. The threat model (T-05-07-01/02/03) assigned `accept` to all three threats: `duration_s` is an additive nullable column already present from Phase 1-02, now populated from server-internal chunker output (not user-controllable); the upload route's `X-Filename` cannot touch it; `ManifestPatch` already validated `duration_s` as `float | None` (strict, extra=forbid); `len(audio)/SAMPLE_RATE` is already computed at chunker.py:130 for the fast-path/chunked-path threshold decision, so reusing it adds no work. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond what the plan's `<threat_model>` already enumerated.

## Self-Check: PASSED

- `app/models/transcript.py` -- FOUND
- `app/models/stt/chunker.py` -- FOUND
- `app/jobs/orchestrator.py` -- FOUND
- `tests/test_orchestrator.py` -- FOUND
- `web/src/components/HistoryRow.test.tsx` -- FOUND
- `.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-07-SUMMARY.md` -- FOUND
- Commit `d2110d6` (RED test) -- FOUND
- Commit `a9594c2` (GREEN implementation) -- FOUND
- Commit `250eab2` (FE regression-guard tests) -- FOUND