---
status: testing
phase: 05-local-file-ingest-history-ui-3-pane-layout
source: [05-VERIFICATION.md]
started: 2026-06-25T04:23:43Z
updated: 2026-06-25T06:25:00Z
---

## Current Test

number: 1
name: Drag-and-drop upload percent bar (D-02 live)
expected: |
  Drag a real multi-gigabyte video file onto the drop zone in a browser with the
  back-end (uvicorn app.main:app --port 8000) + Vite dev server (npm --prefix web run dev)
  running. The upload percent bar climbs 0 -> 100 smoothly (real xhr.upload.onprogress
  percent, not a static label); the ActiveJobCard appears with WS-driven status; on
  completion the card fades out and the job appears in the history list.
awaiting: user response

## Tests

### 1. Drag-and-drop upload percent bar (D-02 live)
expected: Drag a real multi-gigabyte video file onto the drop zone in a browser with the back-end + Vite dev server running. The upload percent bar climbs 0 -> 100 smoothly (real xhr.upload.onprogress); the ActiveJobCard appears with WS-driven status; on completion the card fades out and the job appears in the history list.
result: issue found + fixed (re-verify)
issue: Dragging a file showed the full-window drop overlay (D-01 ok), but dropping did nothing -- no ActiveJobCard, no upload started.
root cause: The overlay div is position:fixed inset:0 z-9999, so it is the actual drop target during any drag. Only the window-level onDrop fired, and it merely preventDefault + hid the overlay, discarding the files. The .drop-zone React onDrop (which calls handleFiles) was unreachable because the overlay sat on top of it.
fix: commit 844dbb5 -- gave the overlay div its own onDrop that calls handleFiles (same upload flow as .drop-zone); window onDrop keeps preventDefault + hide only (no double-handling). tsc clean, vitest 19/19.
re-verify: drop a file again -- expect ActiveJobCard + climbing 0->100 percent + terminal handoff to history.

### 2. Scroll-spy visual highlight (UI-03)
expected: Open a completed job's detail view and scroll the transcript pane. The segment row nearest the vertical center gets the 4px #2563EB left border + rgba(37,99,235,0.05) tint; scrolling moves the highlight to the new nearest row.
result: [pending]

### 3. 2-pane detail visual proportions + no media player (UI-02)
expected: Open /jobs/:id in a browser. Transcript pane (left, 60%) and summary pane (right, 40%) visible at the correct proportions; summary shows the D-08 placeholder copy ("Summaries will appear here once summarization is enabled"); no embedded media player UI anywhere.
result: [pending]

### 4. End-to-end vertical slice in a running browser
expected: Drop file -> watch upload percent -> active card lifecycle -> terminal WS -> history refetch -> click row -> detail loads transcript with scroll-spy highlight. The full vertical slice works against a running back-end + Vite dev server.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

None — all 18 plan must_haves and all 5 requirement IDs (INGEST-01, JOB-03, UI-01, UI-02, UI-03) are satisfied by automated verification (pytest 278, vitest 19, tsc clean, vite build ok; no `<video>`/`FormData`/`duplex`/`react-router-dom`). The 4 items above are perceptual/live-browser checks that cannot be asserted in jsdom.