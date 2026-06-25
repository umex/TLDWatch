---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 02b
subsystem: frontend-shell
tags: [react-router-8, createBrowserRouter, xhr-primary, useUpload, drop-zone, active-job-cards, websockets, 2-pane-detail, transcript-row, history-list]
requires:
  - "Phase 05-02a: web/ Vite scaffold + API/WS layer (client.ts idempotencyKey, ws.ts useJobEvents, jobs.ts useJobs/useJob/useTranscript/invalidateJobs/TRANSCRIBING) + CSS Design System + vitest jsdom infra (XHR+upload mock)"
  - "Phase 05-01: POST /jobs/upload raw-body streaming contract + GET /jobs/{id}/transcript (D-14) + 'uploading' JobStatus"
  - "Phase 4: WS /ws/jobs/{id}/events snapshot+live event contract (D-08)"
  - "Phase 3: Transcript / TranscriptSegment schema (codegen'd into types.ts)"
provides:
  - "web/src/App.tsx: createBrowserRouter routes / (HistoryPage) + /jobs/:id (DetailPage) inside QueryClientProvider (react-router 8, NOT react-router-dom)"
  - "web/src/main.tsx: Vite entry rendering <App/> + design-system styles.css"
  - "web/src/hooks/useUpload.ts: XHR-PRIMARY upload hook -- xhr.send(file) streams from disk without JS-heap buffering; xhr.upload.onprogress drives real 0->100 percent (D-02 literal); raw octet-stream + X-Filename + Idempotency-Key headers match 05-01; NO fetch/duplex, NO FormData"
  - "web/src/components/DropZone.tsx: full-window drag overlay + dedicated .drop-zone drop area (D-01); multi-file FIFO queue via useUpload; emits jobIds upward"
  - "web/src/components/ActiveJobCard.tsx: useJobEvents WS subscription (D-03); queued/ingesting/transcribing lifecycle + ETA gate (>=2 chunks); terminal fade-out + invalidateJobs refetch"
  - "web/src/components/HistoryList.tsx: three useJobs(terminal) merged newest-first (D-05) + 'No Transcripts Yet' empty state"
  - "web/src/components/HistoryRow.tsx: filename/date/duration; click navigates to /jobs/:id (UI-SPEC sec5)"
  - "web/src/pages/HistoryPage.tsx: composes DropZone + ActiveJobCard list + HistoryList (D-04 landing page)"
  - "web/src/pages/DetailPage.tsx: 2-pane .detail-layout (transcript 60% | summary 40%) with Back link + disabled ExportStub; useTranscript feeds TranscriptPane; no embedded media player (UI-02)"
  - "web/src/components/TranscriptPane.tsx + TranscriptRow.tsx: CSS Grid 64px|80px|1fr rows, [mm:ss] timestamp, empty speaker gutter, active prop for 05-03 scroll-spy"
  - "web/src/components/SummaryPane.tsx: exact D-08 placeholder copy"
  - "web/src/components/ExportStub.tsx: disabled 'Export (Coming Soon)' layout-stability stub (D-10)"
  - "web/src/pages/DetailPage.test.tsx: 5 tests covering UI-01 2-pane + UI-02 no-media + D-08 copy + D-10 stub"
  - "web/src/api/jobs.test.ts: useTranscript 200/404 (D-14) + useUpload progress 0->50->100 assertion proving D-02 real percent via XHR-primary"
affects:
  - "05-03: consumes TranscriptRow `active` prop + `seg-{index}` ids for the IntersectionObserver scroll-spy (UI-03); consumes invalidateJobs + the terminal-transition contract for history refetch; consumes DetailPage + HistoryPage routes for the end-to-end suite"
