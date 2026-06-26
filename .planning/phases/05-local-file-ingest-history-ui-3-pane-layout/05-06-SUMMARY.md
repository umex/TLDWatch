---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 06
subsystem: frontend
tags: [gap-closure, race-condition, preparing-state, ws-only, fe-only]
requires: [05-05]
provides: [snapshot-authoritative-state-derivation, race-branch-tests]
affects: [web/src/components/ActiveJobCard.tsx, web/src/components/ActiveJobCard.test.tsx]
tech-stack:
  added: []
  patterns: [snapshot-authoritative state derivation, progressArrived-driven transcribing detection]
key-files:
  created: []
  modified:
    - web/src/components/ActiveJobCard.tsx
    - web/src/components/ActiveJobCard.test.tsx
decisions:
  - "FE-only interpretation of snapshot status:'starting' as preparing (no BE change) preserves the 05-05 WS-only preparing invariant"
  - "progressArrived ref is the authoritative signal for the Transcribing label (decouples from status === 'transcribing' which a late-connecting card misses)"
metrics:
  duration: 2m
  completed: 2026-06-26T14:37:00Z
  tasks: 1
  files: 2
---

# Phase 05 Plan 06: Race-Condition Branches (Snapshot-Authoritative Preparing + Transcribing) Summary

Made the ActiveJobCard snapshot authoritative for the preparing + transcribing race branches so a late-connecting card shows accurate progress feedback without any back-end change (preserving the 05-05 WS-only preparing invariant).

## What Was Built

**Problem (UAT 05 test 5 entry 4 — MAJOR race):** A card that subscribes AFTER `stage_changed(preparing)` (and even after `stage_changed(transcribing)`) was broadcast receives `snapshot{status:"starting", stage:null}` because `preparing` is WS-only (never persisted to DB/manifest per 05-05 H3+H4 invariant). The connect snapshot (routes_ws.py:167-188) is sourced from `job.status` + `manifest.current_stage` + `progress.json` — none of which carry `preparing`. Today `isQueued` matched `"starting"` (ActiveJobCard.tsx:107-110), so the snapshot rendered "In Queue" with NO bar — the user saw "nothing is going on" for the entire model-load window AND the entire transcription when the card connected late.

**Fix (FE-only):** Make the snapshot authoritative for current state on the FE. No back-end file touched.

`web/src/components/ActiveJobCard.tsx` — four targeted edits + label branch update:

1. **`isQueued`** — removed `status === "starting"`. A starting snapshot no longer renders "In Queue".
2. **`isTranscribingActive`** (new boolean, declared after `progressArrived` + terminal defs) — `progressArrived.current && !isQueued && !isIngesting && !isDone && !isFailed && !isCancelled`. True when progress events are flowing and the card is not queued/ingesting/terminal — i.e. effectively transcribing regardless of whether `stage_changed(transcribing)` was received (covers race branch b).
3. **`isPreparing`** — `(status === "preparing" || status === "starting" || (isTranscribing && !progressArrived.current)) && !isTranscribingActive`. The `status === "starting"` branch covers the late-connecting card (race branch a); the `!isTranscribingActive` guard ensures the card switches to the Transcribing label once progress events flow (race branch b).
4. **`showBar`** — `isIngesting || isTranscribing || isPreparing || isTranscribingActive`. **`showIndeterminateBar`** — `isPreparing && !isIngesting && !progressArrived.current` (suppresses indeterminate once progress has arrived; the existing JSX ternary already renders the determinate fill when `!showIndeterminateBar`).
5. **Transcribing label** — guard changed from `isTranscribing && progressArrived.current` to `isTranscribingActive`. Shows the label when progress is flowing even if `status !== "transcribing"`.

`web/src/components/ActiveJobCard.test.tsx` — renamed describe to `plans 05-05 + 05-06`, added two race-branch tests:

- **(a)** `snapshot{status:"starting"}` + NO `stage_changed` → "Preparing..." + indeterminate bar (`data-preparing="true"`, no determinate `width` style).
- **(b)** `snapshot{status:"starting", percent:0}` + `progress{percent:45}` with NO `stage_changed(transcribing)` → "Transcribing... 45%" + determinate bar at 45% (`data-preparing="false"`, no "In Queue", no "Preparing...").

## TDD Gate Compliance

RED gate: `abfdd78` — `test(05-06): add failing tests for race-condition branches (a) + (b)` (2 new tests fail, 5 existing pass — RED confirmed before any implementation).

GREEN gate: `ab049fa` — `feat(05-06): snapshot-authoritative preparing + transcribing race branches` (all 7 ActiveJobCard tests pass).

No REFACTOR commit — the implementation is minimal and clean.

## Verification

| Check | Result |
|-------|--------|
| `npx --prefix web vitest run ActiveJobCard.test.tsx` | 7/7 pass (5 existing 05-05 + 2 new 05-06) |
| `npx --prefix web vitest run` (full FE suite) | 29/29 pass (27 existing + 2 new) |
| `npx --prefix web tsc --noEmit` | clean |
| `npm --prefix web run build` | ok (537.57 kB bundle) |
| `grep -c 'isTranscribingActive'` in ActiveJobCard.tsx | >= 1 (present) |
| `status === "starting"` in isQueued | 0 (removed) |
| `status === "starting"` in isPreparing | >= 1 (added) |
| `git diff HEAD~2 HEAD -- app/` | empty (no back-end files touched — 05-05 WS-only preparing invariant preserved) |

## Deviations from Plan

None — plan executed exactly as written. All four targeted edits + label branch update applied verbatim; both new tests added inside the renamed describe block using the existing `renderCard`/`waitForSocket`/`fire` helpers; `MockWS.instances` cleanup left to the existing setup.ts `afterEach` (no second cleanup added).

## Known Stubs

None. The snapshot + progress events drive real rendering end-to-end.

## Threat Flags

None. The threat model's three accepted dispositions (T-05-06-01..03) all hold: pure FE display re-derivation, no new trust boundary, no new field read (status + percent were already rendered by 05-02b/05-05).

## Commits

- `abfdd78` — test(05-06): add failing tests for race-condition branches (a) + (b)
- `ab049fa` — feat(05-06): snapshot-authoritative preparing + transcribing race branches
## Self-Check: PASSED

- SUMMARY.md: FOUND
- abfdd78 (RED): FOUND
- ab049fa (GREEN): FOUND
