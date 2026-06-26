---
phase: 05-local-file-ingest-history-ui-3-pane-layout
verified: 2026-06-26T12:45:00Z
status: human_needed
score: 18/18 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 18/18
  gaps_closed:
    - "UAT test-4 gap A: history rows showed source.<ext> instead of the dropped filename -- closed by 05-04 (original_filename end-to-end)"
    - "UAT test-4 gap B: stalled 'Transcribing... 0%' bar during STT model JIT-load -- closed by 05-05 (additive stage_changed(preparing) + indeterminate Preparing state)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Re-run UAT test 4 (end-to-end vertical slice in a running browser) to confirm gap-closure fixes 05-04 and 05-05 resolve the two test-4 findings live"
    expected: "Drop a named multi-gigabyte file -> active card shows 'Preparing...' with an indeterminate moving-stripe bar during model load (gap B closed) -> on first chunk progress the card switches to 'Transcribing... X%' determinate bar -> on completion the card fades, the job appears in history, AND the history row shows the dropped filename (e.g. 'my great video.mp4'), not 'source.mp4' (gap A closed). Click the row -> detail loads transcript + summary panes with no embedded video player."
    why_human: "The code-level closure is fully verified by tests/test_original_filename.py (round-trip X-Filename -> GET /jobs/{id}.original_filename), tests/test_orchestrator.py::test_preparing_event_emitted_before_transcribing_on_production_path (preparing -> transcribing ordering), web/src/components/HistoryRow.test.tsx (3 cases: original_filename / basename fallback / unknown), and web/src/components/ActiveJobCard.test.tsx (5 cases: preparing label, stays preparing on transcribing-before-progress, switches to determinate on first progress, no-revert on late stage_changed, terminal fade). All 282 back-end + 27 FE tests are green, tsc clean, vite build ok. However the two gaps were originally surfaced by a human in a live browser (05-UAT.md test 4); the live drag-and-drop + model-load feel + visible dropped filename in history is perceptual and cannot be asserted in jsdom. A human re-test is the final confirmation that the closures resolve the original user-reported findings."
---

# Phase 5: Local File Ingest + History UI + 3-Pane Layout Verification Report

**Phase Goal:** The user can drag a local video file into the browser, watch it process in the background, and see a working 3-pane layout (history | transcript | summary) — without an embedded video player.
**Verified:** 2026-06-26T12:45:00Z
**Status:** human_needed
**Re-verification:** Yes — after gap-closure execution (05-04, 05-05) closing UAT test-4 findings A and B

## Re-verification Mode

The previous VERIFICATION.md (2026-06-25) had status `human_needed` with no `gaps:` section but a 4-item `human_verification` list. The 05-UAT.md file records the human test results: tests 1-3 passed; test 4 (end-to-end vertical slice) raised two gaps (A: history naming, B: stalled feedback). Two gap-closure plans were executed on top of the original 4 phase plans:

- **05-04** — Persist the dropped file's original filename end-to-end (migration 0009 + JobManifest/JobResponse + upload-route persistence + HistoryRow render with basename fallback). Closes UAT test-4 gap A.
- **05-05** — Additive WS-only `stage_changed(preparing)` before STT model load + indeterminate "Preparing..." bar in ActiveJobCard until the first progress event. Closes UAT test-4 gap B.

This re-verification focuses on (a) confirming the two UAT gaps are genuinely closed in the code, (b) regression-checking the 18 previously-verified truths, and (c) re-running the full automated suites. The 05-REVIEW.md code review (0 critical / 3 warnings / 4 info) is assessed against the must-haves below.

## Goal Achievement

### Observable Truths

