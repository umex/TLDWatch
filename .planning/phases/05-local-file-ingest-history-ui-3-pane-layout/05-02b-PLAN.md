---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 02b
type: execute
wave: 1
depends_on: [05-02a]
files_modified:
  - web/src/main.tsx
  - web/src/App.tsx
  - web/src/pages/HistoryPage.tsx
  - web/src/pages/DetailPage.tsx
  - web/src/pages/DetailPage.test.tsx
  - web/src/components/TranscriptPane.tsx
  - web/src/components/TranscriptRow.tsx
  - web/src/components/SummaryPane.tsx
  - web/src/components/ExportStub.tsx
  - web/src/components/DropZone.tsx
  - web/src/components/ActiveJobCard.tsx
  - web/src/hooks/useUpload.ts
  - web/src/components/HistoryList.tsx
  - web/src/components/HistoryRow.tsx
  - web/src/api/jobs.test.ts
autonomous: true
requirements: [INGEST-01, UI-01, UI-02]
must_haves:
  truths:
    - "The web/ app renders the history page at route / and the detail page at /jobs/:id (per D-04, D-12)"
    - "Dropping a file onto the drop zone or full-window overlay triggers a streaming upload to POST /jobs/upload with a client-derived Idempotency-Key via XHR (the PRIMARY path) and the ActiveJobCard shows real streaming-to-disk PERCENT (0->100) for every file on every browser, honoring locked D-02 literally (D-01, D-02, D-11, INGEST-01 FE half)"
    - "Active job cards subscribe to /ws/jobs/{id}/events and display status badge + progress + ETA from the snapshot + live events (D-03, Phase 4 D-08)"
    - "The detail page at /jobs/:id renders a 2-pane transcript (left) | summary (right) layout with NO <video> element anywhere (D-07, UI-02)"
    - "The summary pane shows the placeholder 'Summaries will appear here once summarization is enabled' (D-08)"
  artifacts:
    - path: "web/src/App.tsx"
      provides: "Routes / (HistoryPage) and /jobs/:id (DetailPage)"
      contains: "createBrowserRouter"
    - path: "web/src/components/DropZone.tsx"
      provides: "Full-window drag overlay + history-page drop area (D-01)"
    - path: "web/src/components/ActiveJobCard.tsx"
      provides: "WS-driven card: queued/ingesting/transcribing progress (D-03) + terminal fade-out"
    - path: "web/src/pages/DetailPage.tsx"
      provides: "2-pane transcript | summary grid layout (D-07)"
      contains: "detail-layout"
    - path: "web/src/hooks/useUpload.ts"
      provides: "XHR-PRIMARY upload hook: xhr.send(file) streams from disk without JS-heap buffering; xhr.upload.onprogress gives real 0->100 percent (D-02 literal)"
    - path: "web/src/pages/HistoryPage.tsx"
      provides: "Landing page composing DropZone + ActiveJobCard list + HistoryList (D-04)"
  key_links:
    - from: "web/src/components/DropZone.tsx"
      to: "POST /jobs/upload (05-01 back-end, request.stream())"
      via: "useUpload hook -> XHR primary, raw octet-stream body + X-Filename header"
      pattern: "/jobs/upload"
    - from: "web/src/hooks/useUpload.ts"
      to: "web/src/api/client.ts::idempotencyKey (05-02a)"
      via: "Idempotency-Key header derivation"
      pattern: "idempotencyKey"
    - from: "web/src/components/ActiveJobCard.tsx"
      to: "/ws/jobs/{id}/events"
      via: "useJobEvents WebSocket hook (05-02a)"
      pattern: "useJobEvents"
    - from: "web/src/pages/DetailPage.tsx"
      to: "GET /jobs/{id}/transcript"
      via: "useTranscript TanStack Query hook (05-02a)"
      pattern: "useTranscript"
---

<objective>
The 3-pane-refined app shell (history page + 2-pane detail) + the drop zone and active-job cards + the XHR-primary upload hook. This is the second half of the original 05-02 split; it consumes 05-02a's API layer (client.ts, ws.ts, jobs.ts), types, styles, and test infra.

