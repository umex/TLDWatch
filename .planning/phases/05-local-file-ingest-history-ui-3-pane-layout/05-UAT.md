---
status: diagnosed
phase: 05-local-file-ingest-history-ui-3-pane-layout
source: [05-VERIFICATION.md]
started: 2026-06-25T04:23:43Z
updated: 2026-06-26T17:30:00Z
---

## Current Test

[testing complete -- test 6 issue: 05-06 race fix did not resolve live "nothing" symptom; diagnosing]

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

### 6. Gap-closure re-test (05-06 + 05-07) against fresh servers
expected: With the back-end + Vite dev server freshly restarted on current code, drop a SHORT named clip. After upload completes the active card shows "Preparing..." with an indeterminate moving-stripe bar (NOT "In Queue" / no bar -- the 05-06 race fix lands even when the WS connects late) -> on first chunk progress it switches to "Transcribing... X%" determinate bar that does not revert -> on completion the card fades and the job appears in history showing the DROPPED FILENAME (not "source.mp4" -- 05-04) PLUS a MM:SS duration (not "--:--" -- 05-07) -> click the row -> detail loads transcript + summary panes with no embedded video player.
result: issue
reported: "after upload there was nothing untill video was transcribed and appeared in the history row."
severity: major
note: |
  The 05-06 snapshot-authoritative FE fix did NOT resolve the live symptom. After upload
  completes the user sees NOTHING (no "Preparing..." card, no "Transcribing... X%" bar) until the
  job finishes and pops into the history list. This is the SAME "nothing is going on then
  transcriptions appear" complaint from test 4, recurring despite 05-06. Two leading hypotheses:
  (1) stale runtime AGAIN -- the served FE bundle is not the 05-06 build (Vite not restarted /
      browser cached / HMR missed), so the live card never gets the isPreparing(status==='starting')
      branch; OR (2) the card is not visible at all during transcription -- "nothing" may mean the
      ActiveJobCard unmounts/disappears right after upload-done (DropZone/HistoryPage lifecycle),
      in which case 05-06's label/bar logic is irrelevant because there is no card to label.
  Diagnosis must distinguish these. The 05-07 duration closure + 05-04 filename closure were NOT
  observable in this run (the job never showed an active card to inspect; only the final history
  row was seen) -- their live confirmation is deferred until the card-visibility root cause is fixed.

## Summary

total: 6
passed: 3
issues: 2
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

