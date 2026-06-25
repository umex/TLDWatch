---
status: diagnosed
phase: 05-local-file-ingest-history-ui-3-pane-layout
source: [05-VERIFICATION.md]
started: 2026-06-25T04:23:43Z
updated: 2026-06-25T07:30:00Z
---

## Current Test

[testing complete]

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
result: issue
reported: "it works in general but i dont know when it will appear in history. i thougth nothing was going on then some transcriptions appear. they are all named differently then as opposed to what i dropped in. Also i would appreciate time as well as a date in history row. Now i dont know if this is in the scope of this test, just something to let you know"
severity: minor
note: |
  The vertical-slice mechanics work end-to-end (upload % -> active card -> terminal WS ->
  history refetch -> detail with scroll-spy). Three user observations; two are logged as
  gaps below, one is an out-of-scope enhancement:
  - (A) Naming: history rows show `source.<ext>`, not the dropped filename -> GAP (test 4, gap 1).
  - (B) Feedback: between upload completion and history appearance the card looks stalled
    ("thought nothing was going on") -> GAP (test 4, gap 2).
  - (C) Enhancement: history row shows date only; user would like time + date. NOT a gap --
    the test's expected behavior ("creation date") is met; this is a polish request, out of
    scope for the phase-05 contract. Recorded here for a future polish pass, not fed to
    plan-phase --gaps.

## Summary

total: 4
passed: 3
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "History row shows the original filename the user dropped"
  status: failed
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
  status: failed
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