tech-stack:
  added: []
  patterns:
    - "XHR-primary upload (D-02 locked): XMLHttpRequest is the SINGLE upload path; xhr.upload.onprogress gives real acked-byte percent on every browser. fetch/duplex explicitly excluded (Pitfall 5) and FormData/multipart excluded (raw-body 05-01 contract)"
    - "createBrowserRouter from 'react-router' (not 'react-router-dom') -- React Router 8 merged entry (Pitfall 6)"
    - "DropZone FIFO queue: one useUpload(file) at a time via a keyed UploadController, keeping client memory stable for multi-file drops"
    - "ActiveJobCard terminal transition: on done/failed/cancelled WS event, invalidateJobs(queryClient) refetches the history cache + fade-out + onTerminal callback unmounts the card"
    - "HistoryList: three useJobs(terminal-status) calls merged + re-sorted newest-first (the API ?status= filter is single-valued)"
    - "Comment hygiene: strict grep acceptance gates (no literal '<video', 'dangerouslySetInnerHTML', 'FormData', 'duplex' substrings anywhere in source) required rewording comments so the source-level greps return 0 while the behavior is still documented"
key-files:
  created:
    - web/src/components/TranscriptPane.tsx
    - web/src/components/TranscriptRow.tsx
    - web/src/components/SummaryPane.tsx
    - web/src/components/ExportStub.tsx
    - web/src/components/DropZone.tsx
    - web/src/components/ActiveJobCard.tsx
    - web/src/components/HistoryList.tsx
    - web/src/components/HistoryRow.tsx
    - web/src/hooks/useUpload.ts
    - web/src/pages/DetailPage.tsx
    - web/src/pages/DetailPage.test.tsx
    - web/src/api/jobs.test.ts
  modified:
    - web/src/main.tsx
    - web/src/App.tsx
    - web/src/pages/HistoryPage.tsx
key-decisions:
  - "jobs.test.ts kept the .ts extension (per the plan's acceptance path `src/api/jobs.test.ts`) by using React.createElement instead of JSX -- the vitest include glob matches both .ts and .tsx, but the acceptance command names the .ts file explicitly so the extension is load-bearing."
  - "Strict source-level grep gates (no '<video', 'dangerouslySetInnerHTML', 'FormData', 'duplex' substrings) required rewording comments in DetailPage.tsx, DetailPage.test.tsx, TranscriptRow.tsx, and useUpload.ts so the literal tokens do not appear anywhere while the behavior rationale stays documented."
  - "useUpload derives the Idempotency-Key asynchronously (crypto.subtle SHA-256) before xhr.send; the test awaits the mock XHR instance via waitFor before driving xhr.upload.onprogress. React 19 schedules the setState from the XHR event callback as an async re-render, so the progress assertions use waitFor to let the DOM flush."
  - "HistoryList uses three useJobs(terminal-status) calls merged + re-sorted newest-first rather than a single unfiltered useJobs() because the GET /jobs ?status= filter is single-valued and the simple merge keeps the query cache granular per status."
requirements-completed:
  - INGEST-01
  - UI-01
  - UI-02
metrics:
  duration: "8m"
  completed: "2026-06-25"
  tasks: 2
  files: 15
---

# Phase 5 Plan 02b: App Shell + Routes + 2-Pane Detail + Drop Zone + Active Cards + XHR-Primary useUpload Summary

The FE half of the ingest vertical slice: React Router 8 routes (/ history page + /jobs/:id 2-pane detail), a full-window drag overlay + dedicated drop area driving an XHR-primary `useUpload` hook that streams the raw File body to `POST /jobs/upload` with real `xhr.upload.onprogress` percent 0->100 on every browser (locked D-02), WS-driven active-job cards that fade out and refetch the history list on terminal events, and the transcript | summary detail shell with no embedded media player anywhere.

## What Was Built

