---
phase: 05-local-file-ingest-history-ui-3-pane-layout
verified: 2026-06-26T17:15:00Z
status: human_needed
score: 20/20 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 18/18
  gaps_closed:
    - "UAT test-5 entry 4 (MAJOR): WS connect-timing race -- late-connecting ActiveJobCard showed 'In Queue' / no bar for the entire transcription when the WS connected after stage_changed(preparing)+stage_changed(transcribing). CLOSED by 05-06 (snapshot-authoritative state derivation: status 'starting' treated as preparing; progressArrived drives the Transcribing label). FE-only."
    - "UAT test-5 entry 5 (MINOR): Completed-job duration blank -- history row showed '--:--' while old failed jobs showed '00:42'. CLOSED by 05-07 (Transcript.duration_s populated from chunker total_seconds on both paths, projected via transcribed ManifestPatch, re-projected on done via existing H3+H4 SET clause)."
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Re-run UAT test 5 (gap-closure re-test) against FRESH back-end + Vite dev servers to confirm the 05-06 race fix + 05-07 duration fix resolve the two live test-5 findings"
    expected: "Drop a named file -> after upload completes the active card shows 'Preparing...' with an indeterminate moving-stripe bar (NOT 'In Queue' / no bar -- the 05-06 race fix lands even when the WS connects late) -> on first chunk progress the card switches to 'Transcribing... X%' determinate bar that does not revert -> on completion the card fades, the job appears in history AND the history row shows the DROPPED FILENAME (e.g. 'my great video.mp4') PLUS a MM:SS duration (e.g. '00:42', NOT '--:--' -- 05-07 closes the blank-duration gap). Click the row -> detail loads transcript + summary panes with no embedded video player."
    why_human: "The code-level closure is fully verified: tests/test_orchestrator.py::test_done_job_duration_s_populated (row.duration_s non-null + positive + manifest==DB), web/src/components/ActiveJobCard.test.tsx (7 tests: 5 existing 05-05 + 2 new 05-06 race branches), web/src/components/HistoryRow.test.tsx (6 tests: 3 filename + 3 duration). All 283 BE + 32 FE tests green, tsc clean, vite build ok. However the race gap (05-06) was originally surfaced by a human in a live browser as 'nothing is going on' -- the live WS-connect-timing against a real back-end with real model-load + the perceptual Preparing/Transcribing display feel cannot be fully asserted in jsdom (jsdom simulates the snapshot+event sequence but cannot reproduce the real StrictMode mount->unmount->remount socket-timing race against a live orchestrator). A human re-test against fresh servers is the final confirmation that the 05-06 snapshot-authoritative fix resolves the original 'nothing going on' complaint and the 05-07 duration renders MM:SS live."
---

# Phase 5: Local File Ingest + History UI + 3-Pane Layout Verification Report

**Phase Goal:** The user can drag a local video file into the browser, watch it process in the background, and see a working 3-pane layout (history | transcript | summary) — without an embedded video player.
**Verified:** 2026-06-26T17:15:00Z
**Status:** human_needed
**Re-verification:** Yes — second re-verification, after gap-closure execution (05-06 + 05-07) closing the 2 OPEN UAT test-5 code gaps (race condition + duration blank)

## Re-verification Mode

This is the second re-verification of Phase 5. The first re-verification (2026-06-26T12:45:00Z) closed UAT test-4 gaps A (original_filename) + B (preparing state) via plans 05-04 + 05-05 and reached 18/18 truths verified, status human_needed. The subsequent live UAT (05-UAT.md test 5) surfaced 2 NEW code gaps on the fresh-server re-test:

- **UAT test-5 entry 4 (MAJOR):** WS connect-timing race. The 05-05 preparing closure is WS-only (never persisted to DB/manifest per the H3+H4 invariant), so a card that subscribes AFTER `stage_changed(preparing)` (and even after `stage_changed(transcribing)`) receives `snapshot{status:"starting", stage:null}` and misses preparing entirely. `isQueued` matched `"starting"`, so the card rendered "In Queue" with NO bar for the entire model-load window AND the entire transcription — the original "nothing is going on" complaint recurred in the common idle-worker case.
- **UAT test-5 entry 5 (MINOR):** Completed-job duration blank. The orchestrator's happy path never populated `duration_s` (the `transcribed` transition's ManifestPatch passed only `language`, and `done` passed no patch), so `GET /jobs/{id}` returned `duration_s: null` and HistoryRow rendered `--:--` while old failed jobs showed `00:42`.

Two gap-closure plans were executed on top of the six prior phase plans:

- **05-06** — FE-only snapshot-authoritative state derivation. `isQueued` drops `"starting"`; `isPreparing` adds `status === "starting"` (late-connecting card shows Preparing from the snapshot alone); new `isTranscribingActive` boolean (progressArrived-driven) shows "Transcribing... X%" when progress events flow even if `stage_changed(transcribing)` was missed. Two race-branch tests added. Closes UAT test-5 entry 4.
- **05-07** — `Transcript.duration_s` additive field populated from chunker `total_seconds` on both fast + chunked return paths; orchestrator `transcribed` transition projects it via `ManifestPatch(duration_s=transcript.duration_s)`; `done` re-projects via the existing H3+H4 SET clause. 1 BE + 3 FE tests added. Closes UAT test-5 entry 5.

