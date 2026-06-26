---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 05
subsystem: api, ui
tags: [fastapi, react, websocket, ux-feedback, gap-closure]

# Dependency graph
requires:
  - phase: 05-local-file-ingest-history-ui-3-pane-layout
    provides: ActiveJobCard WS lifecycle + orchestrator stage_changed event stream
provides:
  - "Additive stage_changed(preparing) WS event emitted before _load_stt_adapter on the production path"
  - "ActiveJobCard indeterminate Preparing... state during model load + first-chunk wait"
  - "Determinate Transcribing... X% bar only after the first progress event (never reverts to Preparing)"
affects: [05-local-file-ingest-history-ui-3-pane-layout, verifier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "WS-only transient stage event (preparing) not persisted to DB or StageNameLiteral -- mirrors the existing transcribing stage_changed emission (also WS-only until transcribed)"
    - "progressArrived ref gates the determinate bar; sticks once set so a late stage_changed frame cannot revert the UI to Preparing"
    - "Indeterminate CSS keyframe bar (.fill.indeterminate) reuses the existing .progress-bar .fill selector with a modifier class -- no new component, no new polling/timer"

key-files:
  created:
    - web/src/components/ActiveJobCard.test.tsx
  modified:
    - app/jobs/orchestrator.py
    - tests/test_orchestrator.py
    - web/src/components/ActiveJobCard.tsx
    - web/src/styles.css

key-decisions:
  - "preparing is WS-only and additive: no update_stage call, NOT added to StageNameLiteral -- the DB stage stays at the pre-transcribe value (e.g. ingested/ingesting) so stage_to_status and the manifest-DB projection invariant are untouched"
  - "stage_changed(transcribing) moved to AFTER adapter load so the FE determinate bar only appears once the model is ready; the preparing event covers the silent model-load + first-chunk wait"
  - "Test path (caller-provided adapter) skips the preparing event entirely -- existing orchestrator tests see the same transcribing event stream as before (no regression)"
  - "isPreparing covers BOTH the BE-emitted preparing stage AND transcribing-before-first-progress (first-chunk wait after model load) -- one indeterminate state for the whole silent window"
  - "progressArrived is a ref (no re-render on write); it sticks once set so a late stage_changed(transcribing) after progress cannot revert the UI to Preparing"
  - "Indeterminate bar implemented as a .fill.indeterminate CSS keyframe (rightward-moving 25% stripe) reusing the existing .progress-bar .fill selector -- one rule + one keyframe added to styles.css"

patterns-established:
  - "WS-only transient stage hint: emit _publish({type:stage_changed, stage:X}) without update_stage for display-only feedback that must not perturb the DB state machine"

requirements-completed: [UI-01, INGEST-01]

# Metrics
duration: 11min
completed: 2026-06-26
---

# Phase 5 Plan 05: Preparing... state during STT model load Summary

**Additive stage_changed(preparing) WS event before _load_stt_adapter (production path) + ActiveJobCard indeterminate Preparing... state until the first progress event closes UAT test-4 gap B -- the user no longer sees a stalled "Transcribing... 0%" bar during the silent model-load + first-chunk window.**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-26T10:09:44Z
- **Completed:** 2026-06-26T10:20:14Z
- **Tasks:** 2
- **Files modified:** 4 (2 modified + 1 test file created + 1 CSS rule)

## Accomplishments
- Back-end: the orchestrator's transcribing block now emits `stage_changed(preparing)` BEFORE `_load_stt_adapter` on the production path (adapter is None) and moves `stage_changed(transcribing)` to AFTER the adapter resolves. The test path (caller-provided adapter) skips the preparing event entirely -- existing orchestrator tests are unchanged.
- The preparing event is WS-only: no `update_stage` call, NOT added to `StageNameLiteral`. The DB stage stays at the pre-transcribe value so `stage_to_status` and the manifest-DB projection invariant are untouched.
- Front-end: ActiveJobCard tracks a `progressArrived` ref that sticks once the first progress event arrives. `isPreparing = (status === "preparing") || (status === "transcribing" && !progressArrived.current)` covers both the model-load window and the first-chunk wait. The card shows "Preparing..." with an indeterminate CSS keyframe bar until the first progress event, then switches to the determinate "Transcribing... X%" bar and never reverts.
- CSS: one new `.fill.indeterminate` rule + one `@keyframes indeterminate-slide` (rightward-moving 25% stripe) reusing the existing `.progress-bar .fill` selector.
- TDD: RED + GREEN commits for both tasks; full back-end suite 282 passed (280 + 2 new), vitest 27 passed (22 + 5 new), tsc clean, vite build ok.

## Task Commits

Each task was committed atomically (TDD: RED test -> GREEN implementation):

1. **Task 1: Emit additive stage_changed(preparing) before _load_stt_adapter**
   - `b896f51` (test) - add failing preparing->transcribing ordering test + test-path guard test
   - `9d5687c` (feat) - orchestrator restructure: preparing before load, transcribing after load
2. **Task 2: ActiveJobCard indeterminate Preparing... state until first progress**
   - `d9eca51` (test) - add failing ActiveJobCard preparing-state tests (4 cases + terminal smoke)
   - `9640b7b` (feat) - progressArrived ref + isPreparing + indeterminate bar + data-preparing + CSS keyframe

**Plan metadata:** pending (final docs commit below)

## Files Created/Modified
- `app/jobs/orchestrator.py` - transcribing block restructured: preparing event before _load_stt_adapter (production path), transcribing event after adapter resolves
- `tests/test_orchestrator.py` - test_preparing_event_emitted_before_transcribing_on_production_path + test_preparing_event_not_emitted_on_test_path
- `web/src/components/ActiveJobCard.tsx` - progressArrived ref (sticks on first progress, resets on jobId change); isPreparing boolean; indeterminate bar branch; Preparing... label guard; data-preparing attribute
- `web/src/components/ActiveJobCard.test.tsx` - 5 vitest cases (preparing label, stays preparing on transcribing-before-progress, switches to determinate on first progress, no-revert on late stage_changed, terminal done smoke)
- `web/src/styles.css` - .fill.indeterminate rule + @keyframes indeterminate-slide

## Decisions Made
- preparing is WS-only and additive -- no DB write, no StageNameLiteral entry. This mirrors the existing transcribing stage_changed emission (also WS-only until transcribed) and preserves the stage_to_status mapping + manifest-DB projection invariant.
- The test path (caller-provided adapter) deliberately skips the preparing event so every existing orchestrator test that passes a FakeAdapter sees the same event stream as before. The guard test (test_preparing_event_not_emitted_on_test_path) pins this contract explicitly.
- isPreparing covers BOTH the BE-emitted preparing stage AND the transcribing-before-first-progress window. One indeterminate state for the whole silent window -- the user gets immediate feedback the moment the BE emits preparing, and the card stays indeterminate through the first-chunk wait even after the BE emits transcribing.
- progressArrived is a ref (no re-render on write); it sticks once set so a late stage_changed(transcribing) frame after progress cannot revert the UI to Preparing. Reset on jobId change mirrors the ws.ts hook's own reset.
- Indeterminate bar: a .fill.indeterminate CSS keyframe (rightward-moving 25% stripe) was chosen over a static 100%-width/0.4-opacity fill because the moving stripe gives clearer "something is happening" feedback. Reuses the existing .progress-bar .fill selector with a modifier class -- no new component, no new polling/timer (T-05-05-02 DoS accept: no new render loop).

## Deviations from Plan

None - plan executed exactly as written. The plan's action section referenced "Preparing..." (three dots) and "Preparing..." (ellipsis) interchangeably; three dots were chosen for consistency with the existing "Transcribing..." / "Ingesting File..." labels. The plan's "add the class to web/src/styles.css if a matching rule is needed" branch was taken (the design system had no indeterminate class), adding one rule + one keyframe.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Gap B (stalled feedback between upload completion and history appearance) is closed end-to-end. A re-run of UAT test 4 should show "Preparing..." during the model-load + first-chunk window instead of a stalled "Transcribing... 0%" bar.
- Combined with 05-04 (gap A: original_filename), both UAT test-4 gaps are now closed. The noted enhancement (history row time + date) remains out of scope per the UAT file.
- Manual spot-check (post-execution, optional): drop a large file via the UI and confirm the active card shows "Preparing..." with a moving indeterminate bar before the first progress event, then switches to "Transcribing... X%" once chunk progress arrives.
- Files outside this plan's scope (05-04's original_filename work) were not re-touched.

## Known Stubs
None - the Preparing... state is fully wired to the BE-emitted preparing event and the FE progressArrived gate; no placeholder data.

## Threat Flags
None - the new preparing event is WS-only and display-only (T-05-05-01 accept: no DB/manifest write). No new network endpoints, auth paths, or trust-boundary schema changes beyond the existing stage_changed emission pattern.

## Self-Check: PASSED

- Created files verified present on disk:
  - FOUND: web/src/components/ActiveJobCard.test.tsx
  - FOUND: .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-05-SUMMARY.md
- Modified files verified present on disk:
  - FOUND: app/jobs/orchestrator.py
  - FOUND: tests/test_orchestrator.py
  - FOUND: web/src/components/ActiveJobCard.tsx
  - FOUND: web/src/styles.css
- Task commits verified in git log:
  - FOUND: b896f51 (test 05-05 Task 1 RED)
  - FOUND: 9d5687c (feat 05-05 Task 1 GREEN)
  - FOUND: d9eca51 (test 05-05 Task 2 RED)
  - FOUND: 9640b7b (feat 05-05 Task 2 GREEN)

---
*Phase: 05-local-file-ingest-history-ui-3-pane-layout*
*Completed: 2026-06-26*