Must-haves merged from ROADMAP SC-1..SC-5 + PLAN frontmatter (05-01, 05-02a, 05-02b, 05-03, 05-04, 05-05). Truths 1-18 are carried forward from the previous verification; truth 16 and truth 10 are updated with the gap-closure evidence.

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Drag-and-drop / file-picker upload streams a multi-gigabyte file to disk without holding it in memory; back-end writes directly to `data/jobs/<id>/source.<ext>` (SC-1, INGEST-01, D-11) | ✓ VERIFIED | `app/api/routes_jobs.py:186-200` — `async for chunk in request.stream()` + `aiofiles.open(tmp,"wb")` + `os.fsync` + `retry_windows(os.replace)` lands `source.<ext>` atomically. `tests/test_upload_memory.py` (128MB upload, tracemalloc peak < 64MB) + `tests/test_upload_stream.py` pass. FE: `web/src/hooks/useUpload.ts:66-111` `xhr.send(file)` streams the File handle directly (no JS-heap buffering; `FormData`/`duplex` grep to 0). |
| 2 | Pre-queued `'uploading'` JobStatus makes a mid-upload job invisible to the worker's `pull_next` (Pitfall 1 race prevention) | ✓ VERIFIED | `app/models/job.py:11-22` includes `"uploading"`. `app/jobs/queue.py` `enqueue` accepts `('uploading','created','queued')`; `pull_next` selects `'queued'` only. `tests/test_upload_race.py` passes. |
| 3 | `GET /jobs/{id}/transcript` returns the parsed Transcript and 404 when no `transcript.json` exists; 400 for invalid id (D-14) | ✓ VERIFIED | `app/api/routes_jobs.py` `get_transcript` validates id, 404s on missing file, returns `Transcript.model_validate_json`. `tests/test_transcript_endpoint.py` covers 200 / 404 / 400. |
| 4 | Re-dropping the same file (same Idempotency-Key) collapses to the existing job with HTTP 200, no orphan duplicate (D-11, D-07) | ✓ VERIFIED | `app/api/routes_jobs.py:169-174` reuses `resolve_or_create`; `tests/test_upload_idempotency.py` asserts first 201, second 200, same id, one row. FE `web/src/api/client.ts` derives the key via `crypto.subtle.digest("SHA-256", …)`. |
| 5 | Completed (terminal) jobs returned by `GET /jobs?status=done newest-first` (JOB-03 back-end) | ✓ VERIFIED | `tests/test_history_list.py` asserts done/failed/cancelled rows are returned newest-first and active jobs excluded. |
| 6 | The `web/` Vite dev server boots (tsc clean) and the FE codebase is scaffolded per D-12 | ✓ VERIFIED | `web/package.json` pins `react-router ^8.0.1` (no `react-router-dom`), `@tanstack/react-query`, `openapi-typescript`. `npx tsc --noEmit` exits 0; `npx vite build` succeeds (537 kB JS). |
| 7 | Vitest jsdom infra + test setup (mock IntersectionObserver/WebSocket/fetch/XHR) exist so FE tests run | ✓ VERIFIED | `web/vitest.config.ts` + `web/src/test/setup.ts`. `npx vitest run` → 27 tests pass across 6 files. |
| 8 | API layer type-correct against codegen'd OpenAPI types + `idempotencyKey` SHA-256 helper | ✓ VERIFIED | `web/src/api/types.ts` includes `uploading` enum + `original_filename?: string \| null` on JobResponse (line 659) and JobManifest (line 714). `tsc --noEmit` clean. |
| 9 | Dropping a file triggers a streaming upload to `POST /jobs/upload` with a client-derived Idempotency-Key via XHR (PRIMARY path) and the ActiveJobCard shows real streaming-to-disk PERCENT 0->100 (D-01, D-02, D-11) | ✓ VERIFIED | `web/src/hooks/useUpload.ts:66-111` — `xhr.upload.onprogress` + `xhr.send(file)`, no FormData/duplex. `web/src/api/jobs.test.ts` asserts progress 0->50->100 via `xhr.__progress`. |
| 10 | Active job cards subscribe to `/ws/jobs/{id}/events` and display status badge + progress + ETA from snapshot + live events (D-03, D-08) — UPDATED: now also shows indeterminate "Preparing..." during STT model load until first progress (05-05 gap B) | ✓ VERIFIED | `web/src/components/ActiveJobCard.tsx:38` `useJobEvents(jobId)`. The 05-05 closure adds: `progressArrived` ref (line 52, sticks on first `progress` event, resets on jobId change), `isPreparing = status === "preparing" \|\| (isTranscribing && !progressArrived.current)` (lines 120-122), "Preparing..." label (line 155), `<div className="fill indeterminate" />` branch (lines 175-179), `data-preparing` attribute (line 133). `web/src/styles.css:203-218` adds `.fill.indeterminate` + `@keyframes indeterminate-slide` (rightward-moving 25% stripe). `web/src/components/ActiveJobCard.test.tsx` — 5 tests pass (preparing label, stays preparing on transcribing-before-progress, switches to determinate on first progress, no-revert on late stage_changed, terminal fade). Back-end: `app/jobs/orchestrator.py:251-263` emits `_publish({"type":"stage_changed","stage":"preparing"})` before `_load_stt_adapter` on the production path (adapter is None) and moves `stage_changed(transcribing)` to AFTER the adapter resolves; test path (caller adapter) skips preparing. `tests/test_orchestrator.py::test_preparing_event_emitted_before_transcribing_on_production_path` + `test_preparing_event_not_emitted_on_test_path` pass. `preparing` is WS-only — NOT in `StageNameLiteral` (line 27-29 unchanged), no `update_stage` call, DB stage/status untouched. |
| 11 | Detail page at `/jobs/:id` renders a 2-pane transcript (left) \| summary (right) layout with NO `<video>` element anywhere (D-07, UI-02) | ✓ VERIFIED | `web/src/App.tsx` routes `/jobs/:id` -> DetailPage; `web/src/pages/DetailPage.tsx` uses `.detail-layout` with TranscriptPane + SummaryPane. `grep -r "<video" web/src/` returns no matches; `grep -r "dangerouslySetInnerHTML" web/src/` returns no matches. |
| 12 | Summary pane shows the exact placeholder "Summaries will appear here once summarization is enabled" (D-08) | ✓ VERIFIED | `web/src/components/SummaryPane.tsx` — exact copy present (intentional Phase 8 stub). |
| 13 | The transcript segment row nearest the viewport center is highlighted as the user scrolls (UI-03, D-09, local files only) | ✓ VERIFIED | `web/src/hooks/useScrollSpy.ts` — `IntersectionObserver` rooted at `containerRef.current`, `rootMargin: "-49% 0px -49% 0px"`, `threshold: 0`; pixel-offset fallback. `web/src/components/TranscriptPane.tsx:39,56` wires `useScrollSpy` -> `active` prop. `web/src/hooks/useScrollSpy.test.ts` (5 tests) passes. |
| 14 | Clicking a completed history row opens `/jobs/:id` and loads that job's transcript via `GET /jobs/{id}/transcript` (JOB-03 re-open, D-06, D-14) | ✓ VERIFIED | `web/src/components/HistoryRow.tsx:45` `onClick={() => navigate('/jobs/${encodeURIComponent(job.id)}')}`. `web/src/pages/DetailPage.tsx:19` `useTranscript(id ?? null)` feeds TranscriptPane. |
| 15 | Terminal WS event removes the active card and refetches the history list so the job appears in the completed list (D-03) | ✓ VERIFIED | `web/src/components/ActiveJobCard.tsx:99-105` — `invalidateJobs(queryClient)` + `setTimeout(onTerminalRef.current?.(jobId), 250)`. `web/src/pages/HistoryPage.tsx` `handleTerminal` removes the jobId from `activeJobIds`. |
| 16 | History list shows terminal jobs only, each row shows the DROPPED FILENAME (not source.<ext>) + date + duration, sorted newest-first; no search/filter in v1 (D-05, JOB-03, SC-3) — UPDATED: 05-04 gap A closes the naming defect | ✓ VERIFIED | `web/src/components/HistoryList.tsx:16-22` (terminal-only `useJobs("done"\|"failed"\|"cancelled")` merge, newest-first). `web/src/components/HistoryRow.tsx:38-40` — `const filename = job.original_filename ?? (job.source_path ? basename(job.source_path) : "unknown")` (05-04 closure: prefer the persisted dropped filename, fall back to basename(source_path), then "unknown"). `web/src/components/HistoryRow.test.tsx` — 3 tests pass (renders `vacation-final-cut.mp4` when original_filename present; falls back to `source.mp4` when null; shows `unknown` when both absent). Back-end persistence: `app/api/routes_jobs.py:208-225` writes `original_filename=x_filename` into the manifest via `model_copy(update={...})` AND into the DB row via `UPDATE jobs SET original_filename = :name WHERE id = :id` before enqueue, so an immediate `GET /jobs/{id}` returns it. `app/jobs/manifest.py:230,242` re-projects `original_filename` on every `update_stage` transition (H3+H4 invariant). `app/jobs/service.py:222,252` `list_jobs` + `get_job` SELECTs include `sa.column("original_filename")` so `_row_to_response` (job.py:185) can read it. `app/models/manifest.py:32` `JobManifest.original_filename: str \| None = None` (additive, default None keeps existing manifests loadable). `app/models/job.py:126` `JobResponse.original_filename` + `_row_to_response` projection at line 185. `migrations/0009_add_original_filename.sql` is a single `ALTER TABLE jobs ADD COLUMN original_filename TEXT` (idempotent; runner swallows duplicate-column OperationalError). `tests/test_original_filename.py` — 2 tests pass (round-trip POST /jobs/upload X-Filename "my great video.mp4" -> GET /jobs/{id} returns it + on-disk manifest carries it; POST /jobs without upload has original_filename=null). `tests/test_migration_idempotency.py` updated with version 9 in `_APPLIED_VERSIONS`. |
| 17 | Full back-end + front-end test suites are green end-to-end (the vertical slice is provable) | ✓ VERIFIED | `python -m pytest -q` → 282 passed (incl. 2 new 05-04 + 2 new 05-05 tests). `npx vitest run` → 27 passed across 6 files (incl. 3 new HistoryRow + 5 new ActiveJobCard tests). `npx tsc --noEmit` → clean. `npx vite build` → succeeds (537 kB JS / built in 3.31s). |
| 18 | Re-export UI is deferred to Phase 9 (D-10); a disabled layout-stability "Export (Coming Soon)" stub is allowed | ✓ VERIFIED | `web/src/components/ExportStub.tsx` renders a disabled "Export (Coming Soon)" button (D-10 intentional stub). SC-5 "re-export" half is intentionally deferred to Phase 9; the "re-open + see existing transcript" half is delivered by truth 14. |

