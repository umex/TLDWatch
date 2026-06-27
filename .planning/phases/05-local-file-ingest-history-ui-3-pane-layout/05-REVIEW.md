---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 08
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - web/src/components/ActiveJobCard.tsx
  - web/src/components/ActiveJobCard.test.tsx
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 05 Plan 08: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 2 (web/src/components/ActiveJobCard.tsx, web/src/components/ActiveJobCard.test.tsx)
**Status:** issues_found

## Summary

Plan 05-08 is a FE-only gap-closure that makes `ActiveJobCard` snapshot-authoritative for the live DB `status:"ingesting"` window (model-load + transcribe), closing UAT test-6. The five targeted edits are implemented exactly as the plan prescribes (snapshot handler seeds `progressArrived.current` from `snapshot.percent > 0` + an `event.stage === "transcribed" | "done"` fallback; `isTranscribingActive` drops the `!isIngesting` gate; `isPreparing` adds the `status === "ingesting"` branch; `showIndeterminateBar` drops `!isIngesting`; the label render is reordered with `!isPreparing && !isTranscribingActive` guarding the "Ingesting File..." label). The three new race-branch tests (a/b/c) assert the plan's `<behavior>` contract faithfully, and the 7 prior 05-05/05-06 tests remain meaningful (they drive the `queued`/`starting` paths that are independent of the new `ingesting` branch).

No correctness or security defects were found. The change stays within the plan's threat-model boundary (display-only reinterpretation of already-trusted snapshot fields `status`/`percent`/`stage`; no new untrusted input read; no BE files touched; the rejected Option B is correctly absent). The findings below are maintainability/robustness items: two stale comments that now misdescribe the code, and three minor observations about effectively-dead branches and a reconnect-ETA limitation that the plan does not cover.

The `!isIngesting` removal was traced for regressions across prior statuses (`queued`/`done`/`failed`/`cancelled`): `isTranscribingActive` is still gated by `!isQueued && !isDone && !isFailed && !isCancelled`, so no prior/terminal status can flip to the Transcribing label. The `event.stage === "transcribed" | "done"` fallback was traced against the orchestrator/manifest flow (`update_stage("transcribed")` atomically flips status to `transcribing`; `update_stage("done")` atomically flips status to `done`): under the documented BE invariant, `stage:"done"` never coincides with `status:"ingesting"`, so the fallback cannot mis-seed `progressArrived` for an in-flight `ingesting` card.

## Warnings

### WR-01: Stale comment on `isTranscribingActive` contradicts the 05-08 code

**File:** `web/src/components/ActiveJobCard.tsx:128-135`
**Issue:** The comment block above `isTranscribingActive` still reads, in part: _"Gated by !isQueued/!isIngesting/!terminal so it never fires for queued/ingesting/terminal cards."_ and _"status may still be \"starting\" ... so the snapshot carries status:\"starting\" through the model-load window AND the first-chunk wait."_ After 05-08, the `!isIngesting` gate was deliberately removed (the whole point of this plan) so the Transcribing label DOES fire for `ingesting` cards once progress arrives; and 05-08's premise (debug session `active-card-silence.md`) is that the snapshot carries `status:"ingesting"`, not `"starting"`, through that window. A future maintainer reading this comment would believe `!isIngesting` is still present and could "restore" a non-existent gate or mis-diagnose a future race. The comment actively contradicts the code.
**Fix:**
```tsx
// 05-06 race branch b + 05-08 ingesting window: a late-connecting card
// that missed stage_changed(transcribing) but is receiving progress
// events is effectively transcribing. progressArrived is the
// authoritative signal (progress events are flowing) -- for local
// ingest the DB status is "ingesting" for the ENTIRE model-load +
// transcribe window (the WS-only stage_changed(preparing|transcribing)
// events at orchestrator.py:260/:263 are NOT persisted, so the snapshot
// status never becomes "preparing"/"transcribing"). Gated by
// !isQueued/!isDone/!isFailed/!isCancelled so queued/terminal cards never
// flip to transcribing.
const isTranscribingActive =
  progressArrived.current &&
  !isQueued &&
  !isDone &&
  !isFailed &&
  !isCancelled
```

### WR-02: Stale comment on `isPreparing` omits the 05-08 `ingesting` branch

