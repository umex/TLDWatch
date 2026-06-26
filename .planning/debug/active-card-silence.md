# Debug Session: Active card "nothing" after upload (Phase 5 UAT test 6)

- **UAT test:** 6 (gap-closure re-test of 05-06 + 05-07)
- **Opened:** 2026-06-26T16:47:00Z (user response)
- **Diagnosed:** 2026-06-26T17:30:00Z
- **Severity:** major
- **Symptom (user verbatim):** "after upload there was nothing untill video was transcribed and appeared in the history row."
- **Method:** 3-angle parallel diagnosis (stale-runtime, card-lifecycle, ws-snapshot-status) + adversarial verify + synthesis. 7 agents, 277k tokens.

## Verdict

REAL CODE GAP. Stale-runtime was refuted; card-lifecycle was refuted (the card mounts and does not unmount prematurely). The surviving, verified root cause is the WS-snapshot-status gap: **05-06's fix premises a snapshot status the live runtime never sends.**

## Root Cause

05-06 assumed a late-connecting card's WS connect snapshot carries `status:"starting"` during the model-load + first-chunk wait (`ActiveJobCard.tsx:116-119` comment). It does not. The DB status for the entire model-load + transcription window is `"ingesting"`:

- The only writer of DB `starting` is `queue.py:118` (pull_next claim), overwritten milliseconds later by `orchestrator.py:230-233` `update_stage("ingested")` → `stage_to_status("ingested") = "ingesting"` (`manifest.py:41,67-77`).
- `transcribed → transcribing` is persisted only at `orchestrator.py:290-297`, AFTER `transcript = await future` (`:282`) returns, immediately followed by `update_stage("done")` (`:299`). So `transcribing` is never the snapshot status *during* transcription.
- `stage_changed(preparing)` (`:260`) and `stage_changed(transcribing)` (`:263`) are **WS-only** — no `update_stage` (comment `:246-250`). A card connecting after they were emitted misses them; `routes_ws.py:186` sends `snapshot.status = job.status` (raw DB = `"ingesting"`).
- The DropZone race makes late-connect the **common** case: `onJobCreated` fires only when `upload.status==="done"` (`DropZone.tsx:84-87`), by which point the worker has usually already claimed the job and emitted the WS-only `stage_changed(preparing)`.

### FE consequence once the card receives `snapshot{status:"ingesting"}`

- `isIngesting = true` (`ActiveJobCard.tsx:108`).
- `isTranscribingActive` (`:121-127`) is gated by `!isIngesting` → `false`, even after progress events set `progressArrived.current` (the snapshot handler `:60-64` never sets `progressArrived`; only the `"progress"` case `:69` does, and `!isIngesting` blocks it anyway).
- `isPreparing`'s `status==="starting"` branch (`:136`) is dead code for this case.
- The card renders a frozen `"Ingesting File... 0%"` (model-load, no `progress.json`) / mislabeled `"Ingesting File... X%"` (mid-transcription, bar moves but label wrong) — perceived as "nothing is going on" until the job finishes and pops into history.

Reproduces with **fresh** servers + browser hard reload. Not operational.

## Evidence

- `orchestrator.py:260/263` WS-only `stage_changed(preparing|transcribing)`; comment `:246-250` confirms no DB write.
- `orchestrator.py:230-233` `update_stage("ingested")` overwrites transient `starting`.
- `orchestrator.py:290-297` `transcribed` persisted after `await future` (`:282`); `:299` → `done`.
- `manifest.py:39-44` `_STAGE_STATUS_MAP`: no stage → `starting`; no pre-transcribe stage → `transcribing`.
- `queue.py:116-128` only writer of DB `starting` (transient).
- `routes_ws.py:180-188` snapshot = raw `job.status` + `manifest.current_stage` + percent/eta; FE `:60-64` ignores `event.stage`, doesn't seed `progressArrived` from `snapshot.percent`.
- `ActiveJobCard.tsx:121-127` `isTranscribingActive` gated by `!isIngesting`; `:134-138` `isPreparing` `status==="starting"` dead for `ingesting`; `:116-119` false-premise comment.
- `DropZone.tsx:84-87` `onJobCreated` fires only on `upload.status==="done"` → late-connect is common.
- Stale-runtime refuted: Vite serves source on demand keyed by mtime (`ActiveJobCard.tsx` mtime 16:36, post-05-06); BE PID 20596 (started 14:43) includes 05-05's `stage_changed(preparing)` emit.

## Suggested Fix Direction

Treat the snapshot's `status:"ingesting"` as the preparing/transcribing signal for local ingest (local ingest is instant, so `ingesting` post-snapshot = waiting for model load / first chunk; progress events on top of `ingesting` = transcribing).

**Option A — FE-only (cheaper, mirrors 05-06 style):**
1. `ActiveJobCard.tsx` `isPreparing` also covers `status==="ingesting" && !progressArrived.current`.
2. `isTranscribingActive` also fires when `status==="ingesting" && progressArrived.current`.
3. Snapshot handler `:60-64` also consume `event.stage` + read `snapshot.percent` to seed `progressArrived` + drive the determinate bar immediately on reconnect.

**Option B — BE-persisted (more robust, heavier):**
- `orchestrator.py` around `:260/:263` persist a transient status to the DB alongside the WS-only `stage_changed` so late-connecting snapshots carry an unambiguous `transcribing`/`preparing` + percent. Requires extending `manifest.py` `_STAGE_STATUS_MAP` / `StageNameLiteral` — touches the H3+H4 invariant.

Either way the FE snapshot handler must stop ignoring `event.stage`.

## Tests to add

- (a) `snapshot{status:"ingesting", percent:0}` + NO `stage_changed` → "Preparing..." + indeterminate bar.
- (b) `snapshot{status:"ingesting", percent:0}` + `progress{percent:45}` (no `stage_changed(transcribing)`) → "Transcribing... 45%" + determinate bar.
- (c) `snapshot{status:"ingesting", percent:45}` (reconnect mid-transcription) → "Transcribing... 45%" + determinate bar from snapshot alone.

## Verification prerequisite (operational, not the fix)

Kill PID 20596 (BE, no `--reload`) + PID 32968 (Vite), restart both on current HEAD `2af8354`, hard-reload the browser, before re-running UAT test 6. Stale runtime was not the root cause, but fresh code is required to verify the fix.

## Hand-off

Root cause confirmed → `/gsd-plan-phase 5 --gaps` (or the verify-work gap-closure planner) to produce plan 05-08 closing this gap.