**Score:** 18/18 truths verified. Both UAT test-4 gaps (A: naming, B: stalled feedback) are closed in code; the other 16 truths are regression-clean.

### Gap-Closure Verification (05-04 + 05-05)

| Gap | Plan | Root cause (from 05-UAT.md) | Closure evidence (live codebase) | Status |
| --- | --- | --- | --- | --- |
| A — history rows showed `source.<ext>` instead of the dropped filename | 05-04 | X-Filename header discarded after ext validation; manifest/DB had no original_filename field; HistoryRow rendered basename(source_path) | `migrations/0009_add_original_filename.sql` (ALTER TABLE) + `app/models/manifest.py:32` (JobManifest.original_filename) + `app/models/job.py:126,185` (JobResponse + _row_to_response projection) + `app/jobs/manifest.py:230,242` (update_stage re-projects) + `app/jobs/service.py:222,252` (list_jobs + get_job SELECTs widened) + `app/api/routes_jobs.py:208-225` (upload route persists X-Filename to manifest + DB before enqueue) + `web/src/api/types.ts:659,714` (FE types) + `web/src/components/HistoryRow.tsx:38-40` (render with fallback) + `tests/test_original_filename.py` (2 tests) + `web/src/components/HistoryRow.test.tsx` (3 tests). All pass. | ✓ CLOSED |
| B — stalled "Transcribing... 0%" bar during STT model JIT-load | 05-05 | No model-loading/preparing stage event before _load_stt_adapter; ActiveJobCard rendered a 0% determinate bar during the silent model-load + first-chunk wait | `app/jobs/orchestrator.py:251-263` (emit `stage_changed(preparing)` before `_load_stt_adapter` on production path; move `stage_changed(transcribing)` to after adapter resolves; test path skips preparing) + `web/src/components/ActiveJobCard.tsx:52,120-122,155,175-179,133` (progressArrived ref + isPreparing + "Preparing..." label + indeterminate bar branch + data-preparing attr) + `web/src/styles.css:203-218` (.fill.indeterminate + @keyframes indeterminate-slide) + `tests/test_orchestrator.py:313,401` (preparing ordering + test-path-skip tests) + `web/src/components/ActiveJobCard.test.tsx` (5 tests). All pass. | ✓ CLOSED |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `migrations/0009_add_original_filename.sql` | ALTER TABLE jobs ADD COLUMN original_filename TEXT | ✓ VERIFIED | 10-line idempotent migration; runner auto-discovers via glob. |
| `app/models/manifest.py` | JobManifest.original_filename additive field | ✓ VERIFIED | Line 32 — `original_filename: str \| None = None` (default None). |
| `app/models/job.py` | JobResponse.original_filename + _row_to_response projection | ✓ VERIFIED | Line 126 (field) + line 185 (projection). |
| `app/jobs/manifest.py` | update_stage binds original_filename (H3+H4) | ✓ VERIFIED | Line 230 (SET clause) + line 242 (param). |
| `app/jobs/service.py` | list_jobs + get_job SELECTs include original_filename | ✓ VERIFIED | Lines 222, 252 — `sa.column("original_filename")` added (05-04 deviation fix). |
| `app/api/routes_jobs.py` | upload route persists X-Filename + GET /jobs/{id}/transcript | ✓ VERIFIED | Lines 208-225 (manifest model_copy + DB UPDATE before enqueue). |
| `app/jobs/orchestrator.py` | stage_changed(preparing) before _load_stt_adapter (production path) | ✓ VERIFIED | Lines 251-263 — preparing event + transcribing moved to after adapter load. |
| `web/src/api/types.ts` | JobResponse + JobManifest include original_filename | ✓ VERIFIED | Lines 659, 714 — `original_filename?: string \| null`. |
| `web/src/components/HistoryRow.tsx` | Render original_filename with basename fallback | ✓ VERIFIED | Lines 38-40 — `job.original_filename ?? (job.source_path ? basename(job.source_path) : "unknown")`. |
| `web/src/components/ActiveJobCard.tsx` | Indeterminate Preparing... state + determinate bar after first progress | ✓ VERIFIED | progressArrived ref (line 52), isPreparing (120-122), Preparing label (155), indeterminate bar branch (175-179), data-preparing (133). |
| `web/src/styles.css` | .fill.indeterminate + @keyframes indeterminate-slide | ✓ VERIFIED | Lines 203-218 — one rule + one keyframe reusing the existing .progress-bar .fill selector. |
| `tests/test_original_filename.py` | Round-trip + null-case tests | ✓ VERIFIED | 2 tests pass. |
| `tests/test_orchestrator.py` | preparing->transcribing ordering + test-path-skip tests | ✓ VERIFIED | `test_preparing_event_emitted_before_transcribing_on_production_path` + `test_preparing_event_not_emitted_on_test_path` pass. |
| `tests/test_migration_idempotency.py` | _APPLIED_VERSIONS includes 9 | ✓ VERIFIED | Version 9 appended (05-04 deviation fix). |
| `web/src/components/HistoryRow.test.tsx` | 3 vitest cases (present / null fallback / both absent) | ✓ VERIFIED | 3 tests pass. |
| `web/src/components/ActiveJobCard.test.tsx` | 5 vitest cases (preparing / stays preparing / switches / no-revert / terminal) | ✓ VERIFIED | 5 tests pass. |
| Phase 05-01..05-03 artifacts (upload route, transcript endpoint, FE scaffold, useUpload, DropZone, ActiveJobCard, HistoryList, TranscriptPane, SummaryPane, ExportStub, useScrollSpy, DetailPage, tests) | Per previous verification | ✓ VERIFIED | All regression-checked; full suites green. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `app/api/routes_jobs.py::upload_source` | manifest.original_filename + jobs.original_filename DB column | `model_copy(update={original_filename: x_filename})` + `UPDATE jobs SET original_filename` | ✓ WIRED | routes_jobs.py:212,221-224 |
| `app/jobs/manifest.py::update_stage` | jobs.original_filename column | H3+H4 manifest->DB projection | ✓ WIRED | manifest.py:230,242 |
| `app/jobs/service.py::list_jobs/get_job` | `_row_to_response` row.original_filename | `sa.column("original_filename")` in SELECT | ✓ WIRED | service.py:222,252 + job.py:185 |
| `web/src/components/HistoryRow.tsx` | `job.original_filename` | `job.original_filename ?? basename(job.source_path) ?? "unknown"` | ✓ WIRED | HistoryRow.tsx:38-40 |
| `app/jobs/orchestrator.py` (production transcribe block) | EventBus -> WS -> ActiveJobCard | `_publish({type:stage_changed, stage:preparing})` before `_load_stt_adapter` | ✓ WIRED | orchestrator.py:260 |
| `web/src/components/ActiveJobCard.tsx` | `useJobEvents` progress event | `progressArrived` ref gates the determinate bar | ✓ WIRED | ActiveJobCard.tsx:52,69,120-122,156 |
| (all 11 key links from previous verification) | | | ✓ WIRED | Regression-checked; no link broken by gap-closure changes. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `web/src/components/HistoryRow.tsx` | `job.original_filename` | `GET /jobs?status=…` -> `list_jobs` SELECT -> `_row_to_response` (row.original_filename) -> upload route's `UPDATE jobs SET original_filename = :name` at upload time | Yes | ✓ FLOWING |
| `web/src/components/ActiveJobCard.tsx` | `event` (status / percent / eta / stage) | `useJobEvents(jobId)` -> `/ws/jobs/{id}/events` snapshot + live (incl. new `stage_changed(preparing)` on production path) | Yes | ✓ FLOWING |
| `web/src/components/HistoryList.tsx` | merged terminal arrays | `useJobs(status)` -> `GET /jobs?status=…` -> `list_jobs` DB SELECT (now includes original_filename) | Yes | ✓ FLOWING |
| `web/src/components/TranscriptPane.tsx` | `segments` | `useTranscript(id)` -> `GET /jobs/{id}/transcript` -> `Transcript.model_validate_json` | Yes | ✓ FLOWING |
| `web/src/components/SummaryPane.tsx` | (static placeholder) | n/a — intentional D-08 placeholder | n/a (Phase 8 fills it) | ℹ️ INTENTIONAL_STUB |
| `web/src/components/ExportStub.tsx` | (disabled button) | n/a — intentional D-10 layout-stability stub | n/a (Phase 9 fills it) | ℹ️ INTENTIONAL_STUB |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full back-end suite green | `python -m pytest -q` | 282 passed in 193.57s | ✓ PASS |
| 05-04 gap-closure tests | `python -m pytest tests/test_original_filename.py tests/test_migration_idempotency.py -q` | 4 passed | ✓ PASS |
| 05-05 gap-closure tests | `python -m pytest tests/test_orchestrator.py -q` | 16 passed (incl. 2 new preparing tests) | ✓ PASS |
| Phase 05 back-end tests | `python -m pytest tests/test_upload_*.py tests/test_transcript_endpoint.py tests/test_history_list.py -q` | 11 passed | ✓ PASS |
| FE type-check clean | `cd web && npx tsc --noEmit` | exit 0, no output | ✓ PASS |
| FE tests green (incl. 8 new gap-closure tests) | `cd web && npx vitest run` | 27 passed across 6 files | ✓ PASS |
| FE production build | `cd web && npx vite build` | built in 3.31s, 537 kB JS | ✓ PASS |
| UI-02 no-video gate | `grep -r "<video" web/src/` | no matches | ✓ PASS |
| XSS mitigation gate | `grep -r "dangerouslySetInnerHTML" web/src/` | no matches | ✓ PASS |
| D-02 no-FormData / no-duplex gate | `grep -c "FormData\|duplex" web/src/hooks/useUpload.ts` | 0 | ✓ PASS |
| FE types include original_filename | `grep -c "original_filename" web/src/api/types.ts` | 2 (JobResponse + JobManifest) | ✓ PASS |
| service.py SELECTs include original_filename | `grep -c "sa.column(\"original_filename\")" app/jobs/service.py` | 2 (list_jobs + get_job) | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` probes declared by the phase PLAN/SUMMARY; validation is via pytest + vitest + tsc + vite build (all run above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| INGEST-01 | 05-01, 05-02a, 05-02b, 05-05 | User can submit a local video file via drag-and-drop in the browser | ✓ SATISFIED | Streaming upload + XHR-primary useUpload + DropZone + 05-05 preparing-state feedback during model load. Tests: test_upload_stream/memory/atomic/race/idempotency + test_original_filename + jobs.test.ts + ActiveJobCard.test.tsx. |
| JOB-03 | 05-01, 05-03, 05-04 | Persist completed jobs to local history; revisit / re-export (re-export half deferred to Phase 9 per D-10) | ✓ SATISFIED (re-open half) / DEFERRED (re-export half) | test_history_list.py locks the back-end contract; HistoryList + HistoryRow (navigate to /jobs/:id) + useTranscript deliver the revisit + see-existing-transcript half. 05-04 adds original_filename persistence so the history row shows the dropped name. Re-export is intentionally Phase 9 (D-10); ExportStub is a disabled layout-stability stub. REQUIREMENTS.md traceability line 136 marks JOB-03 Phase 5 Complete. |
| UI-01 | 05-02a, 05-02b, 05-03, 05-04, 05-05 | Main working layout is 3-pane: history \| transcript \| summary (refined per D-04 to history-page + 2-pane detail) | ✓ SATISFIED | App.tsx routes `/` (HistoryPage) + `/jobs/:id` (DetailPage 2-pane .detail-layout). D-04 refinement honored. 05-04 ensures history rows show recognizable filenames. |
| UI-02 | 05-02a, 05-02b | No embedded video player; YouTube jobs show "open in YouTube" link (YouTube link-out is Phase 6) | ✓ SATISFIED | `grep -r "<video" web/src/` returns no matches; DetailPage.test.tsx asserts no media element. |
| UI-03 | 05-03 | Active transcript line is highlighted based on current scroll position (for local files only) | ✓ SATISFIED | `useScrollSpy.ts` IntersectionObserver + TranscriptPane wiring + 5 useScrollSpy tests pass. |

No orphaned requirements — REQUIREMENTS.md traceability lines (128, 136, 155-157) map exactly the five IDs the plans claim (INGEST-01, JOB-03, UI-01, UI-02, UI-03) and all are covered.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `web/src/components/SummaryPane.tsx` | 12 | Static placeholder copy (D-08 intentional) | ℹ️ Info | Phase 8 fills the summary pane; stub is documented in CONTEXT.md D-08. |
| `web/src/components/ExportStub.tsx` | — | Disabled "Export (Coming Soon)" button (D-10 intentional) | ℹ️ Info | Phase 9 adds export; stub is documented in CONTEXT.md D-10. |
| `web/src/components/TranscriptRow.tsx` | — | Empty 80px speaker gutter (D-07 intentional) | ℹ️ Info | Phase 7 fills speaker labels; stub is documented in CONTEXT.md D-07. |

No `TBD` / `FIXME` / `XXX` / `TODO` / `HACK` / `PLACEHOLDER` markers in any gap-closure-modified file (`app/api/routes_jobs.py`, `app/jobs/manifest.py`, `app/jobs/orchestrator.py`, `app/models/manifest.py`, `app/models/job.py`, `app/jobs/service.py`, `migrations/0009_add_original_filename.sql`, `web/src/components/HistoryRow.tsx`, `web/src/components/ActiveJobCard.tsx`, `web/src/styles.css`, `web/src/api/types.ts`). No unreferenced debt markers. The three stubs above are intentional, documented in CONTEXT.md, and addressed by later phases (7/8/9) — not blockers.

### 05-REVIEW.md Warnings Assessment

The code review (05-REVIEW.md) found 0 critical / 3 warnings / 4 info. The 3 warnings are all on the FE WS-reconnect path (not the primary flow):

- **WR-01**: Reconnect mid-transcription shows "Preparing..." indeterminate instead of the determinate "Transcribing... X%" bar. Root cause: `progressArrived.current` is only set in the `progress` case, not the `snapshot` case, so a reconnecting client with `percent=50` still reads as "preparing". **Assessment:** Edge case on reconnect. The phase must-haves (SC-1..SC-5) are about the primary flow (drop file -> process -> 3-pane -> history). No SC covers reconnect behavior. The 05-05 plan contract ("indeterminate Preparing... bar until the first progress event, then a determinate bar that never reverts") is met on the primary path where the first `progress` event sets the ref. The reconnect path is a UX-correctness defect, not a goal blocker. **Classification: WARNING, not BLOCKER.**
- **WR-02**: Reconnect during the model-load window shows "Ingesting File... 0%" (DB status is still "ingesting") because `preparing` is WS-only and not replayed on connect. **Assessment:** Same edge-case classification. The primary flow (card mounted at upload completion, WS opened before the preparing event fires) sees the preparing event. A reconnecting client is a refresh-during-load scenario not covered by any SC. **Classification: WARNING, not BLOCKER.**
- **WR-03**: ETA hidden after reconnect because the WS snapshot carries no `chunks_done` and `chunks` is only updated in the `progress` case. **Assessment:** Same reconnect-path edge case. ETA appears after the next live `progress` event. **Classification: WARNING, not BLOCKER.**

The 4 info findings (IN-01 redundant `!isIngesting` term, IN-02 unused `_SerialFakeAdapterAdapter` test class, IN-03 no length/charset cap on `X-Filename`, IN-04 `basename` trailing-slash fallback) are non-blocking. IN-03 is worth a future hardening pass (X-Filename is display-only, React auto-escapes, source_path is server-generated so no path traversal) but does not block the phase goal.

**None of the REVIEW.md findings block the phase's must-haves or success criteria.** They are reconnect-path UX edge cases (WR-01/02/03) and minor cleanup (IN-01..04), all appropriate for a future polish/hardening pass.

### Human Verification Required

1. **Re-run UAT test 4 to confirm gap-closure fixes 05-04 and 05-05 resolve the two test-4 findings live**
   - **Test:** Drop a named multi-gigabyte file via the drop zone in a browser with the back-end + Vite dev server running. Watch the active card through model load + first chunk progress. On completion, check the history row's filename. Click the row to open the detail view.
   - **Expected:**
     - (Gap B closed) The active card shows "Preparing..." with an indeterminate moving-stripe bar during the STT model JIT-load + first-chunk wait — NOT a stalled "Transcribing... 0%" bar.
     - (Gap B closed) On the first chunk progress event the card switches to "Transcribing... X%" with a determinate fill bar that does not revert to Preparing.
     - (Gap A closed) On completion the card fades out and the job appears in the history list with the DROPPED FILENAME (e.g. "my great video.mp4"), NOT "source.mp4".
     - (SC-3) Clicking the row navigates to `/jobs/:id` and loads the transcript + summary panes.
     - (UI-02) No embedded video player anywhere in the detail view.
   - **Why human:** The code-level closure is fully verified: `tests/test_original_filename.py` (round-trip X-Filename -> GET /jobs/{id}.original_filename), `tests/test_orchestrator.py::test_preparing_event_emitted_before_transcribing_on_production_path` (preparing -> transcribing ordering), `web/src/components/HistoryRow.test.tsx` (3 cases), `web/src/components/ActiveJobCard.test.tsx` (5 cases). All 282 back-end + 27 FE tests green, tsc clean, vite build ok. However the two gaps were originally surfaced by a human in a live browser (05-UAT.md test 4); the live drag-and-drop + model-load feel + visible dropped filename in history is perceptual and cannot be asserted in jsdom. A human re-test is the final confirmation that the closures resolve the original user-reported findings.

The other three original human verification items (drag-and-drop upload percent bar, scroll-spy visual highlight, 2-pane detail visual proportions) already PASSED in the 05-UAT.md round and are not re-listed — they are unaffected by the 05-04/05-05 changes (05-04 only adds a display field + DB column; 05-05 only adds a preparing stage event + indeterminate bar CSS).

### Gaps Summary

No gaps found. All 18 merged must-have truths (ROADMAP SC-1..SC-5 + plan frontmatter must_haves) are verified against the actual codebase, including the two UAT test-4 gaps (A: original_filename, B: preparing state) which are now genuinely closed in code with full test coverage. All gap-closure artifacts exist, are substantive, are wired, and have real data flowing. All key links are wired. Full back-end suite (282 passed) + FE suite (27 passed) + tsc clean + vite build succeed. All grep gates pass (no `<video>`, no `dangerouslySetInnerHTML`, no `FormData`, no `duplex`, no `react-router-dom`).

The 05-REVIEW.md warnings (WR-01/02/03) are reconnect-path UX edge cases that do not block any phase must-have or success criterion; they are appropriate for a future polish pass. The 4 info findings (IN-01..04) are minor cleanup, non-blocking.

The status is `human_needed` rather than `passed` because one focused human re-test of UAT test 4 is the final confirmation that the 05-04/05-05 gap-closure changes resolve the original user-reported findings in a live browser. The automated evidence for both closures is already green; the other three human items already passed in the prior UAT round and are unaffected by the gap-closure changes.

---

_Verified: 2026-06-26T12:45:00Z_
_Verifier: Claude (gsd-verifier)_