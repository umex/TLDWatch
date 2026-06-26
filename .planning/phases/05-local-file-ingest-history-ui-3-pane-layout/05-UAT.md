---
status: diagnosed
phase: 05-local-file-ingest-history-ui-3-pane-layout
source: [05-VERIFICATION.md]
started: 2026-06-25T04:23:43Z
updated: 2026-06-26T13:53:30Z
---

## Current Test

[testing complete -- 2 gaps open for fresh-session gap-closure]

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
result: issue
reported: "the file was uploading, and when it was complete there seem to be some error showing up quickly and now nothing is happening, at least not that i would know"
severity: blocker
note: |
  Live re-test regressed: after upload completes an error flashes briefly in the UI, then
  the card goes silent with no visible Preparing/Transcribing state. Code-level closure
  (282 BE + 27 FE tests green) did not surface this — it is a live-runtime symptom only.
  Diagnosis pending the actual error text from the browser dev console + server terminal.

  DIAGNOSIS (2026-06-26T12:44Z): stale-runtime artifact, NOT a code defect.
  - Browser console error was React 18 StrictMode dev double-invoke noise: the first WS
    socket is torn down in disconnectPassiveEffect before it connects ("WebSocket is
    closed before the connection is established"); the second mount's socket is the real
    one. Stack: <ActiveJobCard> -> HistoryPage.tsx:36. Harmless on its own.
  - Root cause: the back-end process (PID 15584, started 2026-06-23 23:14) had been
    running for 3 days WITHOUT --reload and predated the 05-04/05-05 gap-closure commits.
    Proof: the live jobs?status=done JobResponse it served had NO original_filename field
    (05-04 added it; nulls ARE serialized, e.g. source_sha256:null, so absence = field not
    in the running model). With the stale back-end the orchestrator never emitted the new
    stage_changed(preparing) event (05-05), so the card had nothing to render -> silent.
  - FIX APPLIED: killed the stale back-end (PID 15584) + stale Vite (PID 7272) and
    restarted both with current code. Back-end now serves original_filename (verified:
    /jobs?status=failed returns "original_filename":null on old rows). data_dir resolved
    to the configured E:\Projects\TranscriptionAndNotes\data (settings.json data_dir
    field; data2 was a prior override the stale process held in memory).
  - Re-test promoted below: user re-drops a named file against the FRESH servers. If the
    card now shows Preparing + the history row shows the dropped filename, the closure is
    confirmed and this issue flips to resolved (root cause = stale runtime, fix = restart).

  RE-TEST ON FRESH SERVERS (2026-06-26T13:02Z, job f309cc13, file
  "Dead.Poets.Society.1989.1080p.BluRay.x264.YIFY.mp4"):
  - Gap A (original_filename): CONFIRMED LIVE. Direct GET /jobs/f309cc13 returns
    "original_filename":"Dead.Poets.Society.1989.1080p.BluRay.x264.YIFY.mp4". 05-04 persists
    the dropped filename end-to-end. (Live history-row render + click->detail + no-video
    still pending a completed job; the 2hr movie on CPU is impractical -- switching to a
    short clip to finish the lifecycle.)
  - WS endpoint: CONFIRMED WORKING. A direct websockets probe connected to
    /ws/jobs/f309cc13/events and received a snapshot. The browser console
    "WebSocket closed before established" error is React 18 StrictMode dev double-invoke
    noise (first socket torn down in disconnectPassiveEffect; second-mount socket connects).
  - Gap B part 2 (Transcribing...X% determinate bar): NOT OBSERVED LIVE. User correction:
    they never saw A/B/C -- the active card showed NO recognizable progress state. This is
    consistent with the race gap (see below) being broader than just Preparing: when the
    card connects after BOTH stage_changed(preparing) AND stage_changed(transcribing) were
    emitted, status stays "starting" (snapshot), isTranscribing is never true, so the card
    shows "In Queue" with no bar for the ENTIRE transcription, then fades on done. Matches
    the original test-4 "nothing going on then transcriptions appear" complaint -- 05-05
    did NOT fix it in the common idle-worker case.
  - Gap B part 1 (Preparing... indeterminate bar during model load): GAPPED -- same race
    condition (card shows "In Queue", no bar). See the race-condition gap entry below.
  - Gap A (history row shows dropped filename): CONFIRMED LIVE END-TO-END. The completed
    movie landed in history as "Dead.Poets.Society.1989.1080p.BluRay.x264.YIFY.mp4" -- the
    dropped filename, not "source.mp4". 05-04 works.
  - NEW MINOR ISSUE: the completed movie row shows duration "--:--" (no time), while an
    old failed job shows "00:42". duration_s is not rendering for the completed job.
    Logged as a minor gap below (HistoryRow duration rendering).
  - SC-3 (click row -> detail): PASS. Clicking the Dead.Poets.Society row navigated to
    /jobs/:id and loaded the transcript + summary panes (transcript text present).
  - UI-02 (no embedded video player): PASS. No video player anywhere in the detail view.

  TEST 5 VERDICT: ISSUE. Gap A (dropped filename) + SC-3 + UI-02 PASS live. Gap B
  (Preparing + Transcribing progress display) FAILS live due to the race-condition gap
  (card shows "In Queue" / no bar for the whole transcription when the WS connects late).
  Plus a minor blank-duration gap. Both logged in Gaps below for fresh-session closure.

## Summary

total: 5
passed: 3
issues: 1
pending: 0
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

- truth: "After upload completes the active card shows 'Preparing...' with an indeterminate moving-stripe bar (gap B closure) and never flashes an error or goes silent"
  status: diagnosed
  reason: "User reported: the file was uploading, and when it was complete there seem to be some error showing up quickly and now nothing is happening, at least not that i would know"
  severity: blocker
  test: 5
  root_cause: >
    Stale-runtime artifact, NOT a code defect. The back-end process (PID 15584, started
    2026-06-23 23:14) had run for ~3 days without --reload and predated the 05-04/05-05
    gap-closure commits, so the live server never emitted stage_changed(preparing) (05-05)
    and never serialized original_filename (05-04). Proof: the served jobs?status=done
    JobResponse had no original_filename field (nulls ARE serialized in that response, so
    absence = the field was not in the running model). The flashed browser error was React
    18 StrictMode dev double-invoke WS noise (first socket closed in disconnectPassiveEffect
    before connect) -- harmless on its own; the card went silent because the stale back-end
    never sent a preparing event to render.
  resolution: >
    Operational, not a code change: killed PID 15584 (back-end) + PID 7272 (Vite) and
    restarted both with current code. Verified 05-04 now live: /jobs?status=failed returns
    "original_filename":null on old rows. Re-test against fresh servers is the confirmation
    step (see test 5 note). DO NOT feed to /gsd-plan-phase --gaps -- this is not a code gap.
  artifacts: []       # No code defect -- stale runtime, not source
  missing: []         # No code change required
  debug_session: ""   # No debug session needed -- root cause confirmed from live evidence
  pending_retest: true

- truth: "During STT model JIT-load + first-chunk wait the active card shows 'Preparing...' with an indeterminate moving-stripe bar (05-05 gap B closure), regardless of WS connect timing"
  status: failed
  reason: "Live re-test: model-load window was too quick to observe, but code-level proof shows the card renders 'In Queue' (no bar) when the WS connects after the orchestrator emits stage_changed(preparing). User's original 'nothing happening' complaint can still recur."
  severity: major
  test: 5
  root_cause: >
    Race condition in the 05-05 FE closure. orchestrator.py:237-260 emits an additive
    stage_changed(preparing) WS event BEFORE _load_stt_adapter, and preparing is deliberately
    WS-only (NOT persisted to DB/manifest -- orchestrator.py:246-250, preserves H3+H4
    invariant). routes_ws.py:167-188 sends a connect snapshot sourced from job.current_stage
    + manifest.current_stage + progress.json -- NONE of which carry preparing. So a card
    that subscribes AFTER the preparing event was broadcast (common: the worker is idle and
    picks the job up fast, and React 18 StrictMode's mount->unmount->remount delays the real
    socket) receives snapshot {status:"starting", stage:null} and MISSES preparing. EventBus
    (app/jobs/progress.py) only relays events published AFTER subscribe -- no replay.
    ActiveJobCard.tsx:107-110 sets isQueued = status==="queued"||"uploading"||"starting",
    so the snapshot's status:"starting" renders the "In Queue" label with NO progress bar
    (showBar = isIngesting||isTranscribing||isPreparing; isQueued excluded). The card only
    shows "Preparing..." if it catches the live stage_changed(preparing) (line 65-67,120-122).
    ActiveJobCard.test.tsx never covers this branch -- every test fires snapshot{status:"queued"}
    THEN stage_changed(preparing), so the card always catches the event.
  artifacts:
    - path: "web/src/components/ActiveJobCard.tsx"
      issue: "isQueued includes 'starting'; a snapshot with status:'starting' (model-load window, preparing not persisted) renders 'In Queue' with no bar instead of 'Preparing...' indeterminate bar"
    - path: "app/api/routes_ws.py"
      issue: "connect snapshot cannot convey the WS-only preparing stage; late-connecting clients miss it with no replay"
  missing:
    - "ActiveJobCard: make the snapshot authoritative for current state, not just live stage events. Treat DB status 'starting' as preparing (remove from isQueued, add to isPreparing) so a late-connecting card shows 'Preparing...' + indeterminate bar from the snapshot alone."
    - "ActiveJobCard: when stage_changed(transcribing) is missed but progress events are flowing (snapshot.percent>0 OR a progress event arrived), still show 'Transcribing... X%' determinate bar (derive from percent, not from status==='transcribing'). Without this the card shows 'In Queue' for the entire transcription when it connects late."
    - "Tests: (a) snapshot{status:'starting'} + NO stage_changed -> 'Preparing...' + indeterminate bar; (b) snapshot{status:'starting', percent:0} + progress{percent:45} with NO stage_changed(transcribing) -> 'Transcribing... 45%' determinate bar (covers both race branches)."
  debug_session: ""

- truth: "A completed job's history row shows its duration (like the old failed jobs show 00:42), not a blank --:--"
  status: failed
  reason: "User observed: the completed movie row shows duration '--:--' (no time), while an old failed job shows '00:42'. The completed job's duration is not rendering."
  severity: minor
  test: 5
  root_cause: ""      # Needs diagnosis: is duration_s populated on the done path? orchestrator run_job update_stage("done") may not set duration_s.
  artifacts: []
  missing: []
  debug_session: ""
  pending_retest: false

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