This re-verification focuses on (a) confirming the two UAT test-5 gaps are genuinely closed in the live code, (b) regression-checking the 18 previously-verified truths (especially the 05-05 preparing invariant + 05-04 H3+H4 projection invariant that 05-06/05-07 must preserve), and (c) re-running the full automated suites. The 05-REVIEW.md advisory finding WR-01 is assessed against the must-haves below.

## Goal Achievement

### Observable Truths

Must-haves merged from ROADMAP SC-1..SC-5 + PLAN frontmatter (05-01, 05-02a, 05-02b, 05-03, 05-04, 05-05, 05-06, 05-07). Truths 1-18 are carried forward from the previous verification; truth 10 is updated with the 05-06 race-closure evidence and truth 16 is updated with the 05-07 duration-closure evidence. Truths 19-20 are the two new gap-closure truths from the 05-06/05-07 PLAN frontmatter must_haves.

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Drag-and-drop / file-picker upload streams a multi-gigabyte file to disk without holding it in memory; back-end writes directly to `data/jobs/<id>/source.<ext>` (SC-1, INGEST-01, D-11) | ✓ VERIFIED | `app/api/routes_jobs.py` `async for chunk in request.stream()` + `aiofiles.open(tmp,"wb")` + `retry_windows(os.replace)`. `tests/test_upload_memory.py` (128MB, tracemalloc peak < 64MB) + `tests/test_upload_stream.py` pass. FE: `web/src/hooks/useUpload.ts` `xhr.send(file)` streams the File handle (no FormData/duplex). Regression-clean. |
| 2 | Pre-queued `'uploading'` JobStatus makes a mid-upload job invisible to the worker's `pull_next` (Pitfall 1 race prevention) | ✓ VERIFIED | `app/models/job.py:11-22` includes `"uploading"`. `pull_next` selects `'queued'` only. `tests/test_upload_race.py` passes. Regression-clean. |
| 3 | `GET /jobs/{id}/transcript` returns the parsed Transcript and 404 when no `transcript.json` exists; 400 for invalid id (D-14) | ✓ VERIFIED | `app/api/routes_jobs.py::get_transcript` validates id, 404s on missing file, returns `Transcript.model_validate_json`. `tests/test_transcript_endpoint.py` covers 200 / 404 / 400. Regression-clean. |
| 4 | Re-dropping the same file (same Idempotency-Key) collapses to the existing job with HTTP 200, no orphan duplicate (D-11, D-07) | ✓ VERIFIED | `app/api/routes_jobs.py` reuses `resolve_or_create`; `tests/test_upload_idempotency.py` asserts first 201, second 200, same id, one row. Regression-clean. |
| 5 | Completed (terminal) jobs returned by `GET /jobs?status=done newest-first` (JOB-03 back-end) | ✓ VERIFIED | `tests/test_history_list.py` asserts done/failed/cancelled rows returned newest-first, active jobs excluded. Regression-clean. |
| 6 | The `web/` Vite dev server boots (tsc clean) and the FE codebase is scaffolded per D-12 | ✓ VERIFIED | `npx tsc --noEmit` exits 0; `npx vite build` succeeds (537.57 kB JS, built in 2.97s). Regression-clean. |
| 7 | Vitest jsdom infra + test setup (mock IntersectionObserver/WebSocket/fetch/XHR) exist so FE tests run | ✓ VERIFIED | `web/vitest.config.ts` + `web/src/test/setup.ts`. `npx vitest run` → 32 tests pass across 6 files. Regression-clean. |
| 8 | API layer type-correct against codegen'd OpenAPI types + `idempotencyKey` SHA-256 helper | ✓ VERIFIED | `web/src/api/types.ts` includes `uploading` enum + `original_filename?: string \| null` on JobResponse + JobManifest. `tsc --noEmit` clean. Regression-clean. |
| 9 | Dropping a file triggers a streaming upload to `POST /jobs/upload` with a client-derived Idempotency-Key via XHR (PRIMARY path) and the ActiveJobCard shows real streaming-to-disk PERCENT 0->100 (D-01, D-02, D-11) | ✓ VERIFIED | `web/src/hooks/useUpload.ts:66-111` — `xhr.upload.onprogress` + `xhr.send(file)`, no FormData/duplex. `web/src/api/jobs.test.ts` asserts progress 0->50->100. Regression-clean. |
| 10 | Active job cards subscribe to `/ws/jobs/{id}/events` and display status badge + progress + ETA from snapshot + live events (D-03, D-08) — UPDATED: 05-06 closes the WS connect-timing race so a late-connecting card shows Preparing (from snapshot status:"starting") + Transcribing X% (from progress events) even when stage_changed events were missed | ✓ VERIFIED | `web/src/components/ActiveJobCard.tsx:38` `useJobEvents(jobId)`. The 05-06 closure adds: `isQueued` drops `"starting"` (line 107), `isTranscribingActive = progressArrived.current && !isQueued && !isIngesting && !isDone && !isFailed && !isCancelled` (lines 121-127), `isPreparing = (status === "preparing" \|\| status === "starting" \|\| (isTranscribing && !progressArrived.current)) && !isTranscribingActive` (lines 134-138), `showBar` includes `isTranscribingActive` (line 139), `showIndeterminateBar = isPreparing && !isIngesting && !progressArrived.current` (lines 140-141), Transcribing label guard uses `isTranscribingActive` (line 173). `web/src/components/ActiveJobCard.test.tsx` — 7 tests pass (5 existing 05-05: preparing label, stays preparing on transcribing-before-progress, switches to determinate on first progress, no-revert on late stage_changed, terminal fade; 2 new 05-06: snapshot{status:"starting"} + no stage_changed → Preparing + indeterminate; snapshot{status:"starting"} + progress{percent:45} + no stage_changed(transcribing) → Transcribing... 45% determinate). Back-end: `app/jobs/orchestrator.py:251-263` emits `stage_changed(preparing)` before `_load_stt_adapter` on the production path (unchanged by 05-06 — FE-only plan). `preparing` is WS-only — NOT in `StageNameLiteral` (app/models/job.py:27-29: ingested/transcribed/diarized/summarized/done only), no `update_stage` call, DB stage/status untouched. 05-05 invariant preserved. |
| 11 | Detail page at `/jobs/:id` renders a 2-pane transcript (left) \| summary (right) layout with NO `<video>` element anywhere (D-07, UI-02) | ✓ VERIFIED | `web/src/App.tsx` routes `/jobs/:id` -> DetailPage; `web/src/pages/DetailPage.tsx` uses `.detail-layout` with TranscriptPane + SummaryPane. `grep -r "<video" web/src/` returns no matches. Regression-clean. |
| 12 | Summary pane shows the exact placeholder "Summaries will appear here once summarization is enabled" (D-08) | ✓ VERIFIED | `web/src/components/SummaryPane.tsx` — exact copy present (intentional Phase 8 stub). Regression-clean. |
| 13 | The transcript segment row nearest the viewport center is highlighted as the user scrolls (UI-03, D-09, local files only) | ✓ VERIFIED | `web/src/hooks/useScrollSpy.ts` IntersectionObserver + `web/src/components/TranscriptPane.tsx` wiring. `web/src/hooks/useScrollSpy.test.ts` (5 tests) passes. Regression-clean. |
| 14 | Clicking a completed history row opens `/jobs/:id` and loads that job's transcript via `GET /jobs/{id}/transcript` (JOB-03 re-open, D-06, D-14) | ✓ VERIFIED | `web/src/components/HistoryRow.tsx:45` `onClick={navigate('/jobs/${encodeURIComponent(job.id)}')}`. `web/src/pages/DetailPage.tsx:19` `useTranscript(id ?? null)`. Regression-clean. |
| 15 | Terminal WS event removes the active card and refetches the history list so the job appears in the completed list (D-03) | ✓ VERIFIED | `web/src/components/ActiveJobCard.tsx:99-105` — `invalidateJobs(queryClient)` + `setTimeout(onTerminalRef.current?.(jobId), 250)`. `web/src/pages/HistoryPage.tsx` `handleTerminal`. Regression-clean. |
| 16 | History list shows terminal jobs only, each row shows the DROPPED FILENAME + date + DURATION (MM:SS, not --:--), sorted newest-first; no search/filter in v1 (D-05, JOB-03, SC-3) — UPDATED: 05-07 closes the blank-duration gap so the row shows MM:SS for completed jobs | ✓ VERIFIED | `web/src/components/HistoryList.tsx:16-22` (terminal-only merge, newest-first). `web/src/components/HistoryRow.tsx:38-40` — `job.original_filename ?? (job.source_path ? basename(job.source_path) : "unknown")` (05-04 closure). `web/src/components/HistoryRow.tsx:25` `formatDuration(seconds)` + line 49 `formatDuration(job.duration_s)` renders MM:SS when duration_s is non-null, `--:--` when null (05-07: the back-end now populates duration_s so completed jobs render MM:SS). `web/src/components/HistoryRow.test.tsx` — 6 tests pass (3 filename: present / null fallback / both absent; 3 duration: 00:42 for duration_s:42, 02:05 for duration_s:125, --:-- for duration_s:null). Back-end: `app/models/transcript.py:50` `Transcript.duration_s: float \| None = None` (additive, default None — existing transcript.json files load). `app/models/stt/chunker.py:164,253` both return paths pass `duration_s=total_seconds` (fast path line 164, chunked path line 253). `app/jobs/orchestrator.py:291-297` `transcribed` transition passes `ManifestPatch(language=transcript.language, duration_s=transcript.duration_s)`; `done` transition (line 299) re-projects via the existing H3+H4 SET clause (`app/jobs/manifest.py:231,244`). `app/jobs/service.py:225,255` SELECTs include `sa.column("duration_s")`. `app/models/job.py:66,129,188` ManifestPatch + JobResponse + _row_to_response carry duration_s. `tests/test_orchestrator.py::test_done_job_duration_s_populated` asserts `row.duration_s is not None`, `> 0`, `manifest.duration_s == row.duration_s`. |
| 17 | Full back-end + front-end test suites are green end-to-end (the vertical slice is provable) | ✓ VERIFIED | `python -m pytest -q` → **283 passed** (282 prior + 1 new 05-07). `npx vitest run` → **32 passed** across 6 files (27 prior + 2 new 05-06 + 3 new 05-07). `npx tsc --noEmit` → clean (exit 0). `npx vite build` → succeeds (537.57 kB JS, built in 2.97s). |
| 18 | Re-export UI is deferred to Phase 9 (D-10); a disabled layout-stability "Export (Coming Soon)" stub is allowed | ✓ VERIFIED | `web/src/components/ExportStub.tsx` renders a disabled "Export (Coming Soon)" button (D-10 intentional stub). SC-5 "re-export" half deferred to Phase 9; "re-open + see existing transcript" half delivered by truth 14. Regression-clean. |
| 19 | A late-connecting ActiveJobCard (WS connects AFTER stage_changed(preparing) was broadcast) shows "Preparing..." + indeterminate bar from the snapshot alone (snapshot status:"starting" treated as preparing); and a card that connects after both stage_changed events but receives a progress event shows "Transcribing... X%" determinate bar derived from percent (05-06 race branches a + b) — NEW GAP TRUTH | ✓ VERIFIED | `web/src/components/ActiveJobCard.tsx` — `isQueued` drops `"starting"` (line 107) so a starting snapshot is NOT "In Queue"; `isPreparing` adds `status === "starting"` (line 136) so the snapshot renders "Preparing..." + indeterminate bar from the snapshot alone (race branch a); `isTranscribingActive` (lines 121-127) drives the "Transcribing... X%" label + determinate bar when progress events flow even if `stage_changed(transcribing)` was missed (race branch b); `showIndeterminateBar` gated by `!progressArrived.current` (line 141) so the indeterminate bar clears once progress arrives. `web/src/components/ActiveJobCard.test.tsx` — 2 new tests pass: (a) `snapshot{status:"starting"}` + no stage_changed → Preparing + indeterminate (data-preparing="true", no determinate width); (b) `snapshot{status:"starting", percent:0}` + `progress{percent:45}` + no stage_changed(transcribing) → Transcribing... 45% determinate (data-preparing="false", fill width 45%). 05-06 is FE-only — no routes_ws.py / orchestrator.py / progress.py changes (05-05 WS-only preparing invariant preserved). |
| 20 | A completed job's GET /jobs/{id} response carries a non-null duration_s (the source MEDIA duration in seconds, not wall-clock time) and the HistoryRow renders a MM:SS duration (e.g. 00:42), not --:-- (05-07) — NEW GAP TRUTH | ✓ VERIFIED | `app/models/transcript.py:50` `duration_s: float \| None = None` (additive). `app/models/stt/chunker.py:164,253` both return paths pass `duration_s=total_seconds` (source media duration from `len(audio)/SAMPLE_RATE`, computed once at chunker.py:130). `app/jobs/orchestrator.py:291-297` `transcribed` transition `ManifestPatch(language=transcript.language, duration_s=transcript.duration_s)` projects to manifest + DB; `done` (line 299) re-projects via existing H3+H4 SET clause. `tests/test_orchestrator.py::test_done_job_duration_s_populated` — asserts `row.duration_s is not None`, `> 0`, `manifest.duration_s == row.duration_s`. `web/src/components/HistoryRow.tsx:49` `formatDuration(job.duration_s)` renders MM:SS for non-null, --:-- for null. `web/src/components/HistoryRow.test.tsx` — 3 new duration tests pass (00:42, 02:05, --:--). Existing transcript.json files load with duration_s=None (backward-compatible). 05-05 preparing emission block (orchestrator.py:251-263) untouched; 05-04 H3+H4 projection invariant preserved (manifest.py:231,244 unchanged). |

