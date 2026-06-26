---
status: testing
phase: 05-local-file-ingest-history-ui-3-pane-layout
source: [05-VERIFICATION.md]
started: 2026-06-25T04:23:43Z
updated: 2026-06-26T12:45:00Z
---

## Current Test

number: 5
name: Re-run UAT test 4 live to confirm gap-closure fixes 05-04 + 05-05
expected: |
  Drop a named multi-gigabyte file via the drop zone in a browser with the back-end +
  Vite dev server running. Watch the active card through model load + first chunk
  progress. On completion, check the history row's filename. Click the row to open the
  detail view.
    - (Gap B closed) Active card shows "Preparing..." with an indeterminate moving-stripe
      bar during STT model JIT-load + first-chunk wait — NOT a stalled "Transcribing... 0%".
    - (Gap B closed) On first chunk progress the card switches to "Transcribing... X%"
      with a determinate fill bar that does not revert to Preparing.
    - (Gap A closed) On completion the card fades, the job appears in history with the
      DROPPED FILENAME (e.g. "my great video.mp4"), NOT "source.mp4".
    - (SC-3) Clicking the row navigates to /jobs/:id and loads transcript + summary panes.
    - (UI-02) No embedded video player anywhere in the detail view.
awaiting: user response

## Tests

### 1. Drag-and-drop upload percent bar (D-02 live)
expected: Drag a real multi-gigabyte video file onto the drop zone in a browser with the back-end + Vite dev server running. The upload percent bar climbs 0 -> 100 smoothly (real xhr.upload.onprogress); the ActiveJobCard appears with WS-driven status; on completion the card fades out and the job appears in the history list.
result: pass
note: |
  Originally reported as an issue (overlay swallowed the drop); fixed in commit 844dbb5
  (overlay given its own onDrop calling handleFiles). Re-verified live in browser on
  2026-06-25 -- ActiveJobCard appeared, upload percent climbed 0->100 via real
  xhr.upload.onprogress, card faded out on completion, job landed in history list.

### 2. Scroll-spy visual highlight (UI-03)
expected: Open a completed job's detail view and scroll the transcript pane. The segment row nearest the vertical center gets the 4px #2563EB left border + rgba(37,99,235,0.05) tint; scrolling moves the highlight to the new nearest row.
result: pass

### 3. 2-pane detail visual proportions + no media player (UI-02)
expected: Open /jobs/:id in a browser. Transcript pane (left, 60%) and summary pane (right, 40%) visible at the correct proportions; summary shows the D-08 placeholder copy ("Summaries will appear here once summarization is enabled"); no embedded media player UI anywhere.
result: pass

### 4. End-to-end vertical slice in a running browser
expected: Drop file -> watch upload percent -> active card lifecycle -> terminal WS -> history refetch -> click row -> detail loads transcript with scroll-spy highlight. The full vertical slice works against a running back-end + Vite dev server.
result: resolved
reported: "it works in general but i dont know when it will appear in history. i thougth nothing was going on then some transcriptions appear. they are all named differently then as opposed to what i dropped in. Also i would appreciate time as well as a date in history row. Now i dont know if this is in the scope of this test, just something to let you know"
severity: minor
note: |
  The vertical-slice mechanics work end-to-end (upload % -> active card -> terminal WS ->
  history refetch -> detail with scroll-spy). Three user observations; two were logged as
  gaps below and are NOW CLOSED in code by gap-closure plans 05-04 + 05-05 (executed
  2026-06-26); one is an out-of-scope enhancement:
  - (A) Naming: history rows showed `source.<ext>`, not the dropped filename -> GAP CLOSED
    by 05-04 (original_filename persisted end-to-end). See gap entry below.
  - (B) Feedback: between upload completion and history appearance the card looked stalled
    ("thought nothing was going on") -> GAP CLOSED by 05-05 (additive stage_changed(preparing)
    + indeterminate Preparing bar). See gap entry below.
  - (C) Enhancement: history row shows date only; user would like time + date. NOT a gap --
    the test's expected behavior ("creation date") is met; polish request, out of scope for
    the phase-05 contract. Recorded below for a future polish pass, not fed to plan-phase.
  Live re-test of the two closures is promoted to test 5 below (the perceptual model-load
  feel + visible dropped filename cannot be asserted in jsdom).

### 5. Gap-closure re-test (05-04 + 05-05) in a running browser
expected: |
  Drop a named multi-gigabyte file -> active card shows "Preparing..." with an indeterminate
  moving-stripe bar during model load (gap B closed) -> on first chunk progress the card
  switches to "Transcribing... X%" determinate bar that does not revert -> on completion the
  card fades, the job appears in history AND the history row shows the dropped filename
  (e.g. "my great video.mp4"), not "source.mp4" (gap A closed) -> click the row -> detail
  loads transcript + summary panes with no embedded video player.
result: pending
note: |
  Code-level closure fully verified by tests (test_original_filename.py round-trip,
  test_orchestrator.py preparing->transcribing ordering, HistoryRow.test.tsx 3 cases,
  ActiveJobCard.test.tsx 5 cases). All 282 back-end + 27 FE tests green, tsc clean, vite
  build ok. This human re-test is the final live-browser confirmation that the closures
  resolve the original user-reported findings from test 4.

## Summary

total: 5
passed: 3
issues: 0
pending: 1
skipped: 0
blocked: 0
resolved: 1