**File:** `web/src/components/ActiveJobCard.tsx:142-147`
**Issue:** The comment above `isPreparing` describes it as covering _"the BE-emitted preparing stage (model load window), the transcribing-before-first-progress window, AND the late-connecting card (snapshot status:\"starting\", missed stage_changed(preparing))"_ and _"even if status is still \"starting\" (race branch b)"_. It does not mention the new `status === "ingesting"` branch that 05-08 adds, which is the primary late-connect case now that the `starting` branch is recognized as defensive-only (the live runtime sends `ingesting`). The comment makes the new branch look like an accident rather than the load-bearing 05-08 fix.
**Fix:** Update the comment to call out the `ingesting` branch as the 05-08 late-connect case and note that `starting` is retained only as a defensive fallback for the (now-refuted) 05-06 premise:
```tsx
// 05-05 gap B + 05-06 race branch a + 05-08 ingesting window: covers the
// BE-emitted preparing stage (model load window), the
// transcribing-before-first-progress window, AND the late-connecting
// card whose snapshot carries status:"ingesting" (the live DB status for
// the whole model-load + transcribe window -- 05-08) or, defensively,
// status:"starting" (05-06's original premise, retained as a fallback).
// Gated by !isTranscribingActive so once progress events flow the card
// switches to the Transcribing label even if status is still
// "ingesting"/"starting" (race branch b).
```

## Info

### IN-01: `event.stage === "done"` fallback is effectively dead under the BE invariant

**File:** `web/src/components/ActiveJobCard.tsx:75`
**Issue:** The snapshot handler seeds `progressArrived.current = true` when `event.stage === "done"`. Per the orchestrator/manifest flow documented in the plan, `update_stage("done")` (`orchestrator.py:299`) atomically sets both `manifest.current_stage = "done"` and `job.status = stage_to_status("done") = "done"`. So a snapshot can carry `stage:"done"` only when `status:"done"`, in which case `isDone` already gates `isTranscribingActive`/`isPreparing` and the `progressArrived` seeding has no observable effect. The `"transcribed"` fallback (line 74) is the load-bearing one (it coincides with `status:"transcribing"` where the seeding is meaningful); the `"done"` arm is redundant. Not a bug -- it is a harmless defensive fallback against a hypothetical BE inconsistency -- but worth a comment so a future reader does not assume it is load-bearing.
**Fix:** Either drop the `event.stage === "done"` arm, or add a trailing comment: `// "done" is redundant (status:"done" already gates via isDone) but defensive against a BE inconsistency.`

### IN-02: "Ingesting File..." label branch is now unreachable for local ingest

**File:** `web/src/components/ActiveJobCard.tsx:191-193`
**Issue:** The label `{isIngesting && !isPreparing && !isTranscribingActive && (<span>Ingesting File... {percent}%</span>)}` can no longer render for any local-ingest snapshot. When `status === "ingesting"` and `!progressArrived.current`, `isPreparing` is `true` (via the new `status === "ingesting"` branch), so the `!isPreparing` guard fails; when `progressArrived.current` is `true`, `isTranscribingActive` is `true` (since `isIngesting` implies none of queued/done/failed/cancelled), so the `!isTranscribingActive` guard fails. The plan explicitly accepts this ("dead for the local-ingest post-snapshot window"), so it is intentional, not a defect. Suggest a one-line comment so the dead branch is not "fixed" back into life by a future maintainer who reads the render in isolation.
**Fix:**
```tsx
{/* 05-08: dead for local ingest post-snapshot -- isPreparing (no
    progress) or isTranscribingActive (progress flowing) always wins for
    status:"ingesting". Retained for a future non-local-ingest path that
    does not exist yet. */}
{isIngesting && !isPreparing && !isTranscribingActive && (
  <span>Ingesting File... {percent}%</span>
)}
```

### IN-03: ETA label suppressed on reconnect mid-transcription (snapshot has no chunks field)

**File:** `web/src/components/ActiveJobCard.tsx:156-157` (etaLabel) + snapshot handler `:60-79`
**Issue:** Test (c) verifies that a reconnecting card (`snapshot{status:"ingesting", percent:45, eta:null}`) renders "Transcribing... 45%" with a determinate bar from the snapshot alone. The `JobEvent` snapshot type (`ws.ts:18`) carries `eta` but not `chunks_done`/`chunks_total`, so even when the BE ships a non-null `eta` on the snapshot, the `etaLabel` expression `eta !== null && chunks >= 2` is always false on reconnect (the `progress` case is the only writer of `chunks`). A reconnecting user therefore sees "Transcribing... 45%" without an ETA until the next live `progress` event arrives, even though the BE has enough data to display one. This is a minor UX limitation, not a correctness bug, and is out of the plan's stated scope (the plan only requires the determinate bar to render from the snapshot alone). Noting so it is a conscious decision rather than an oversight.
**Fix:** If the reconnect-ETA matters, either (a) extend the snapshot `JobEvent` type with a `chunks_done`/`chunks_total` pair and seed `chunks` in the snapshot handler, or (b) relax the `etaLabel` guard to `eta !== null` when `progressArrived.current` is true (the BE already gates ETA emission on `>=2` chunks server-side per Phase 4 D-09). Either is a follow-up, not a 05-08 deliverable.

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_