**Score:** 20/20 truths verified. Both UAT test-5 gaps (race condition: 05-06, duration blank: 05-07) are closed in code; the other 18 truths are regression-clean.

### Gap-Closure Verification (05-06 + 05-07)

| Gap | Plan | Root cause (from 05-UAT.md) | Closure evidence (live codebase) | Status |
| --- | --- | --- | --- | --- |
| 4 — WS connect-timing race: late-connecting card shows "In Queue" / no bar for the entire transcription | 05-06 | `preparing` is WS-only (05-05 H3+H4 invariant — not persisted to DB/manifest), so the connect snapshot carries `status:"starting"`, not `preparing`. `isQueued` matched `"starting"` → "In Queue" with no bar. `isTranscribing` never true if `stage_changed(transcribing)` missed → "In Queue" for the entire transcription. | `web/src/components/ActiveJobCard.tsx:107,121-127,134-138,139-141,173` — `isQueued` drops "starting"; `isTranscribingActive` (progressArrived-driven); `isPreparing` adds `status === "starting"` gated by `!isTranscribingActive`; `showBar`/`showIndeterminateBar` gated by progressArrived; Transcribing label guard uses `isTranscribingActive`. `web/src/components/ActiveJobCard.test.tsx` — 2 new race-branch tests (a: snapshot starting → Preparing indeterminate; b: snapshot starting + progress → Transcribing 45% determinate). 7 ActiveJobCard tests total pass. FE-only — no back-end files touched (05-05 WS-only preparing invariant preserved). | ✓ CLOSED |
| 5 — Completed-job duration blank: history row shows --:-- while old failed jobs show 00:42 | 05-07 | Orchestrator `transcribed` transition passed `ManifestPatch(language=transcript.language)` with NO `duration_s`; `done` passed no patch. `update_stage` re-projects `manifest.duration_s` which stayed `None`. Chunker computed `total_seconds` but Transcript had no duration field. | `app/models/transcript.py:50` (Transcript.duration_s additive) + `app/models/stt/chunker.py:164,253` (both paths pass `duration_s=total_seconds`) + `app/jobs/orchestrator.py:291-297` (transcribed ManifestPatch adds `duration_s=transcript.duration_s`) + `app/jobs/manifest.py:231,244` (existing H3+H4 SET clause re-projects on done, unchanged) + `app/jobs/service.py:225,255` (SELECTs include duration_s) + `app/models/job.py:66,129,188` (ManifestPatch/JobResponse/_row_to_response carry duration_s) + `web/src/components/HistoryRow.tsx:49` (formatDuration renders MM:SS). `tests/test_orchestrator.py::test_done_job_duration_s_populated` (row non-null + positive + manifest==DB) + `web/src/components/HistoryRow.test.tsx` (3 duration tests: 00:42, 02:05, --:--). | ✓ CLOSED |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `web/src/components/ActiveJobCard.tsx` | Snapshot-authoritative state derivation: isQueued drops "starting"; isTranscribingActive (progressArrived-driven); isPreparing adds "starting" gated by !isTranscribingActive | ✓ VERIFIED | Lines 107, 121-127, 134-138, 139-141, 173 — all four 05-06 edits applied. |
| `web/src/components/ActiveJobCard.test.tsx` | 2 race-branch tests (a: snapshot starting → Preparing indeterminate; b: snapshot starting + progress → Transcribing 45% determinate) + 5 existing 05-05 tests | ✓ VERIFIED | 7 tests pass. Describe renamed to "plans 05-05 + 05-06". |
| `app/models/transcript.py` | Transcript.duration_s additive optional field | ✓ VERIFIED | Line 50 — `duration_s: float \| None = None`. |
| `app/models/stt/chunker.py` | Both transcribe_file return paths populate duration_s = total_seconds | ✓ VERIFIED | Line 164 (fast path) + line 253 (chunked path). |
| `app/jobs/orchestrator.py` | transcribed transition passes ManifestPatch(duration_s=transcript.duration_s); preparing block untouched | ✓ VERIFIED | Lines 291-297 (transcribed patch); lines 251-263 (preparing block unchanged). |
| `tests/test_orchestrator.py` | test_done_job_duration_s_populated asserts non-null + positive + manifest==DB | ✓ VERIFIED | Lines 1355-1406 — full test present, passes. |
| `web/src/components/HistoryRow.test.tsx` | 3 duration tests (00:42, 02:05, --:--) + 3 existing filename tests | ✓ VERIFIED | 6 tests pass. New describe "HistoryRow duration rendering (plan 05-07)". |
| Phase 05-01..05-05 artifacts | Per previous verification | ✓ VERIFIED | All regression-checked; full suites green. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `web/src/components/ActiveJobCard.tsx` snapshot branch | `isPreparing` (status:"starting") | `status === "starting"` in isPreparing | ✓ WIRED | ActiveJobCard.tsx:136 |
| `web/src/components/ActiveJobCard.tsx` progress branch | `isTranscribingActive` (Transcribing label + determinate bar) | `progressArrived.current` set in progress case → isTranscribingActive | ✓ WIRED | ActiveJobCard.tsx:69,121-127,173 |
| `app/models/stt/chunker.py` (total_seconds) | `Transcript.duration_s` | `return Transcript(..., duration_s=total_seconds)` on both paths | ✓ WIRED | chunker.py:164,253 |
| `app/jobs/orchestrator.py` (transcribed transition) | `manifest.duration_s` + `jobs.duration_s` DB column | `ManifestPatch(language=..., duration_s=transcript.duration_s)` → update_stage SET | ✓ WIRED | orchestrator.py:291-297 + manifest.py:231,244 |
| `app/jobs/manifest.py::update_stage` | `jobs.duration_s` DB column | H3+H4 SET clause `duration_s = :duration_s` | ✓ WIRED | manifest.py:231,244 (unchanged by 05-07) |
| `app/jobs/service.py::list_jobs/get_job` | `_row_to_response` row.duration_s | `sa.column("duration_s")` in SELECT | ✓ WIRED | service.py:225,255 + job.py:188 |
| `web/src/components/HistoryRow.tsx` | `job.duration_s` | `formatDuration(job.duration_s)` renders MM:SS | ✓ WIRED | HistoryRow.tsx:25,49 |
| (all key links from previous verification) | | | ✓ WIRED | Regression-checked; no link broken by 05-06/05-07. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `web/src/components/ActiveJobCard.tsx` | `event` (status / percent / stage) | `useJobEvents(jobId)` -> `/ws/jobs/{id}/events` snapshot + live (snapshot status:"starting" now interpreted as preparing; progress events drive Transcribing label) | Yes | ✓ FLOWING |
| `web/src/components/HistoryRow.tsx` | `job.duration_s` | `GET /jobs?status=…` -> `list_jobs` SELECT (duration_s) -> orchestrator transcribed ManifestPatch -> chunker total_seconds -> `len(audio)/SAMPLE_RATE` | Yes | ✓ FLOWING |
| `web/src/components/HistoryRow.tsx` | `job.original_filename` | upload route `UPDATE jobs SET original_filename` + manifest re-projection (05-04, regression-clean) | Yes | ✓ FLOWING |
| `web/src/components/TranscriptPane.tsx` | `segments` | `useTranscript(id)` -> `GET /jobs/{id}/transcript` -> `Transcript.model_validate_json` | Yes | ✓ FLOWING |
| `web/src/components/SummaryPane.tsx` | (static placeholder) | n/a — intentional D-08 placeholder | n/a (Phase 8 fills it) | ℹ️ INTENTIONAL_STUB |
| `web/src/components/ExportStub.tsx` | (disabled button) | n/a — intentional D-10 layout-stability stub | n/a (Phase 9 fills it) | ℹ️ INTENTIONAL_STUB |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full back-end suite green | `python -m pytest -q` | 283 passed in 485.72s | ✓ PASS |
| 05-07 duration test | `python -m pytest tests/test_orchestrator.py::test_done_job_duration_s_populated -x` | passed (within full suite) | ✓ PASS |
| 05-05 preparing tests (regression) | `python -m pytest tests/test_orchestrator.py -k preparing -q` | 2 passed (within full suite) | ✓ PASS |
| FE type-check clean | `cd web && npx tsc --noEmit` | exit 0, no output | ✓ PASS |
| FE tests green (incl. 2 new 05-06 + 3 new 05-07) | `cd web && npx vitest run` | 32 passed across 6 files | ✓ PASS |
| FE production build | `cd web && npx vite build` | built in 2.97s, 537.57 kB JS | ✓ PASS |
| UI-02 no-video gate | `grep -r "<video" web/src/` | no matches | ✓ PASS |
| XSS mitigation gate | `grep -r "dangerouslySetInnerHTML" web/src/` | no matches | ✓ PASS |
| D-02 no-FormData / no-duplex gate | `grep -c "FormData\|duplex" web/src/hooks/useUpload.ts` | 0 | ✓ PASS |
| 05-06 isTranscribingActive present | `grep -c "isTranscribingActive" web/src/components/ActiveJobCard.tsx` | >= 1 | ✓ PASS |
| 05-06 "starting" removed from isQueued | isQueued expression (ActiveJobCard.tsx:107) | `status === "queued" \|\| status === "uploading"` (no "starting") | ✓ PASS |
| 05-06 "starting" added to isPreparing | isPreparing expression (ActiveJobCard.tsx:134-138) | includes `status === "starting"` | ✓ PASS |
| 05-06 FE-only (no BE changes) | `preparing` not in StageNameLiteral | `app/models/job.py:27-29` — ingested/transcribed/diarized/summarized/done only | ✓ PASS |
| 05-07 Transcript.duration_s present | `grep -c "duration_s" app/models/transcript.py` | 1 (field) | ✓ PASS |
| 05-07 both chunker paths populate | `grep -c "duration_s=total_seconds" app/models/stt/chunker.py` | 2 (fast + chunked) | ✓ PASS |
| 05-07 orchestrator transcribed patch | `grep -c "duration_s=transcript.duration_s" app/jobs/orchestrator.py` | 1 (transcribed transition) | ✓ PASS |
| 05-07 service.py SELECTs include duration_s | `grep -c 'sa.column("duration_s")' app/jobs/service.py` | 2 (list_jobs + get_job) | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` probes declared by the phase PLAN/SUMMARY; validation is via pytest + vitest + tsc + vite build (all run above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| INGEST-01 | 05-01, 05-02a, 05-02b, 05-05, 05-06 | User can submit a local video file via drag-and-drop in the browser | ✓ SATISFIED | Streaming upload + XHR useUpload + DropZone + 05-05 preparing + 05-06 race-robust active-card feedback. Tests: test_upload_stream/memory/atomic/race/idempotency + ActiveJobCard.test.tsx (7). REQUIREMENTS.md line 128: Complete. |
| JOB-03 | 05-01, 05-03, 05-04, 05-07 | Persist completed jobs to local history; revisit / re-export (re-export half deferred to Phase 9 per D-10) | ✓ SATISFIED (re-open + duration) / DEFERRED (re-export) | test_history_list.py + HistoryList/HistoryRow (navigate to /jobs/:id) + useTranscript + 05-04 original_filename + 05-07 duration_s population. Re-export is Phase 9 (D-10); ExportStub disabled. REQUIREMENTS.md line 136: Complete. |
| UI-01 | 05-02a, 05-02b, 05-03, 05-04, 05-05, 05-06, 05-07 | Main working layout is 3-pane: history \| transcript \| summary (refined per D-04) | ✓ SATISFIED | App.tsx routes + DetailPage 2-pane. 05-04 filename + 05-07 duration make history rows informative. REQUIREMENTS.md line 155: Complete. |
| UI-02 | 05-02a, 05-02b | No embedded video player; YouTube jobs show "open in YouTube" link (YouTube link-out is Phase 6) | ✓ SATISFIED | `grep -r "<video" web/src/` returns no matches. REQUIREMENTS.md line 156: Complete. |
| UI-03 | 05-03 | Active transcript line is highlighted based on current scroll position (for local files only) | ✓ SATISFIED | useScrollSpy.ts + TranscriptPane wiring + 5 tests. REQUIREMENTS.md line 157: Complete. |

No orphaned requirements — REQUIREMENTS.md traceability lines (128, 136, 155-157) map exactly the five IDs the plans claim (INGEST-01, JOB-03, UI-01, UI-02, UI-03) and all are covered.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `web/src/components/SummaryPane.tsx` | 12 | Static placeholder copy (D-08 intentional) | ℹ️ Info | Phase 8 fills the summary pane; stub documented in CONTEXT.md D-08. |
| `web/src/components/ExportStub.tsx` | — | Disabled "Export (Coming Soon)" button (D-10 intentional) | ℹ️ Info | Phase 9 adds export; stub documented in CONTEXT.md D-10. |
| `web/src/components/TranscriptRow.tsx` | — | Empty 80px speaker gutter (D-07 intentional) | ℹ️ Info | Phase 7 fills speaker labels; stub documented in CONTEXT.md D-07. |

No `TBD` / `FIXME` / `XXX` / `TODO` / `HACK` / `PLACEHOLDER` markers in any gap-closure-modified file (`web/src/components/ActiveJobCard.tsx`, `web/src/components/ActiveJobCard.test.tsx`, `app/models/transcript.py`, `app/models/stt/chunker.py`, `app/jobs/orchestrator.py`, `tests/test_orchestrator.py`, `web/src/components/HistoryRow.test.tsx`). No unreferenced debt markers. The three stubs above are intentional, documented in CONTEXT.md, and addressed by later phases (7/8/9) — not blockers.

### 05-REVIEW.md WR-01 Advisory Assessment

**WR-01 (advisory, non-blocking):** A card connecting mid-transcription with `snapshot{status:"starting", percent:45}` + NO live `progress` event still renders "Preparing..." instead of "Transcribing... 45%". Root cause: `progressArrived.current` is set only in the `progress` case (ActiveJobCard.tsx:69), not the `snapshot` case, so a reconnecting client whose snapshot already carries `percent:45` (progress happened before connect) but receives no live progress event reads as "preparing" (isPreparing true via `status === "starting"`, isTranscribingActive false because progressArrived is false).

**Assessment against phase must-haves:** WR-01 is OUTSIDE the 05-06 plan's claimed must_haves. The 05-06 must_haves cover:
1. Connect AFTER `stage_changed(preparing)` broadcast (snapshot status:"starting", no live stage_changed) → "Preparing..." — WR-01's case satisfies this (it IS the intended branch-a behavior).
2. Connect AFTER both stage_changed events + a live `progress` event arrives → "Transcribing... X%" — WR-01 does NOT receive a live progress event, so this must_have does not apply.

WR-01 is the narrower edge case where the snapshot itself carries `percent>0` (progress already happened before connect) but no live progress event arrives after connect. The 05-06 plan explicitly scopes branch (b) to "a progress event arrives" — the snapshot's `percent` field is not treated as a progress-arrived signal. This is a deliberate design choice in the plan, not an oversight.

**Impact on phase truths / success criteria:** None. The 20 phase truths and ROADMAP SC-1..SC-5 are about the primary flow (drop file → process → 3-pane → history) + the two UAT test-5 gaps (race-branch a: connect-after-preparing → Preparing; race-branch b: connect-after-both-stages + live progress → Transcribing X%). No truth or SC covers reconnect-mid-transcription-with-snapshot-percent-but-no-live-progress. The primary flow (card mounted at upload completion, WS opened before the preparing event fires on a fresh back-end) sees the preparing event and the first progress event sets progressArrived.

**Classification: ADVISORY (non-blocking).** WR-01 is a reconnect-path UX refinement appropriate for a future polish pass (e.g., set `progressArrived.current = true` in the snapshot case when `event.percent > 0`, or treat snapshot `percent > 0` as a progress signal). It does NOT affect any phase must-have, success criterion, or the 05-06/05-07 plan contracts. Recording it here so it is not lost; no action required for Phase 5 closure.

### Human Verification Required

1. **Re-run UAT test 5 (gap-closure re-test) against FRESH back-end + Vite dev servers to confirm the 05-06 race fix + 05-07 duration fix resolve the two live test-5 findings**
   - **Test:** Stop any stale back-end / Vite processes (the 05-UAT.md diagnosis showed a 3-day-old back-end caused the original test-5 "nothing going on" symptom — it predated the 05-04/05-05/05-06 commits). Restart both with current code. Drop a named file via the drop zone. Watch the active card through model load + first chunk progress + completion. Check the history row's filename AND duration. Click the row to open the detail view.
   - **Expected:**
     - (05-06 race fix) After upload completes the active card shows "Preparing..." with an indeterminate moving-stripe bar — NOT "In Queue" / no bar — even if the WS connects after the orchestrator emitted `stage_changed(preparing)` (the common idle-worker case that originally produced "nothing is going on").
     - (05-06 race fix) On the first chunk progress event the card switches to "Transcribing... X%" with a determinate fill bar that does not revert to Preparing.
     - (05-07 duration fix) On completion the card fades out and the job appears in the history list with the DROPPED FILENAME (e.g. "my great video.mp4", not "source.mp4") AND a MM:SS duration (e.g. "00:42", NOT "--:--").
     - (SC-3) Clicking the row navigates to `/jobs/:id` and loads the transcript + summary panes.
     - (UI-02) No embedded video player anywhere in the detail view.
   - **Why human:** The code-level closure is fully verified: `tests/test_orchestrator.py::test_done_job_duration_s_populated` (row.duration_s non-null + positive + manifest==DB), `web/src/components/ActiveJobCard.test.tsx` (7 tests: 5 existing 05-05 + 2 new 05-06 race branches), `web/src/components/HistoryRow.test.tsx` (6 tests: 3 filename + 3 duration). All 283 BE + 32 FE tests green, tsc clean, vite build ok. However the race gap (05-06) was originally surfaced by a human in a live browser as "nothing is going on" — the live WS-connect-timing against a real back-end with real model-load + the perceptual Preparing/Transcribing display feel cannot be fully asserted in jsdom (jsdom simulates the snapshot+event sequence but cannot reproduce the real StrictMode mount→unmount→remount socket-timing race against a live orchestrator). A human re-test against fresh servers is the final confirmation that the 05-06 snapshot-authoritative fix resolves the original "nothing going on" complaint and the 05-07 duration renders MM:SS live.

The other three original human verification items (drag-and-drop upload percent bar, scroll-spy visual highlight, 2-pane detail visual proportions) already PASSED in the prior UAT rounds and are unaffected by the 05-06/05-07 changes (05-06 is FE display-derivation only on the ActiveJobCard; 05-07 adds a back-end field + FE regression-guard tests, no HistoryRow.tsx change).

### Gaps Summary

No gaps found. All 20 merged must-have truths (ROADMAP SC-1..SC-5 + plan frontmatter must_haves across 05-01..05-07) are verified against the actual codebase, including the two UAT test-5 gaps (race condition: 05-06, duration blank: 05-07) which are now genuinely closed in code with full test coverage. All gap-closure artifacts exist, are substantive, are wired, and have real data flowing. All key links are wired. Full back-end suite (283 passed) + FE suite (32 passed) + tsc clean + vite build succeed. All grep gates pass (no `<video>`, no `dangerouslySetInnerHTML`, no `FormData`, no `duplex`, no `react-router-dom`, `preparing` not in StageNameLiteral, no debt markers in modified files).

The 05-REVIEW.md WR-01 advisory (reconnect mid-transcription with snapshot percent but no live progress shows Preparing instead of Transcribing X%) is OUTSIDE the 05-06 plan's claimed must_haves and does not affect any phase must-have or success criterion — it is a non-blocking UX refinement for a future polish pass. The other REVIEW.md warnings (WR-02/03, reconnect-path edge cases) and info findings (IN-01..04) remain non-blocking as assessed in the prior verification.

The status is `human_needed` rather than `passed` because one focused human re-test of UAT test 5 against fresh servers is the final confirmation that the 05-06 race fix + 05-07 duration fix resolve the original user-reported live findings. The automated evidence for both closures is already green; the other three human items already passed in prior UAT rounds and are unaffected by the gap-closure changes.

---

_Verified: 2026-06-26T17:15:00Z_
_Verifier: Claude (gsd-verifier)_