Purpose: Deliver the FE half of the ingest vertical slice (drop file -> XHR streaming upload -> active card shows real per-file percent) and the detail-view shell (re-open a completed job -> transcript | summary placeholder), per D-04 (history page + 2-pane detail), D-01 (two drop entry points), D-02 (per-file upload PERCENT on every file — locked, honored literally via XHR-primary), D-03 (active cards near drop zone), D-07 (2-pane no video), D-08 (summary placeholder), D-12 (Vite + React + TS + TanStack Query + React Router 8). Runs after 05-02a (it imports the API layer + styles + test setup); runs in parallel with 05-01 (back-end) since it builds against the documented contract; integration is verified in 05-03.

Output: The two routes, the drop zone + active cards, the 2-pane detail view + transcript/summary components, the XHR-primary useUpload hook (real 0->100 percent), and the FE tests (DetailPage.test, jobs.test incl. useUpload progress assertion).
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-CONTEXT.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-VALIDATION.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-02a-SUMMARY.md
@app/api/routes_ws.py
@app/models/job.py
@app/models/transcript.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: App shell + routes + 2-pane detail view + transcript/summary components + DetailPage test (UI-01, UI-02)</name>
  <files>web/src/main.tsx, web/src/App.tsx, web/src/pages/HistoryPage.tsx, web/src/pages/DetailPage.tsx, web/src/pages/DetailPage.test.tsx, web/src/components/TranscriptPane.tsx, web/src/components/TranscriptRow.tsx, web/src/components/SummaryPane.tsx, web/src/components/ExportStub.tsx</files>
  <read_first>
    - web/src/api/jobs.ts, web/src/api/types.ts, web/src/styles.css (created in 05-02a — the hooks, types, and CSS classes this task consumes)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md (§5 routes / and /jobs/:id; §4 transcript row layout 64px|80px|1fr; §6 Summary Pane Placeholder copy "Summaries will appear here once summarization is enabled"; §6 Layout Stability Stub "Export (Coming Soon)" disabled button; Copywriting Contract — empty state heading "No Transcripts Yet")
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md (Example 5 — CSS Grid detail-layout 60%|40%; Anti-Patterns — DO NOT add a <video> element; Pattern 4 — scroll-spy hook reference for the active class, wiring in 05-03)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-VALIDATION.md (Per-Task Verification Map rows 05-02-01 DetailPage.test.tsx, 05-02-02 grep "<video"; FE tests created TDD-style in implementation tasks per INFO 4)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md (rows: DetailPage.tsx, TranscriptPane.tsx/TranscriptRow.tsx, SummaryPane.tsx, ExportStub.tsx, HistoryPage.tsx, App.tsx — UI-SPEC + RESEARCH mapping)
    - app/models/transcript.py (TranscriptSegment shape: start_s, end_s, text, speaker=None — the row renders start_s as [mm:ss], text body, leaves speaker gutter empty)
  </read_first>
  <behavior>
    - The app has two routes: / (HistoryPage) and /jobs/:id (DetailPage) via React Router 8 createBrowserRouter.
    - DetailPage renders a 2-pane grid: transcript (left, 60%) | summary (right, 40%) using the .detail-layout class — no left history pane, no <video> element.
    - TranscriptRow renders a CSS Grid row (64px timestamp | 80px speaker gutter | 1fr body) with the timestamp formatted as [mm:ss] from start_s.
    - SummaryPane renders the exact placeholder copy "Summaries will appear here once summarization is enabled".
    - ExportStub renders a disabled "Export (Coming Soon)" button (UI-SPEC §6 layout-stability stub, allowed per D-10).
    - DetailPage.test.tsx renders the 2-pane grid in jsdom and asserts both panes are present and NO <video> element exists.
  </behavior>
  <action>
    Create web/src/App.tsx with React Router 8 `createBrowserRouter` (import from "react-router", NOT "react-router-dom") defining two routes: path "/" -> HistoryPage, path "/jobs/:id" -> DetailPage. Wrap in a QueryClientProvider (05-02a's hooks need it).

    Create web/src/main.tsx: import App, createRoot, render <App/> (the Vite entry). The QueryClientProvider + RouterProvider setup lives here or in App.tsx — pick one; keep it minimal.

    Create web/src/pages/DetailPage.tsx: read :id from useParams, call useTranscript(id). Render a header with a "Back to History" button (React Router Link to "/") and the disabled ExportStub. Render the 2-pane .detail-layout: left = TranscriptPane (pass the transcript segments or a "Transcribing..." loading state when useTranscript returns 404 per UI-SPEC §6), right = SummaryPane (the placeholder). Use the Transcript type from types.ts. No <video> element anywhere (UI-02).

    Create web/src/components/TranscriptPane.tsx: takes a Transcript (or loading) prop, renders a scrollable container with one TranscriptRow per segment. Each row gets an id like `seg-{index}` (the scroll-spy in 05-03 observes these). Leave the active-class wiring for 05-03 — just render the rows with the .transcript-row class. Show a "Transcribing..." state (UI-SPEC §6) when the transcript is not ready (404).

    Create web/src/components/TranscriptRow.tsx: CSS Grid row (64px | 80px | 1fr) per UI-SPEC §4. Format start_s as [mm:ss] (zero-padded minutes:seconds). Render text in the body column. Leave the 80px speaker gutter empty (Phase 7 fills it). Accept an optional `active` boolean prop that applies the .active class (05-03 wires it; default false here).

    Create web/src/components/SummaryPane.tsx: render the exact placeholder copy from UI-SPEC §6: heading + "Summaries will appear here once summarization is enabled." Centered, low-contrast. Fixed 40% width (the grid enforces it).

    Create web/src/components/ExportStub.tsx: a disabled button with the copy "Export (Coming Soon)" (UI-SPEC §6 layout-stability stub; D-10 allows this for layout stability). Grey, non-clickable.

    Create web/src/pages/HistoryPage.tsx as a minimal shell for now (Task 2 fills the drop zone + cards + list): render the page container with a placeholder for the drop area, a placeholder for active cards, and the history list (useJobs — Task 2 wires it; here just render the empty-state copy "No Transcripts Yet" when there are no done jobs). Task 2 will compose DropZone + ActiveJobCard list + HistoryList into this page.

    Create web/src/pages/DetailPage.test.tsx: render DetailPage in jsdom (Testing Library), assert the transcript pane and summary pane are both present (query by test-id or role), and assert no <video> element exists in the container. Mock useTranscript to return a sample Transcript (segments: [{start_s:12, end_s:15, text:"hello"}]). This covers UI-01 (2-pane detail) + UI-02 (no video) per VALIDATION.md rows 05-02-01 + 05-02-02 (created TDD-style in this implementation task per INFO 4).

    Per D-04, D-07, D-08, D-10, UI-02, UI-SPEC §4/§5/§6, RESEARCH Anti-Patterns (no <video>).
  </action>
  <verify>
    <automated>cd web && npx vitest run src/pages/DetailPage.test.tsx && grep -r "<video" web/src/ || echo "NO_VIDEO_OK"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "createBrowserRouter" web/src/App.tsx` returns >= 1 (React Router 8 routes).
    - `grep -c "react-router-dom" web/src/App.tsx web/src/main.tsx` returns 0 (legacy import NOT used).
    - `grep -c "detail-layout" web/src/pages/DetailPage.tsx` returns >= 1 (2-pane grid applied).
    - `grep -c "Summaries will appear here once summarization is enabled" web/src/components/SummaryPane.tsx` returns >= 1 (exact UI-SPEC §6 copy).
    - `grep -c "Export (Coming Soon)" web/src/components/ExportStub.tsx` returns >= 1 (layout-stability stub).
    - `grep -c "transcript-row" web/src/components/TranscriptRow.tsx` returns >= 1 (CSS Grid row class).
    - `grep -r "<video" web/src/` returns no matches (UI-02 — no embedded video player anywhere).
    - `cd web && npx vitest run src/pages/DetailPage.test.tsx` exits 0 (UI-01 2-pane + UI-02 no-video verified).
    - `cd web && npx tsc --noEmit` exits 0.
  </acceptance_criteria>
  <done>DetailPage renders the 2-pane transcript|summary grid with the exact placeholder copy; DetailPage.test passes; grep finds no <video> in web/src; app routes / and /jobs/:id are wired.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Drop zone + active job cards + XHR-PRIMARY useUpload hook (real 0->100 percent per D-02) + history list/row + jobs.test (INGEST-01 FE, UI-01 history page)</name>
  <files>web/src/components/DropZone.tsx, web/src/components/ActiveJobCard.tsx, web/src/hooks/useUpload.ts, web/src/components/HistoryList.tsx, web/src/components/HistoryRow.tsx, web/src/pages/HistoryPage.tsx, web/src/api/jobs.test.ts</files>
  <read_first>
    - web/src/pages/HistoryPage.tsx, web/src/api/jobs.ts, web/src/api/client.ts, web/src/test/setup.ts (created in 05-02a/Task 1 of this plan — the shell + hooks + idempotencyKey helper + XHR mock this task composes/uses)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md (§1 Drop Zone + full-window drag overlay — trigger mechanism, overlay design "Drop files to start transcribing", multi-file FIFO queue, Idempotency-Key derivation; §2 Active-Job Card — lifecycle states queued/ingesting/transcribing, WS event mapping, terminal transition fade-out -> prepend to history; §5 history row click -> /jobs/:id)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md (Open Questions #1 RESOLVED -> 05-02b Task 2: XHR is the PRIMARY path (not fallback) so every browser shows real percent; Open Questions #2 RESOLVED -> 05-02b Task 2: real 0->100 percent via xhr.upload.onprogress on the primary path; Pitfall 4 — Firefox/Safari: XHR works on all browsers (no fetch-streaming dependency); Pitfall 5 — fetch gives no reliable progress, XHR does; Anti-Patterns — do NOT treat enqueued bytes as upload progress, use xhr.upload.onprogress; Pattern 3 — useJobs TanStack Query + invalidate on terminal WS)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-VALIDATION.md (Per-Task Verification Map row 05-03-03 jobs.test.ts — GET /jobs/{id}/transcript returns Transcript; 404 when none; FE tests created TDD-style in implementation tasks per INFO 4)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md (rows: DropZone.tsx, ActiveJobCard.tsx, HistoryList.tsx, HistoryRow.tsx, useUpload.ts — UI-SPEC + RESEARCH + back-end contract mapping)
    - app/models/job.py (JobResponse — the HistoryRow renders id, status, created_at, duration_s, source_path (filename derived))
    - app/api/routes_ws.py (snapshot + live event shapes for ActiveJobCard)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-01-PLAN.md (back-end POST /jobs/upload reads the raw body via request.stream() + X-Filename header — the FE XHR-primary path sends the raw File body to match this contract; NO multipart/FormData)
  </read_first>
  <behavior>
    - A full-window drag overlay appears on dragenter over any page and dismisses on dragleave/drop, showing "Drop files to start transcribing" (UI-SPEC §1).
    - The history page has a dedicated drop area at the top (D-01).
    - Dropping one or more files calls useUpload for each, which POSTs the RAW file body to /jobs/upload via XHR with headers {Idempotency-Key (from idempotencyKey helper), X-Filename: file.name, Content-Type: "application/octet-stream"} — NOT FormData/multipart (matches the 05-01 back-end request.stream() contract). Each file becomes a job (D-02).
    - useUpload uses XHR as the PRIMARY (and only) upload path: `xhr.send(file)` streams the File/Blob body directly from disk WITHOUT buffering the whole file in JS heap (INGEST-01 memory guarantee preserved on the FE side too); `xhr.upload.onprogress` with e.lengthComputable yields the real acked-byte percent, updating 0->100. fetch with duplex:"half" is NOT used (it gives no progress per Pitfall 5 and would show indeterminate "Uploading..." on Chrome/Edge, violating locked D-02 which requires PERCENT for every file).
    - The ActiveJobCard / DropZone surfaces this real 0->100 percent during the upload (ingesting stage on the FE side), NOT a static "Uploading..." label. (The back-end WS later relays the ingesting/transcribing stage percent per Phase 4 D-09.)
    - ActiveJobCard subscribes to /ws/jobs/{id}/events and renders: queued badge "In Queue", ingesting "Ingesting File... X%", transcribing "Transcribing... X% (ETA: MM:SS)" (ETA hidden until >=2 chunks per Phase 4 D-09), with the snapshot seeding initial state.
    - On a terminal WS event (done/failed/cancelled), the card fades out (.active-card transition from 05-02a styles.css) and the history list refetches (invalidateJobs from 05-02a jobs.ts) so the job appears in the completed list (UI-SPEC §2 terminal transition).
    - HistoryList renders completed jobs (done/failed/cancelled) newest-first; HistoryRow shows filename (derived from source_path), date (created_at), duration (duration_s); clicking a row navigates to /jobs/:id (UI-SPEC §5).
    - jobs.test.ts asserts useTranscript returns the Transcript on 200 and a "transcribing" sentinel on 404 (mocked fetch), AND asserts useUpload progress: mocking XHR (from setup.ts), firing xhr.upload.onprogress with {lengthComputable:true, loaded:500, total:1000} sets progress to 50, then loaded:1000 sets progress to 100 — proving real 0->100 percent on the primary path (D-02 honored, not a static "Uploading...").
  </behavior>
  <action>
    Create web/src/hooks/useUpload.ts with XHR as the PRIMARY (and only) upload path per locked D-02 (per-file PERCENT for every file on every browser) and RESEARCH Open Questions #1+#2 (RESOLVED -> 05-02b Task 2):
    - `const xhr = new XMLHttpRequest(); xhr.open("POST", "/jobs/upload");`
    - Set headers: `xhr.setRequestHeader("Idempotency-Key", idempotencyKey(file.name, file.size, file.lastModified))` (from 05-02a client.ts), `xhr.setRequestHeader("X-Filename", file.name)`, `xhr.setRequestHeader("Content-Type", "application/octet-stream")`.
    - `xhr.upload.onprogress = (e) => { if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100)); }` — real acked-byte percent 0->100 (Pitfall 5 mitigation: real % on XHR, never indeterminate).
    - `xhr.onload = () => { if (xhr.status === 201 || xhr.status === 200) { const body = JSON.parse(xhr.responseText); setStatus("done"); setJobId(body.id); resolve({status: "done", jobId: body.id, progress: 100, error: null}); } else { setError(xhr.statusText); } };`
    - `xhr.onerror = () => { setError("upload failed"); };`
    - `xhr.send(file)` — the browser streams the File/Blob body directly from disk WITHOUT buffering the whole file in JS heap (this is the FE-side expression of INGEST-01's memory guarantee; XHR sends the File handle, not an in-memory copy). State this explicitly in a code comment.
    - Do NOT use fetch with duplex:"half" — it provides no upload progress (Pitfall 5) and would deliver indeterminate "Uploading..." on Chrome/Edge, violating D-02's locked "percent" requirement. XHR-primary is the single clean path and works on all browsers (Firefox/Safari included — Pitfall 4 moot).
    - Return `{ status, jobId, progress, error }` where `progress` is a number 0-100 driven by xhr.upload.onprogress (the component renders `progress` as a real percent bar, NOT a static label).

    Create web/src/components/DropZone.tsx per UI-SPEC §1: a full-window drag overlay (global window dragenter/dragover listeners preventing default; overlay with #2563EB dashed border + "Drop files to start transcribing" copy; dismiss on dragleave/drop) AND a dedicated drop area at the top of the history page (D-01). On drop, capture the FileList, and for each file call useUpload (sequentially — FIFO client queue per UI-SPEC §1). Emit each created jobId to the parent (HistoryPage) so it renders an ActiveJobCard. Surface useUpload's `progress` (0-100) in the drop-area upload indicator while a file is streaming up.

    Create web/src/components/ActiveJobCard.tsx per UI-SPEC §2: takes a jobId, calls useJobEvents(jobId), renders the lifecycle states from the WS events. queued -> gray "In Queue" badge. ingesting -> progress bar "Ingesting File... X%" (the X here is the back-end WS relay of the ingesting stage per Phase 4 D-09; the FE upload percent from useUpload is shown by DropZone until the WS snapshot/ingesting events take over). transcribing -> "Transcribing... X% (ETA: MM:SS)" with ETA hidden until the snapshot/progress carries >=2 chunks (Phase 4 D-09). done/failed/cancelled -> fade-out transition (.active-card from 05-02a styles.css) + call an onTerminal callback so HistoryPage calls invalidateJobs (05-02a jobs.ts) and the card is removed. If failed, show the soft red border + UI-SPEC §6 error copy ("Failed to transcribe video. Please check your file format and try again.") before fade-out.

    Create web/src/components/HistoryList.tsx: calls useJobs() with the terminal statuses (done + failed + cancelled — one useJobs() call filtered to terminal client-side, or three useJobs(status) calls merged; pick the simpler). Render HistoryRow for each, newest-first (the API already sorts newest-first). Show the empty-state copy "No Transcripts Yet" + body from UI-SPEC Copywriting Contract when the list is empty.

    Create web/src/components/HistoryRow.tsx: renders filename (derived from source_path — basename), date (created_at formatted), duration (duration_s formatted mm:ss). Clicking the row calls navigate("/jobs/:id") via React Router (UI-SPEC §5).

    Update web/src/pages/HistoryPage.tsx to compose: DropZone (top) + active job cards list (the jobIds from DropZone's onDrop, each rendered as ActiveJobCard) + HistoryList (completed jobs). This is the landing page per D-04.

    Create web/src/api/jobs.test.ts: mock fetch (the setup.ts vi.fn mock). Test useTranscript returns the parsed Transcript when fetch returns 200 + a sample Transcript JSON; test it returns a "transcribing" sentinel (null or a loading flag) when fetch returns 404. This covers VALIDATION.md row 05-03-03 (JOB-03 re-open loads transcript). THEN add a useUpload progress assertion: using the XHR mock from setup.ts, call useUpload with a fake File, trigger xhr.upload.onprogress with {lengthComputable:true, loaded:500, total:1000}, assert progress === 50; trigger loaded:1000/total:1000, assert progress === 100. This proves D-02 is honored — real 0->100 percent on the XHR-primary path, NOT a static "Uploading..." (per RESEARCH Open Questions #1+#2 RESOLVED).

    Per D-01, D-02 (locked — real percent via XHR primary), D-03, D-11, UI-SPEC §1/§2/§5, RESEARCH Open Questions #1+#2 (RESOLVED -> 05-02b Task 2) + Pattern 2/3 + Pitfalls 4/5, Phase 4 D-08/D-09, 05-01 back-end raw-body contract.
  </action>
  <verify>
    <automated>cd web && npx vitest run src/api/jobs.test.ts && cd web && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "Drop files to start transcribing" web/src/components/DropZone.tsx` returns >= 1 (UI-SPEC §1 overlay copy).
    - `grep -c "useJobEvents" web/src/components/ActiveJobCard.tsx` returns >= 1 (WS subscription).
    - `grep -c "In Queue\|Transcribing" web/src/components/ActiveJobCard.tsx` returns >= 1 (UI-SPEC §2 lifecycle states).
    - `grep -c "XMLHttpRequest\|new XMLHttpRequest" web/src/hooks/useUpload.ts` returns >= 1 (XHR-primary path).
    - `grep -c "xhr.upload.onprogress\|upload\\.onprogress" web/src/hooks/useUpload.ts` returns >= 1 (real progress events).
    - `grep -c "xhr.send(file)" web/src/hooks/useUpload.ts` returns >= 1 (raw File body streamed from disk, not buffered in JS heap).
    - `grep -c "FormData" web/src/hooks/useUpload.ts` returns 0 (NO multipart — matches 05-01 request.stream() raw-body contract).
    - `grep -c "duplex" web/src/hooks/useUpload.ts` returns 0 (fetch streaming path NOT used — it gives no progress per Pitfall 5; XHR-primary honors D-02).
    - `grep -c "/jobs/upload" web/src/hooks/useUpload.ts` returns >= 1 (posts to the streaming endpoint).
    - `grep -c "X-Filename" web/src/hooks/useUpload.ts` returns >= 1 (filename via header, matches 05-01 back-end route).
    - `grep -c "No Transcripts Yet" web/src/components/HistoryList.tsx` returns >= 1 (UI-SPEC empty state).
    - `grep -c "navigate.*jobs\|Link.*jobs" web/src/components/HistoryRow.tsx` returns >= 1 (click-through to detail per UI-SPEC §5).
    - `cd web && npx vitest run src/api/jobs.test.ts` exits 0 (JOB-03 re-open transcript 200/404 AND useUpload progress 0->100 assertion passes — D-02 real percent verified).
    - `cd web && npx tsc --noEmit` exits 0 (full FE type-check).
    - `grep -r "<video" web/src/` returns no matches (UI-02 preserved across all new components).
  </acceptance_criteria>
  <done>DropZone + ActiveJobCard + XHR-primary useUpload (real 0->100 percent per D-02, raw body matching 05-01 request.stream(), no fetch/multipart) + HistoryList/Row compose into HistoryPage; jobs.test passes incl. the useUpload progress 0->100 assertion; full FE type-checks clean; no <video> anywhere.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser -> POST /jobs/upload | FE sends raw file bytes + client-derived Idempotency-Key + X-Filename (localhost-only) via XHR-primary |