### Task 1 — App shell + routes + 2-pane detail + transcript/summary components + DetailPage test (`42ed1ef`)
- **`web/src/App.tsx`** — `createBrowserRouter` (imported from `react-router`, NOT `react-router-dom`) defining `/` -> HistoryPage and `/jobs/:id` -> DetailPage, wrapped in a `QueryClientProvider` so the 05-02a TanStack hooks resolve. `web/src/main.tsx` is the Vite entry rendering `<App/>` + the design-system `styles.css`.
- **`web/src/pages/DetailPage.tsx`** — reads `:id` from `useParams`, calls `useTranscript(id)`, renders a header with a "← Back to History" `<Link>` + the disabled `ExportStub`, then the 2-pane `.detail-layout` grid (transcript 60% | summary 40%). No embedded media player element anywhere (UI-02).
- **`web/src/components/TranscriptPane.tsx`** — renders one `TranscriptRow` per segment inside the scrollable `.transcript-pane`; shows a "Transcribing..." state when `useTranscript` returns the `TRANSCRIBING` sentinel (404, D-14) or undefined (loading).
- **`web/src/components/TranscriptRow.tsx`** — CSS Grid row `64px | 80px | 1fr` (UI-SPEC §4) with the timestamp formatted as `[mm:ss]` from `start_s`, an empty 80px speaker gutter (Phase 7 fills it), and the body as a normal React child (auto-escaped, T-05-07). Accepts an `active` prop (default false) that applies the `.active` class for 05-03's scroll-spy. Each row gets `id="seg-{index}"` for the IntersectionObserver target.
- **`web/src/components/SummaryPane.tsx`** — the exact UI-SPEC §6 placeholder copy "Summaries will appear here once summarization is enabled." in the fixed 40% `.summary-pane` (D-08 stable shape).
- **`web/src/components/ExportStub.tsx`** — a disabled "Export (Coming Soon)" button (D-10 layout-stability stub).
- **`web/src/pages/HistoryPage.tsx`** (Task 1 minimal shell, fully wired in Task 2) — drop-area + active-cards placeholders + the "No Transcripts Yet" empty state.
- **`web/src/pages/DetailPage.test.tsx`** — 5 tests: both panes present (UI-01), no `<video>` element anywhere (UI-02), `[00:12]` timestamp + body render, exact D-08 placeholder copy, disabled Export stub. Mocks `useTranscript` to return a sample Transcript.

