---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 08
subsystem: frontend
tags: [gap-closure, fe-only, tdd, race-condition, active-job-card, uat-test-6]
requires:
  - 05-05-PLAN (WS-only preparing + progressArrived ref)
  - 05-06-PLAN (snapshot-authoritative race-closure for status:"starting")
  - 05-04-PLAN (H3+H4 manifest projection invariant)
provides:
  - "ActiveJobCard snapshot-authoritative state derivation for the live DB status 'ingesting' window (model-load + transcribe)"
affects:
  - web/src/components/ActiveJobCard.tsx
  - web/src/components/ActiveJobCard.test.tsx
tech-stack:
  added: []
  patterns:
    - "Snapshot seeds progressArrived.current from snapshot.percent + event.stage fallback (reconnect mid-transcription shows determinate bar immediately)"
    - "status:'ingesting' reinterpreted as preparing (no progress) OR transcribing (progress flowing) for local ingest — FE-only, no DB change"
key-files:
  created: []
  modified:
    - web/src/components/ActiveJobCard.tsx
    - web/src/components/ActiveJobCard.test.tsx
decisions:
  - "Option A (FE-only reinterpretation of already-trusted snapshot fields) chosen over Option B (BE-persisted transient preparing/transcribing status). Option B would touch the 05-04 H3+H4 manifest projection invariant and the 05-05 WS-only preparing invariant for no additional user-visible benefit."
  - "isIngesting 'Ingesting File...' label is now dead for the local-ingest post-snapshot window (guarded by !isPreparing && !isTranscribingActive) — local ingest is instant, so 'ingesting' status post-snapshot means model-load/transcribe, not file ingestion."
metrics:
  duration: ~6min
  completed: 2026-06-27
  tasks: 1
  files: 2
  tests_added: 3
---

# Phase 05 Plan 08: Ingesting-Window ActiveJobCard Race-Closure Summary

Closed UAT test-6 gap (MAJOR; debug session `.planning/debug/active-card-silence.md`): 05-06's race-closure was built on a false premise. 05-06 assumed a late-connecting card's snapshot carries `status:"starting"` during the model-load + first-chunk wait; in the live runtime the DB status for the ENTIRE model-load + transcription window is `"ingesting"` (the WS-only `stage_changed(preparing|transcribing)` events at orchestrator.py:260/:263 are NOT persisted, and `transcribed` only lands AFTER `await future` returns). The card rendered a frozen `"Ingesting File... 0%"` / mislabeled `"Ingesting File... X%"` — perceived as "nothing is going on" until the job popped into history.

## What Was Built

Five targeted edits to `web/src/components/ActiveJobCard.tsx` (FE-only — `routes_ws.py`, `orchestrator.py`, `progress.py`, `manifest.py` untouched):

1. **Snapshot handler** now seeds `progressArrived.current` from `snapshot.percent > 0` (plus an `event.stage === "transcribed" | "done"` fallback) so a card reconnecting mid-transcription drives the determinate bar immediately without waiting for the next progress event.
2. **`isTranscribingActive`** drops the `!isIngesting` gate so `status:"ingesting" && progressArrived` fires the Transcribing label for a late-connecting card that missed `stage_changed(transcribing)`.
3. **`isPreparing`** adds `status === "ingesting"` so `status:"ingesting"` with no progress yet (the model-load window for a late-connecting card) shows `"Preparing..."` + indeterminate bar.
4. **`showIndeterminateBar`** drops the `!isIngesting` guard so the indeterminate preparing bar renders during the ingesting model-load window.
5. **Label render** reordered so `isPreparing` + `isTranscribingActive` take priority over the `"Ingesting File..."` label, which is now guarded by `!isPreparing && !isTranscribingActive` (dead for the local-ingest post-snapshot window).

Three new tests added to `web/src/components/ActiveJobCard.test.tsx` inside the renamed describe block `describe("ActiveJobCard preparing state (plans 05-05 + 05-06 + 05-08)", ...)`:

- **(a)** `shows Preparing... + indeterminate bar when snapshot status is ingesting and no stage_changed fires (05-08 race branch a)` — snapshot{ingesting,0} + nothing else.
- **(b)** `shows Transcribing...X% determinate bar when snapshot is ingesting and a progress event arrives with no stage_changed(transcribing) (05-08 race branch b)` — snapshot{ingesting,0} + progress{45}.
- **(c)** `shows Transcribing...X% determinate bar from snapshot alone when reconnecting mid-transcription (05-08 race branch c)` — snapshot{ingesting,45} alone.

## TDD Gate Compliance

- **RED gate:** `test(05-08):` commit `d12aa74` — three new tests added, observed failing (3 failed | 7 passed). RED confirmed before any implementation.
- **GREEN gate:** `feat(05-08):` commit `0e86ea3` — five edits applied, 10/10 tests pass (3 new + 7 existing).
- **REFACTOR gate:** not needed — no cleanup beyond the targeted edits.

## Verification

- `npx vitest run ActiveJobCard.test.tsx` — 10 passed (7 prior 05-05/05-06 + 3 new 05-08).
- `npx vitest run` (full FE suite) — 35 passed (32 prior + 3 new, no regression).
- `npx tsc --noEmit` — clean.
- `npm run build` — succeeded (537.67 kB bundle, 2.37s).
- `git diff --name-only HEAD~2 HEAD` lists ONLY `web/src/components/ActiveJobCard.tsx` + `web/src/components/ActiveJobCard.test.tsx` (no BE files touched).
- Grep guards: `status === "ingesting"` count = 2 (>=1); `progressArrived.current = true` count = 2 (>=2, one in snapshot seeding + one in progress case); `event.stage === "transcribed"` count = 1 (>=1); `!isIngesting` in isTranscribingActive/showIndeterminateBar = 0 (dropped).
- BE preparing scan: `grep -rn "preparing" app/jobs/orchestrator.py app/jobs/manifest.py app/api/routes_ws.py | grep -iv "stage_changed\|_publish\|#"` returns nothing — the 05-05 WS-only preparing invariant is preserved.

## Deviations from Plan

None - plan executed exactly as written. RED-first TDD order honored (test commit before implementation).

## Known Stubs

None — the snapshot.percent seeding drives real determinate bar width from the live progress.json value; no placeholder data.

## Threat Flags

None — the threat model in the plan (T-05-08-01..04) accepts all four dispositions. No new trust boundary crossed: `status` + `percent` + `stage` were already shipped by `routes_ws.py:180-188` and already rendered by 05-02b/05-05/05-06; the snapshot handler now consumes `event.stage` (already on the `JobEvent` snapshot type per `ws.ts:18`) as a fallback, which was merely ignored before. FE-only fix by construction.

## Self-Check: PASSED

- web/src/components/ActiveJobCard.tsx — FOUND (modified, 20 insertions / 4 deletions)
- web/src/components/ActiveJobCard.test.tsx — FOUND (modified, 91 insertions / 1 deletion)
- commit d12aa74 (RED) — FOUND
- commit 0e86ea3 (GREEN) — FOUND