- truth: "After upload completes the active card shows 'Preparing...' indeterminate bar then 'Transcribing... X%' determinate bar (05-06 race fix) with visible progress feedback throughout -- never silence between upload-done and the job appearing in history"
  status: diagnosed
  reason: "User reported: after upload there was nothing untill video was transcribed and appeared in the history row."
  severity: major
  test: 6
  root_cause: >
    REAL CODE GAP -- 05-06's fix was built on a FALSE premise. 05-06 assumed a late-connecting
    card's WS connect snapshot carries status:"starting" during the model-load + first-chunk wait
    (ActiveJobCard.tsx:116-119 comment states this). It does NOT. In the live runtime the DB status
    for the ENTIRE model-load + transcription window is "ingesting", never "starting" and never
    "transcribing":
    - The ONLY writer of DB status "starting" is queue.py:118 (pull_next atomic claim), and
      orchestrator.py:230-233 overwrites it with update_stage("ingested") milliseconds later.
      stage_to_status("ingested") = "ingesting" (manifest.py:41,67-77).
    - "transcribed"->"transcribing" is persisted ONLY at orchestrator.py:290-297, AFTER
      `transcript = await future` returns (line 282), immediately followed by update_stage("done")
      at line 299. So "transcribing" is never the snapshot status DURING transcription.
    - stage_changed(preparing) (orchestrator.py:260) + stage_changed(transcribing) (:263) are
      WS-ONLY with no update_stage (comment :246-250) -- a card connecting after they were emitted
      misses them, and routes_ws.py:186 sends snapshot.status = job.status (raw DB = "ingesting").
    The DropZone race makes late-connect the COMMON case, not an edge case: onJobCreated fires
    only when upload.status==="done" (DropZone.tsx:84-87), by which point the worker has usually
    already claimed the job and emitted the WS-only stage_changed(preparing).
    FE consequence once the card receives snapshot{status:"ingesting"}: isIngesting=true
    (ActiveJobCard.tsx:108); isTranscribingActive (:121-127) is gated by !isIngesting -> false
    even after progress events set progressArrived.current (the snapshot handler :60-64 never
    sets progressArrived; only the "progress" case :69 does, and !isIngesting blocks it anyway);
    isPreparing's status==="starting" branch (:136) is dead code for this case. The card renders a
    frozen "Ingesting File... 0%" (model-load, no progress.json) / mislabeled "Ingesting File... X%"
    (mid-transcription, bar moves but label wrong) -- perceived as "nothing is going on" until the
    job finishes and pops into history. Reproduces with FRESH servers + browser hard reload; the
    stale-runtime angle was adversarially refuted (Vite serves source on demand keyed by mtime;
    ActiveJobCard.tsx mtime 16:36 is post-05-06; the running BE PID 20596 started 14:43 and
    includes 05-05's stage_changed(preparing) emission). NOT operational -- a code change is required.
  closure: ""
  artifacts:
    - path: "web/src/components/ActiveJobCard.tsx"
      issue: ":116-119 comment falsely claims the snapshot carries status:'starting'; :121-127 isTranscribingActive gated by !isIngesting (false when snapshot='ingesting') so it never fires for a late-connecting card; :134-138 isPreparing status==='starting' branch (:136) is dead code for the late-connect case (snapshot is 'ingesting'). Snapshot handler :60-64 ignores event.stage + does not seed progressArrived from snapshot.percent. Card renders stuck 'Ingesting File... 0%' instead of 'Preparing...' / 'Transcribing... X%'."
    - path: "app/jobs/orchestrator.py"
      issue: ":260 + :263 publish stage_changed(preparing/transcribing) WS-only with no update_stage (comment :246-250); DB status stays 'ingesting' (:230-233) for the whole model-load + transcribe window; 'transcribing' persisted only at :290-297 after `transcript = await future` (:282) then immediately 'done' (:299). Late-connecting snapshots carry status='ingesting'."
    - path: "app/jobs/manifest.py"
      issue: ":39-44 _STAGE_STATUS_MAP / :67-77 stage_to_status: no stage maps to 'starting' and no pre-transcribe stage maps to 'transcribing'. 'ingested'->'ingesting' is the only status persisted between enqueue and transcribe-done. The DB cannot represent the preparing/transcribing state the FE needs."
    - path: "app/api/routes_ws.py"
      issue: ":180-188 snapshot sends status=job.status (raw DB) + stage=manifest.current_stage + percent/eta from progress.json, but the FE snapshot handler (ActiveJobCard.tsx:60-64) ignores event.stage; snapshot.percent (:184) is sent but the FE only treats percent>0 as progress via the 'progress' EVENT (:69), not via snapshot -- a reconnecting card cannot derive transcribing state from the snapshot alone."
    - path: "web/src/components/DropZone.tsx"
      issue: ":84-87 onJobCreated fires only when upload.status==='done' (after upload completes), so the card's WS connect races behind the worker's claim + WS-only stage_changed(preparing) emission -- making the late-connect race the common case, not an edge case."
  missing:
    - "FE fix (cheaper, mirrors 05-06 style): in ActiveJobCard.tsx extend isPreparing to also cover (status==='ingesting' && !progressArrived.current) -- local ingest is instant, so 'ingesting' post-snapshot means 'waiting for model load / first chunk' -- and extend isTranscribingActive to also fire when (status==='ingesting' && progressArrived.current). Late-connecting card then shows 'Preparing...' + indeterminate bar (model load) then 'Transcribing... X%' + determinate bar (progress flowing)."
    - "FE fix part 2: in ActiveJobCard.tsx:60-64 (snapshot case) also consume event.stage (currently ignored) as a fallback signal, and read snapshot.percent (already sent at routes_ws.py:184) to seed progressArrived + drive the determinate bar immediately on reconnect so a reconnecting card shows the real percent without waiting for the next progress event."
    - "BE fix (more robust alternative / complement): in orchestrator.py around :260/:263 persist a transient status to the DB alongside the WS-only stage_changed publish so late-connecting snapshots carry an unambiguous 'transcribing' (or new 'preparing') status + percent from progress.json. Requires extending manifest.py _STAGE_STATUS_MAP / StageNameLiteral -- heavier, touches the H3+H4 invariant."
    - "Tests: (a) snapshot{status:'ingesting', percent:0} + NO stage_changed -> 'Preparing...' + indeterminate bar; (b) snapshot{status:'ingesting', percent:0} + progress{percent:45} with NO stage_changed(transcribing) -> 'Transcribing... 45%' + determinate bar; (c) snapshot{status:'ingesting', percent:45} (reconnect mid-transcription) -> 'Transcribing... 45%' + determinate bar from snapshot alone."
    - "VERIFICATION PREREQ (operational, not the code fix): kill PID 20596 (BE, no --reload) + PID 32968 (Vite), restart both with current HEAD 2af8354, hard-reload browser, before re-running UAT test 6. Stale runtime was NOT the root cause but fresh code is required to verify the fix."
  debug_session: ".planning/debug/active-card-silence.md"
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