### Task 2 — Drop zone + active cards + XHR-PRIMARY useUpload + history list/row + jobs.test (`c32f4c8`)
- **`web/src/hooks/useUpload.ts`** — XHR-PRIMARY upload hook (D-02 locked-real-percent). `new XMLHttpRequest()` -> `POST /jobs/upload` with `Idempotency-Key` (from 05-02a `idempotencyKey`, SHA-256->32 hex, T-05-10), `X-Filename`, `Content-Type: application/octet-stream`. `xhr.upload.onprogress` with `lengthComputable` drives the real acked-byte percent 0->100. `xhr.send(file)` streams the File/Blob directly from disk WITHOUT buffering the whole file in JS heap (FE-side INGEST-01 memory guarantee). fetch/duplex is NOT used (Pitfall 5) and FormData/multipart is NOT used (raw-body 05-01 contract). Returns `{ status, jobId, progress, error }`.
- **`web/src/components/DropZone.tsx`** — full-window drag overlay (global `dragenter`/`dragover`/`dragleave`/`drop` listeners; "Drop files to start transcribing" copy; #2563EB dashed border) AND a dedicated `.drop-zone` drop area (D-01). Multi-file drops queue FIFO (single-concurrency client queue per UI-SPEC §1) via a keyed `UploadController` that calls `useUpload(file)` one at a time. Emits each created jobId upward via `onJobCreated`. Shows the real percent bar in the drop-area upload indicator while a file streams up.
- **`web/src/components/ActiveJobCard.tsx`** — subscribes via `useJobEvents(jobId)` (05-02a ws.ts, D-03). Renders the lifecycle states: queued -> "In Queue" badge, ingesting -> "Ingesting File... X%", transcribing -> "Transcribing... X% (ETA: MM:SS)" with ETA hidden until >=2 chunks (Phase 4 D-09), done/failed/cancelled -> `.active-card` fade-out + `invalidateJobs(queryClient)` so the history list refetches (D-03 terminal transition) + `onTerminal` callback so HistoryPage unmounts the card. On failure: soft red border + UI-SPEC §6 error copy "Failed to transcribe video. Please check your file format and try again."
- **`web/src/components/HistoryList.tsx`** — three `useJobs("done" | "failed" | "cancelled")` calls merged and re-sorted newest-first (D-05; the API `?status=` filter is single-valued). "No Transcripts Yet" empty state when the merged list is empty (UI-SPEC Copywriting Contract).
- **`web/src/components/HistoryRow.tsx`** — filename (basename of `source_path`), date (`created_at`), duration (`duration_s` as mm:ss). Clicking navigates to `/jobs/:id` via `useNavigate` (UI-SPEC §5).
- **`web/src/pages/HistoryPage.tsx`** (Task 2 full composition) — `DropZone` (top) + `ActiveJobCard` list (the jobIds DropZone emits) + `HistoryList` (completed jobs). The landing page per D-04.
- **`web/src/api/jobs.test.ts`** — useTranscript returns the parsed Transcript on 200 and the `TRANSCRIBING` sentinel on 404 (D-14); useUpload progress assertion: firing `xhr.upload.onprogress` with `{loaded:500,total:1000}` sets progress to 50, then `{loaded:1000,total:1000}` sets it to 100 -- proving real 0->100 percent on the XHR-primary path (D-02 honored, NOT a static "Uploading..."). Also asserts the request hits `http://localhost:8000/jobs/upload` with `X-Filename` + octet-stream + 32-hex `Idempotency-Key` headers and that `fetch` is NOT called for the upload. Uses `React.createElement` to keep the `.ts` extension (the plan's acceptance path names `src/api/jobs.test.ts`).

## Verification Results

- `npx tsc --noEmit` (from `web/`) -- clean (exit 0).
- `npx vitest run` (from `web/`) -- **14 tests passed** across 3 files (6 smoke from 05-02a + 5 DetailPage + 3 jobs).
- `npx vite build` (from `web/`) -- succeeds (536 kB JS / 2.84 kB CSS, built in 389ms).
- `grep -r "<video" web/src/` -- no matches (UI-02 preserved across all new components).
- `grep -r "dangerouslySetInnerHTML" web/src/` -- no matches (T-05-07 XSS mitigation).
- `grep -c "react-router-dom" web/package.json` -- 0 (legacy package NOT installed, Pitfall 6).
- `grep -c "createBrowserRouter" web/src/App.tsx` -- 1 (React Router 8 routes wired).
- `grep -c "detail-layout" web/src/pages/DetailPage.tsx` -- 1 (2-pane grid applied).
- `grep -c "Summaries will appear here once summarization is enabled" web/src/components/SummaryPane.tsx` -- 1 (exact UI-SPEC §6 copy, D-08).
- `grep -c "Export (Coming Soon)" web/src/components/ExportStub.tsx` -- 1 (D-10 layout-stability stub).
- `grep -c "transcript-row" web/src/components/TranscriptRow.tsx` -- present (CSS Grid row class).
- `grep -c "Drop files to start transcribing" web/src/components/DropZone.tsx` -- 1 (UI-SPEC §1 overlay copy).
- `grep -c "useJobEvents" web/src/components/ActiveJobCard.tsx` -- 3 (WS subscription + comments).
- `grep -c "In Queue\|Transcribing" web/src/components/ActiveJobCard.tsx` -- 7 (UI-SPEC §2 lifecycle states).
- `grep -c "XMLHttpRequest" web/src/hooks/useUpload.ts` -- 2 (XHR-primary path).
- `grep -c "upload\.onprogress" web/src/hooks/useUpload.ts` -- 4 (real progress events).
- `grep -c "xhr.send(file)" web/src/hooks/useUpload.ts` -- 3 (raw File body streamed from disk).
- `grep -c "FormData" web/src/hooks/useUpload.ts` -- 0 (NO multipart; matches 05-01 raw-body contract).
- `grep -c "duplex" web/src/hooks/useUpload.ts` -- 0 (fetch streaming path NOT used; XHR-primary honors D-02).
- `grep -c "/jobs/upload" web/src/hooks/useUpload.ts` -- 3 (posts to the streaming endpoint).
- `grep -c "X-Filename" web/src/hooks/useUpload.ts` -- 2 (filename via header, matches 05-01 back-end route).
- `grep -c "No Transcripts Yet" web/src/components/HistoryList.tsx` -- 2 (UI-SPEC empty state).
- `grep -c "navigate.*jobs" web/src/components/HistoryRow.tsx` -- 1 (click-through to detail per UI-SPEC §5).
- Manual (deferred to `/gsd-verify-phase 5`): drag a file onto the drop zone, confirm the upload percent bar moves 0->100 (D-02 honored), confirm active card + history transition; confirm 2-pane detail renders; confirm scroll-spy (wired in 05-03).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Strict source-level grep gates rejected literal tokens in comments**
- **Found during:** Task 1 + Task 2 acceptance checks.
- **Issue:** The plan's acceptance criteria use strict `grep -c "<video"`, `grep -r "dangerouslySetInnerHTML"`, `grep -c "FormData"`, and `grep -c "duplex"` gates that must return 0 across the whole `web/src/` tree (or in `useUpload.ts` for the latter two). The behavior-rationale comments in `DetailPage.tsx`, `DetailPage.test.tsx`, `TranscriptRow.tsx`, and `useUpload.ts` contained those literal substrings ("No `<video>` element", "no dangerouslySetInnerHTML", "NO FormData / multipart", "fetch with duplex:\"half\" is NOT used"), which failed the strict greps even though the actual code never uses any of them.
- **Fix:** Reworded the comments so the literal tokens do not appear anywhere in source -- "No embedded media player element", "the unescaped-HTML API is never used", "NO multipart form wrapping", "fetch streaming is NOT used" -- while preserving the mitigation rationale. No behavior changed.
- **Files modified:** `web/src/pages/DetailPage.tsx`, `web/src/pages/DetailPage.test.tsx`, `web/src/components/TranscriptRow.tsx`, `web/src/hooks/useUpload.ts`
- **Commit:** `42ed1ef` (Task 1, the first three) and `c32f4c8` (Task 2, useUpload)

**2. [Rule 1 - Bug] jobs.test.ts JSX required .tsx but acceptance path names .ts**
- **Found during:** Task 2 -- `npx tsc --noEmit` failed with "Unterminated regular expression literal" on the JSX inside `jobs.test.ts`.
- **Issue:** The plan's acceptance command is `npx vitest run src/api/jobs.test.ts` (the `.ts` path is load-bearing), but the test file naturally wants JSX for `render(<QueryClientProvider.../>)`. The tsconfig only enables `jsx: react-jsx` for `.tsx` files.
- **Fix:** Rewrote `jobs.test.ts` to use `React.createElement` instead of JSX, keeping the `.ts` extension so the acceptance path matches. The vitest `include` glob matches both `.ts` and `.tsx`, but the acceptance command names the `.ts` file explicitly.
- **Files modified:** `web/src/api/jobs.test.ts`
- **Commit:** `c32f4c8`

**3. [Rule 1 - Bug] useUpload progress assertion raced the React 19 async re-render**
- **Found during:** Task 2 -- the useUpload progress test failed with `expected '0' to be '50'` immediately after `xhr.__progress(500, 1000)`.
- **Issue:** React 19 schedules the `setState` fired from the XHR event callback (outside React's own event system) as an async re-render, so the DOM had not yet flushed when the test read `data-progress` synchronously.
- **Fix:** Wrapped the progress assertions in `waitFor(...)` so the DOM flushes before reading `data-progress`. The assertion still proves the real 0->50->100 percent flow (D-02); only the test timing changed.
- **Files modified:** `web/src/api/jobs.test.ts`
- **Commit:** `c32f4c8`

No architectural changes (Rule 4) and no blockers. All other plan `must_haves` truths hold as written.

## Threat Mitigations (from plan `<threat_model>`)

- **T-05-07 (XSS via transcript text):** `TranscriptRow` renders `segment.text` as a normal React child (auto-escaped). No `dangerouslySetInnerHTML` anywhere in the FE -- verified by `grep -r "dangerouslySetInnerHTML" web/src/` returning 0 matches.
- **T-05-08/T-05-09 (CORS / transcript in DOM):** accepted per plan -- single-user localhost app, back-end CORS boundary holds, no FE action.
- **T-05-10 (Idempotency-Key spoofing):** `useUpload` derives the key via the 05-02a `idempotencyKey` helper (SHA-256 of `[filename]-[size]-[lastmodified]` -> 32 hex chars). Verified by the jobs.test assertion `expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f]{32}$/)`.
- **D-02 fidelity:** XHR-primary with `xhr.upload.onprogress` (real 0->100 percent) + the jobs.test progress 0->50->100 assertion. fetch/duplex explicitly excluded (verified by `grep -c "duplex" useUpload.ts` == 0) so no browser sees an indeterminate "Uploading..." label.

## Known Stubs

| File | Line | Stub | Reason | Resolved By |
|------|------|------|--------|-------------|
| `web/src/components/SummaryPane.tsx` | placeholder copy | Static "Summaries will appear here once summarization is enabled." text, no data source | Intentional per D-08 -- the summary pane stays visible at a stable 40% width with placeholder copy until Phase 8 fills it with structured summaries | Phase 8 |
| `web/src/components/ExportStub.tsx` | disabled button | Disabled "Export (Coming Soon)" button, no click handler | Intentional per D-10 -- layout-stability stub for the detail header; re-export is Phase 9 (EXPORT-01/02/03) | Phase 9 |
| `web/src/components/TranscriptRow.tsx` | 80px speaker gutter | Empty `.speaker` span, no speaker label rendered | Intentional per D-07 -- the gutter is reserved space; `TranscriptSegment.speaker` is `None` until diarization (Phase 7) | Phase 7 |
| `web/src/pages/HistoryPage.tsx` (Task 1 shell) | n/a | Task 1's minimal shell was fully replaced by Task 2's composition | Task 2 wired DropZone + ActiveJobCard list + HistoryList into the page | Task 2 (`c32f4c8`) |

None of these stubs block the plan's goal (the ingest vertical slice + 2-pane detail shell); each is an explicit deferred-phase placeholder documented in CONTEXT.md.

## Task Commits

1. **Task 1: App shell + routes + 2-pane detail + transcript/summary components + DetailPage test** -- `42ed1ef` (feat)
2. **Task 2: Drop zone + active cards + XHR-primary useUpload + history list/row + jobs.test** -- `c32f4c8` (feat)

## Self-Check: PASSED

- [x] `web/src/main.tsx`, `web/src/App.tsx` present with `createBrowserRouter` routes / and /jobs/:id
- [x] `web/src/pages/HistoryPage.tsx`, `web/src/pages/DetailPage.tsx`, `web/src/pages/DetailPage.test.tsx` present
- [x] `web/src/components/{DropZone,ActiveJobCard,HistoryList,HistoryRow,TranscriptPane,TranscriptRow,SummaryPane,ExportStub}.tsx` all present
- [x] `web/src/hooks/useUpload.ts` present with XHR-primary path (`xhr.send(file)`, `xhr.upload.onprogress`, no FormData, no duplex)
- [x] `web/src/api/jobs.test.ts` present (3 tests green incl. the D-02 0->50->100 progress assertion)
- [x] Both commit hashes exist in `git log` (`42ed1ef`, `c32f4c8`)
- [x] Full FE suite green: `tsc --noEmit` clean, `vitest run` 14/14, `vite build` ok
- [x] No `<video>`, no `dangerouslySetInnerHTML`, no `react-router-dom` package, no `FormData`/`duplex` in useUpload.ts