| Browser -> /ws/jobs/{id}/events | FE opens a WebSocket per active card (localhost-only) |
| Browser -> GET /jobs, GET /jobs/{id}/transcript | FE reads job list + transcript (localhost-only) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-05-07 | Tampering | XSS via transcript text rendered in TranscriptRow | mitigate | React escapes text content by default (no dangerouslySetInnerHTML); render segment.text as a normal child. Do NOT use innerHTML/dangerouslySetInnerHTML anywhere in the FE. |
| T-05-08 | Spoofing | CORS / WS origin abuse from a rogue local page | accept | CORSMiddleware restricts allow_origins to localhost:5173 + 127.0.0.1:5173 (app/main.py, no Phase 5 change); TrustedHostMiddleware allow-lists localhost; single-user localhost-only app (PROJECT.md). No FE action — the back-end boundary holds. |
| T-05-09 | Information Disclosure | Transcript text in browser memory / DOM | accept | Single-user local app; the transcript is the user's own data displayed to the user; no cross-origin exfiltration surface (CORS locked down). |
| T-05-10 | Tampering | Idempotency-Key collision / spoofing | mitigate | FE derives the key via crypto.subtle SHA-256([filename]-[size]-[lastmodified]) truncated to 32 hex chars (05-02a client.ts, UI-SPEC §1 + RESEARCH Open Questions #3 RESOLVED -> 05-02a Task 2); back-end validate_idempotency_key enforces [A-Za-z0-9_-]{1,128} (Phase 4). |
| T-05-SC | Tampering | npm installs (already done in 05-02a) | accept | All packages OK/Approved in RESEARCH Package Legitimacy Audit; no [SUS]/[SLOP]; no blocking checkpoint needed. |

## Mitigation Traceability

- T-05-07 -> Task 1 action: "render text in the body column" (React default escaping) + acceptance criterion "grep <video returns 0" + no dangerouslySetInnerHTML (enforced by code review + the grep gate has no <video; the verification block also greps dangerouslySetInnerHTML).
- T-05-10 -> Task 2 action: useUpload sends the derived key from 05-02a client.ts::idempotencyKey (SHA-256->32 hex).
- D-02 fidelity -> Task 2 action: XHR-primary with xhr.upload.onprogress (0->100 real percent) + jobs.test progress assertion. fetch/duplex explicitly excluded so no browser sees indeterminate "Uploading...".
</threat_model>

<verification>
- `cd web && npx tsc --noEmit` — full FE type-checks clean.
- `cd web && npx vitest run` — all FE tests green (DetailPage.test, jobs.test incl. useUpload progress 0->100).
- `grep -r "<video" web/src/` returns no matches (UI-02).
- `grep -r "dangerouslySetInnerHTML" web/src/` returns no matches (XSS mitigation T-05-07).
- `grep -c "react-router-dom" web/package.json` returns 0 (legacy package not installed — Pitfall 6).
- `grep -c "FormData" web/src/hooks/useUpload.ts` returns 0 (raw octet-stream body, matches 05-01 request.stream()).
- `grep -c "duplex" web/src/hooks/useUpload.ts` returns 0 (XHR-primary; no fetch streaming indeterminate path).
- `grep -c "xhr.upload.onprogress" web/src/hooks/useUpload.ts` returns >= 1 (real 0->100 percent per D-02).
- `cd web && npm run build` succeeds (Vite production build).
- Manual (deferred to /gsd-verify-phase): drag a file onto the drop zone, confirm the upload percent bar moves 0->100 (D-02 honored), confirm active card + history transition; confirm 2-pane detail renders; confirm scroll-spy (wired in 05-03).
</verification>

<success_criteria>
- The web/ app renders / (history page) and /jobs/:id (detail page) per D-04, D-12.
- Dropping a file triggers a streaming XHR upload to POST /jobs/upload with a client-derived Idempotency-Key (raw octet-stream body + X-Filename header, matching 05-01's request.stream() contract) and the upload percent bar moves 0->100 on every browser (INGEST-01 FE half, D-01, D-02 locked-real-percent, D-11) — verified by the jobs.test useUpload progress assertion.
- Active job cards subscribe to /ws/jobs/{id}/events and show live progress (D-03, Phase 4 D-08).
- The detail page is 2-pane transcript | summary with NO <video> element (UI-01 detail, UI-02).
- The summary pane shows the exact placeholder copy (D-08).
- FE type-checks clean and all FE tests pass (incl. the D-02 real-percent assertion).
</success_criteria>

<output>
Create `.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-02b-SUMMARY.md` when done
</output>

## Artifacts this phase produces

Front-end symbols/files added by this plan (the plan-review-convergence source-grounding pass excludes these from drift verification):
- `web/src/main.tsx`, `web/src/App.tsx` (`createBrowserRouter` routes / and /jobs/:id)
- `web/src/pages/HistoryPage.tsx`, `web/src/pages/DetailPage.tsx`, `web/src/pages/DetailPage.test.tsx`
- `web/src/components/DropZone.tsx`, `ActiveJobCard.tsx`, `HistoryList.tsx`, `HistoryRow.tsx`, `TranscriptPane.tsx`, `TranscriptRow.tsx`, `SummaryPane.tsx`, `ExportStub.tsx`
- `web/src/hooks/useUpload.ts` (`useUpload(file)` — XHR PRIMARY, `xhr.send(file)` streams from disk without JS-heap buffering, `xhr.upload.onprogress` drives real 0->100 percent per D-02; raw octet-stream body + X-Filename header matches 05-01 back-end; NO fetch/duplex, NO FormData)
- `web/src/api/jobs.test.ts` (useTranscript 200/404 + useUpload progress 0->100 assertion — D-02 real percent verified)