## Gaps

- truth: "History row shows the original filename the user dropped"
  status: resolved
  resolved_by: "05-04 (gap-closure plan, executed 2026-06-26)"
  reason: "User reported: they are all named differently then as opposed to what i dropped in"
  severity: minor
  test: 4
  root_cause: >
    Back-end upload route (app/api/routes_jobs.py:182-206) writes the uploaded file to
    data/jobs/<id>/source.<ext> and sets manifest.source_path to that generated path. The
    original X-Filename header is used ONLY for extension validation and is never persisted.
    JobManifest (app/jobs/manifest.py) has no original_filename field. HistoryRow.tsx:35
    renders basename(job.source_path), so every completed row displays "source.<ext>"
    regardless of the dropped file's real name -- which is why the user saw names that did
    not match what they dropped.
  closure: >
    CLOSED by 05-04: migrations/0009_add_original_filename.sql adds nullable TEXT column;
    app/models/manifest.py + app/models/job.py carry the field + projection; app/api/routes_jobs.py
    persists X-Filename to manifest + DB BEFORE enqueue; app/jobs/manifest.py re-projects on every
    update_stage (H3+H4 invariant preserved); app/jobs/service.py SELECTs widened; web/src/api/types.ts
    JobResponse/JobManifest carry original_filename; web/src/components/HistoryRow.tsx renders
    original_filename ?? basename(source_path) ?? "unknown". Tests: tests/test_original_filename.py
    (2) + web/src/components/HistoryRow.test.tsx (3). Live re-test promoted to test 5.
  artifacts:
    - path: "app/api/routes_jobs.py"
      issue: "X-Filename header discarded after ext validation; source_path forced to <job_dir>/source.<ext>"
    - path: "app/jobs/manifest.py"
      issue: "JobManifest has no original_filename field; not persisted nor exposed on JobResponse"
    - path: "web/src/components/HistoryRow.tsx"
      issue: "Displays basename(source_path) instead of the original uploaded filename"
  missing:
    - "Add original_filename field to JobManifest + the jobs DB schema + JobResponse"
    - "Persist X-Filename in the /jobs/upload route"
    - "HistoryRow: display original_filename, fallback to basename(source_path)"

- truth: "User sees clear feedback that transcription is in progress between upload completion and the job appearing in history"
  status: resolved
  resolved_by: "05-05 (gap-closure plan, executed 2026-06-26)"
  reason: "User reported: i dont know when it will appear in history. i thougth nothing was going on then some transcriptions appear"
  severity: minor
  test: 4
  root_cause: >
    After upload completes, DropZone mounts an ActiveJobCard that subscribes to the job's
    WS event stream. The orchestrator (app/jobs/orchestrator.py:236-266) emits
    stage_changed(transcribing) then runs _load_stt_adapter (JIT model load) BEFORE the
    first chunk progress callback. During model load + first-chunk wait the card renders
    "Transcribing... 0%" with a 0% progress bar (ActiveJobCard.tsx:107,151-158) and no
    "preparing / loading model" indication. For a multi-GB video this wait is long, so the
    card looks stalled -- the user perceives "nothing going on" until progress events
    finally arrive and the job later lands in history.
  closure: >
    CLOSED by 05-05: app/jobs/orchestrator.py emits additive WS-only stage_changed(preparing)
    BEFORE _load_stt_adapter on the production path (test path unchanged); stage_changed(transcribing)
    moved to AFTER adapter load; preparing is WS-only (NOT in StageNameLiteral, no update_stage --
    DB invariant untouched). web/src/components/ActiveJobCard.tsx: progressArrived ref sticks on
    first progress event; isPreparing covers status=preparing OR (transcribing && !progressArrived);
    renders "Preparing..." + indeterminate bar until first progress, then determinate "Transcribing... X%"
    that never reverts; data-preparing attr for tests. web/src/styles.css: .fill.indeterminate +
    @keyframes indeterminate-slide. Tests: tests/test_orchestrator.py (2 new) + ActiveJobCard.test.tsx (5).
    Live re-test promoted to test 5.
  artifacts:
    - path: "web/src/components/ActiveJobCard.tsx"
      issue: "No indeterminate 'Loading model… / Preparing…' state; a 0% transcribing bar reads as stalled"
    - path: "app/jobs/orchestrator.py"
      issue: "No 'model_loading' stage event emitted before _load_stt_adapter / first progress callback"
  missing:
    - "Emit a model_loading / preparing stage event before _load_stt_adapter"
    - "ActiveJobCard: show an indeterminate 'Preparing…' state until the first progress event arrives"

## Noted Enhancements (out of scope -- not gaps)

- "History row should show time as well as date." HistoryRow.tsx formatDate() uses
  toLocaleDateString() (date only). The phase-05 contract only required a creation date,
  which is met. This is a polish request for a future pass; deliberately NOT fed to
  /gsd-plan-phase --gaps.

## Code Review Advisory (05-REVIEW.md, non-blocking)

The post-gap-closure code review found 0 critical / 3 warnings / 4 info. The 3 warnings
(WR-01/02/03) are all FE WS-reconnect-path edge cases (snapshot not fully treated as a
progress signal); they do not block any phase must-have or success criterion and are
appropriate for a future polish pass. The 4 info findings are minor cleanup. See
05-REVIEW.md for full detail; `/gsd-code-review 05 --fix` to auto-apply if desired.