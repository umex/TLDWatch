# Phase 5: Local File Ingest + History UI + 3-Pane Layout - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Source:** /gsd-discuss-phase 5 (interactive, default mode). The user gave concrete product-level guidance up front — two upload entry points (full-window overlay + a drop area on the history page), history on its own separate page showing filename/date/duration, history = completed jobs only (active jobs show near the drop zone), export waits for Phase 9. The one genuine spec tension (UI-01 "3-pane" vs. the user's "history on a separate page") was resolved explicitly in favor of **history page + 2-pane detail view** (D-04). Technical areas (FE stack, streaming upload mechanism, scroll-spy, visual theme, transcript endpoint) are Claude's Discretion + cross-AI review per the standing D-09/D-12 preference.

<domain>
## Phase Boundary

The **first front-end** plus the local-file ingest path. A React SPA (greenfield — no front-end exists today) where the user drags a local video file into the browser, it streams to disk and processes in the background, and the user navigates a **history index page** + a **2-pane (transcript | summary) job detail view** — with no embedded video player and a scroll-based active-line highlight. Phase 5 also adds the back-end **streaming upload endpoint** (the "other half" of Phase 4 D-04's generalized `ingested` check) and a **transcript read endpoint** the UI consumes. The job spine (queue, state machine, WebSocket progress, idempotent submit, cancel) all shipped in Phase 4 and is reused as-is.

In scope (ROADMAP success criteria SC-1..SC-5, requirements INGEST-01, JOB-03, UI-01, UI-02, UI-03):
- A **streaming drag-and-drop upload** that streams a multi-gigabyte file to disk **without holding it in memory**; the back-end writes directly to `data/jobs/<id>/source.<ext>` (SC-1, INGEST-01). Two entry points: a full-window drag overlay (any page) and a drop area at the top of the history page.
- A **history index page** (separate route, the landing page) listing **completed (terminal) jobs** — filename, date, duration — newest-first. Clicking a row opens the detail view with that job's transcript loaded (SC-3, JOB-03, and the "see existing transcript" half of SC-5).
- A **2-pane job detail view**: transcript (left) | summary (right). Transcript renders **one row per `TranscriptSegment` with the timestamp on the left** (e.g. `[00:12] …`). Summary pane shows a **placeholder empty state** (Phase 8 fills it). **No embedded video player** anywhere (UI-02).
- **Active-line highlight** based on scroll position (local files only, UI-03) — the segment nearest the viewport anchor is highlighted.
- **Active/queued/in-progress jobs are NOT in the history list**; their live progress (status, %, ETA) shows as cards **near the drop area** on the history page, driven by the existing per-job WebSocket.
- A **transcript read endpoint** serving a job's `transcript.json` to the front-end (D-14 — does not exist yet).
- Re-export is **out of Phase 5** (D-10 → Phase 9).

Out of scope for Phase 5:
- YouTube URL submit / yt-dlp / playlist fan-out / pause-resume / timestamp link-out to YouTube (Phase 6 — the drop zone is **local-file only** in Phase 5; a URL input is a Phase 6 addition).
- Diarization / speaker labels / chip bar / per-line reassign (Phase 7 — the transcript row leaves space for a speaker label but renders none yet).
- LLM summarization / the four templates / summary content (Phase 8 — the right pane is a placeholder empty state until then).
- Transcript inline editing / find-replace text / Markdown export / re-export (Phase 9 — D-10).
- Settings panel / quality preset / per-category model overrides / first-run card / HF token UI (Phase 10).
- Dark mode, responsive/mobile (Out of Scope — PROJECT.md: desktop browser only).
- A rich job-detail metadata panel — the user explicitly does not want one ("I don't care about the details of the job … easy to implement later if needed"); only the minimal click→load-transcript ships (D-06).
- Mid-transcription resume / checkpointing (Phase 4 D-02 — rejected for MVP).

</domain>

<decisions>
## Implementation Decisions

### Upload & new-job flow (SC-1, INGEST-01)
- **D-01:** Two ingest entry points — a **full-window drag overlay** (works on any page) **AND** a **dedicated drop area at the top of the history page** (the landing page). Dropping file(s) starts a new job; the job appears as an active card near the drop area. *(User explicit.)*
- **D-02:** **Per-file upload progress** is shown for every file (streaming-to-disk percent). Multiple files in one drop are accepted → each becomes a job; extras **queue** (worker=1 serial FIFO, Phase 4 D-10 — one job runs at a time). *(User explicit.)*
- **D-03:** Active/queued/in-progress jobs are **not** in the history list. Their live progress (status badge, transcribing %, ETA) renders as **cards near the drop area** at the top of the history page, subscribed to the existing per-job WebSocket `/ws/jobs/{id}/events` (Phase 4 D-08). When a job reaches a terminal state (`done`/`failed`/`cancelled`) it leaves the active area and appears in the completed history list below. *(User explicit: "History = completed only.")*

### History page (JOB-03, SC-3)
- **D-04:** History is a **separate page** (the landing route), NOT the left pane of a 3-pane working view. **This REFINES UI-01**: the "3-pane: history | transcript | summary" requirement is implemented as a **history index page** + a **2-pane (transcript | summary) job detail view**. *(User explicit, chose this over the literal UI-01 3-pane reading. Downstream agents MUST respect this refinement and not re-litigate UI-01.)*
- **D-05:** The history list shows **completed (terminal) jobs only** — `done`, `failed`, `cancelled`. Each row shows **filename, date, duration** (user explicit). Sort newest-first (`GET /jobs` API default, `created_at DESC`). No rich job-detail metadata, no search/filter in v1.
- **D-06:** Clicking a completed history row opens the 2-pane detail view with that job's existing transcript loaded (satisfies SC-3 + the "see existing transcript" half of SC-5). Kept **minimal** — no extra job-detail metadata UI. *(User: "I don't care about the details of the job … easy to implement later if needed.")* Richer detail views are deferred.

### Working/detail view — 2-pane (UI-02, UI-03)
- **D-07:** The job detail view is **2-pane: transcript (left) | summary (right)** — no left history pane, **no embedded video player** (UI-02). Transcript renders **one row per `TranscriptSegment` with the timestamp on the left** (e.g. `[00:12] text`). This gives discrete lines for the scroll-based active-line highlight (UI-03) and is the simplest rendering. *(User explicit; paragraph-merging / hover-timestamps rejected — would make scroll-highlight fuzzy.)*
- **D-08:** The summary (right) pane shows a **placeholder empty state** ("Summaries will appear here once summarization is enabled") and **stays visible from day one**. Phase 8 fills it with structured summaries. Hiding the pane until summaries exist was rejected — keep the 2-pane shape stable. *(User explicit.)*
- **D-09 [locked by spec, mechanism = Claude's Discretion]:** Active-line highlight (UI-03) is **scroll-position based, local files only**. The segment row nearest the viewport anchor (top or center — Claude picks via e.g. an `IntersectionObserver` scroll-spy) is highlighted so the user can locate context. There is **no video player and no click-to-seek on local files in v1** (REQUIREMENTS notes); YouTube timestamp link-out is Phase 6 (TRANS-08).

### Re-export (SC-5 scope split)
- **D-10:** **No export UI in Phase 5.** SC-5's "re-export it" clause is **deferred to Phase 9** (EXPORT-01/02/03). Phase 5 delivers only the "re-open a completed job and see its existing transcript" half of SC-5. Do not ship an Export button — not even a disabled stub unless the planner wants one for layout stability (default: none). *(User: "Export can wait till phase 9.")*

### Streaming upload endpoint (SC-1) — Claude's Discretion
- **D-11 [Claude's Discretion + cross-AI review]:** The browser upload **streams the file to disk without holding it in memory** (SC-1) — a new **streaming upload endpoint** writes directly to `data/jobs/<id>/source.<ext>` (stream to `source.<ext>.tmp` → `os.replace`, atomic per Phase 1 D-04, so a crashed upload leaves no partial file the orchestrator picks up). The existing `POST /jobs` takes `source_path` (Phase 4 local-reference-in-place); a browser can't supply a server path, so Phase 5 adds a streaming route (exact mechanism — chunked streaming body vs. multipart streamed by FastAPI — is the researcher/planner's call). The **generalized `ingested` check** (Phase 4 D-04) already accepts the in-job-dir `source.<ext>` variant, so the orchestrator picks the job up as-is once the file lands. `source_sha256` stays optional/best-effort (Phase 4 D-04). This is the "other half" of D-04 that Phase 4 explicitly deferred to Phase 5. The upload uses the existing **Idempotency-Key** path (Phase 4 D-07) so a re-drop mid-upload collapses to the existing job.

### Front-end toolchain (first UI) — Claude's Discretion
- **D-12 [Claude's Discretion + cross-AI review]:** Greenfield React front-end (none exists today — no package.json/vite/tsconfig/index.html). Recommended stack: **Vite + React + TypeScript**, TS types generated from the FastAPI OpenAPI schema via **`openapi-typescript`** (the codegen Phase 1/2 already accounted for — "openapi-typescript codegen sees the same model"). Server state via **TanStack Query**; routing via **React Router** (history page `/`, job detail `/jobs/:id`); native browser **WebSocket** for `/ws/jobs/{id}/events`. Exact versions/pins to the researcher. The front-end is a **separate codebase** from the Python back-end (PROJECT.md: FE/BE separated, communicate via HTTP/WebSocket; **the back-end is the only thing that touches models + the filesystem** — the browser never writes to disk directly).

### Visual style (first UI) — Claude's Discretion
- **D-13 [Claude's Discretion]:** Clean, **minimal** theme — no heavy design-system dependency. The user is non-technical and steers "as simple as possible"; look/feel is deferred to Claude with a stated default (light, neutral palette, system font stack, modest spacing). **Dark mode is not a v1 requirement** (PROJECT.md is desktop-browser-only; no dark-mode requirement stated) — defer unless the user asks. Cross-AI reviewers may pressure-test.

### Transcript serving — integration note
- **D-14 [Claude's Discretion]:** The front-end needs to read a job's transcript. `transcript.json` lives at `data/jobs/<id>/transcript.json` (Phase 3) but there is **no `GET /jobs/{id}/transcript` endpoint yet** — Phase 5 adds a read endpoint that serves the parsed `Transcript` (Phase 3 schema). The planner decides the exact route/shape; it must return the existing `Transcript`/`TranscriptSegment` Pydantic model (lax-output, Phase 1 D-15) and **404 when the job has no transcript yet** (still queued/transcribing) so the detail view can show a "transcribing…" state.

### Carried forward from earlier phases (locked — not re-asked)
- **Phase 4 D-04:** generalized `ingested` check = "`manifest.source_path` resolves OR a `source.<ext>` exists in the job dir." Phase 5 implements the **in-job-dir `source.<ext>` half** (browser upload); Phase 4 already implemented the `source_path` local-reference half.
- **Phase 4 D-07:** Idempotency via client `Idempotency-Key` HTTP header on `POST /jobs` — the upload flow sends a client-generated key so a re-drop mid-upload doesn't create a duplicate.
- **Phase 4 D-08:** per-job WebSocket `GET /ws/jobs/{id}/events` — snapshot-on-connect (`{type:"snapshot", stage, percent, eta, status}`) then live events (`stage_changed`, `progress` with `percent`+`eta_s`, `done`, `failed`, `cancelled`). The front-end's WS client subscribes here for active-job cards (D-03).
- **Phase 4 D-09:** progress/ETA granularity — per-stage binary for `ingesting` (0→100), per-chunk percent for `transcribing`; ETA hidden until ≥2 chunks. The UI renders these as-is (no client-side ETA computation).
- **Phase 4 D-10:** worker=1 serial FIFO — one job at a time. Multi-file drops queue (D-02).
- **Phase 4 D-03:** interrupted jobs marked `failed` with the source name preserved → findable in history (failed rows appear in the terminal history list per D-05).
- **Phase 4 D-06:** cancel is cooperative + idempotent; queued=instant, running=cooperative (stops at the next chunk boundary). The active card / detail view may expose a Cancel button calling `POST /jobs/{id}/cancel`.
- **Phase 3:** `Transcript`/`TranscriptSegment` schema (`start_s`, `end_s`, `text`, `speaker=None`, `confidence`). `speaker` stays `None` until Phase 7; the transcript row leaves space for a speaker label but renders none yet.
- **Phase 1 D-04/D-05/D-11/D-12/D-15:** atomic writes, rich manifest, file-as-truth stage mapping, lax-output models. The streaming upload writes atomically; the orchestrator picks the job up via the file-as-truth `ingested` check.
- **Standing project preferences:** "as simple as possible" (user), space management (user — streaming-to-disk is its expression here), **cross-AI review codex+gemini** (user-requested; Phase 3 D-09 / Phase 4 D-12), user **defers ML/technical specifics** to Claude + reviewers.

### Claude's Discretion
D-11 (streaming upload mechanism), D-12 (exact FE stack versions/pins + state mgmt + routing + WS client), D-13 (visual theme details), D-14 (transcript read endpoint route/shape), D-09's exact scroll-spy mechanism, and whether to show a disabled Export placeholder (D-10 default: none). All recorded with a rationale + recommended default above; cross-AI review pressure-tests them.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher/planner/executor) MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — FE/BE separated (React + Python, communicate via HTTP/WebSocket), **back-end is the only thing that touches models + the filesystem** (the browser never writes to disk — it streams to a back-end endpoint), single-user no-auth (no auth on the upload/WS/control endpoints), no-telemetry, **desktop-browser-only** (no mobile/responsive/dark-mode requirement), space management, "as simple as possible" steer, 3-pane + no-embedded-video intent (refined by D-04).
- `.planning/REQUIREMENTS.md` — Phase 5 owns `INGEST-01` (drag-and-drop local file upload), `JOB-03` (persist completed jobs to local history; revisit/edit/re-export — the re-export half is Phase 9 per D-10), `UI-01` (3-pane layout — **refined per D-04** to history page + 2-pane detail), `UI-02` (no embedded video player), `UI-03` (active-line highlight scroll-based, local files only). Traceability lines 128, 136, 155–157.
- `.planning/ROADMAP.md` — Phase 5 goal, mode (mvp), success criteria SC-1..SC-5, plans 05-01 / 05-02 / 05-03.
- `.planning/STATE.md` — "ready to plan Phase 5"; no Phase-5 blockers flagged (ROCm / yt-dlp / pyannote / LLM concerns are Phase 2/6/7/8).

### Prior phase context
- `.planning/phases/04-job-orchestrator-persistent-queue-websocket-progress/04-CONTEXT.md` — D-04 (generalized `ingested` check — Phase 5 fills the `source.<ext>` half), D-07 (Idempotency-Key), D-08 (per-job WS endpoint + event types + snapshot), D-09 (progress/ETA granularity), D-10 (worker=1 serial), D-03 (interrupted jobs findable in history), D-06 (cooperative idempotent cancel).
- `.planning/phases/03-stt-adapter-audio-chunker-standalone-cli/03-CONTEXT.md` — `Transcript`/`TranscriptSegment` schema; `STTAdapter` writes `transcript.json`; the `transcribing` stage the UI watches.
- `.planning/phases/01-back-end-skeleton-storage-data-layout/01-CONTEXT.md` — D-04 atomic writes, D-05 rich manifest, D-11/D-12 file-as-truth + `ingested` check, D-15 lax-output models.

### Existing code (the seams Phase 5 plugs into)
- `app/api/routes_jobs.py` — `POST /jobs` (`CreateJobRequest`: `source_type`, `source_path`; strict, `extra="forbid"`; `Idempotency-Key` header), `GET /jobs` (list newest-first, `?status=` / `?limit=` / `?offset=`), `GET /jobs/{id}`, `POST /jobs/{id}/cancel`. Phase 5 adds the **streaming upload route** (D-11) and a **transcript read route** (D-14); the front-end consumes these.
- `app/api/routes_ws.py` — `GET /ws/jobs/{job_id}/events` (snapshot + live relay of `stage_changed`/`progress`/`done`/`failed`/`cancelled`). The front-end WS client subscribes here for active-job cards (D-03). **No back-end WS work for Phase 5** — it already ships; verify CORS/origin allows the Vite dev server.
- `app/models/job.py` — `CreateJobRequest` (strict-in), `JobResponse` (`id`, `status`, `created_at`, `source_type`, `source_path`, `current_stage`, `duration_s`, `language`, `summary_kinds`, `updated_at`, `error`). The FE's TS types are codegen'd from this via OpenAPI.
- `app/models/manifest.py` — `JobManifest` (rich on-disk snapshot; `source_path`, `source_type`, `duration_s`, `language`, `summary_kinds`, `diarization_enabled`).
- `app/models/transcript.py` — `Transcript` / `TranscriptSegment` (`start_s`, `end_s`, `text`, `speaker=None`, `confidence`). The transcript pane renders these (D-07); `speaker` stays `None` until Phase 7.
- `app/jobs/service.py` — `create_job` / `list_jobs` / `get_job` (the upload route extends `create_job` or a sibling; `list_jobs` feeds the history page — terminal jobs via `?status=` filter or client-side filtering).
- `app/api/idempotency.py` — `resolve_or_create` (the Idempotency-Key path the upload flow reuses, D-07).
- `app/storage/fs.py` — `job_dir(settings, id)`, `validate_source_ext` — the streaming upload writes into `job_dir(settings, id)/source.<ext>`.
- `app/storage/atomic.py` — `atomic_write_json` (the streaming upload should land `source.<ext>` atomically — stream to `.tmp` → `os.replace`).
- `app/main.py` — OpenAPI served at `/openapi.json` (the codegen source); **Phase 5 adds CORS** for the Vite dev origin (localhost:5173 or configured port) so the separate FE dev server can call the back-end.
- `pyproject.toml` — back-end dependency policy (the FE is a **separate `package.json`** in a `web/` or `frontend/` dir; `openapi-typescript` codegen already anticipated per Phase 1/2 CONTEXT).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/api/routes_ws.py` — the WS endpoint + snapshot contract already ship; the FE just connects. The `{type:"snapshot", stage, percent, eta, status}` + live event shapes are the exact active-card data (D-03).
- `app/models/job.py::JobResponse` + `app/models/transcript.py::Transcript` — already the exact shapes the FE needs; `openapi-typescript` turns them into TS types. **No new back-end models** for the history/transcript rendering.
- `app/jobs/service.py::list_jobs` (newest-first, `?status=` filter, `?limit=`/`?offset=`) — feeds the history page (terminal jobs: filter to `done`/`failed`/`cancelled` server-side or client-side).
- `app/api/idempotency.py::resolve_or_create` — the upload flow sends a client `Idempotency-Key` so a re-drop mid-upload collapses to the existing job (no duplicate, Phase 4 D-07).
- `app/jobs/cleanup.py::cancel_job` + the cooperative `queue.cancel` path — a Cancel button on the active card / detail view is a thin call to `POST /jobs/{id}/cancel` (Phase 4 D-06).

### Established Patterns
- **Strict input / lax output at the API boundary** (Phase 1 D-15) — new upload request models are strict-in; `JobResponse`/`Transcript` stay lax-out.
- **Atomic writes** (Phase 1 D-04) — the streaming upload lands `source.<ext>` atomically (`.tmp` → `os.replace`) so a crashed upload leaves no partial file the orchestrator would pick up.
- **File-as-truth** (Phase 1 D-11/D-12 + Phase 4 D-04) — the orchestrator picks the job up once `source.<ext>` exists; the upload route finishes writing then signals the `ingested` stage transition (via the existing `update_stage`, not a raw HTTP call).
- **Back-end is the only thing that touches the filesystem** (PROJECT.md) — the browser never writes to disk; it streams to a back-end endpoint.
- **openapi-typescript codegen from the FastAPI OpenAPI schema** (Phase 1/2) — the FE's TS types come from the live schema at `/openapi.json`, not hand-written.
- **Lazy in-body imports + package boundary checks** (Phase 2/3) — the FE does not import any back-end ML library; it only talks HTTP/WebSocket. (The back-end boundary checks — e.g. `grep -rE 'from faster_whisper' app/` matches only `app/models/stt` — stay intact; Phase 5 adds no new back-end ML imports.)

### Integration Points
- New **back-end** routes Phase 5 CREATES: a **streaming upload endpoint** (e.g. `POST /jobs/{id}/source` or a combined submit+stream route) writing `data/jobs/<id>/source.<ext>` without buffering in memory (SC-1, D-11); a **`GET /jobs/{id}/transcript`** endpoint serving the parsed `Transcript` (D-14, 404 when none); **CORS** in `app/main.py` for the Vite dev origin. The upload route drives the `ingested` stage transition through `app/jobs/manifest.py::update_stage`.
- New **front-end** codebase Phase 5 CREATES (greenfield): a `web/` (or `frontend/`) dir with `package.json` (Vite + React + TS), an `openapi-typescript` codegen script (reads `/openapi.json`), React Router routes (`/` history page, `/jobs/:id` detail), the drop zone + active-job cards (WS-driven, D-03), the 2-pane detail view (D-07), the transcript segment list + scroll-spy (D-09), and a WS client hook for `/ws/jobs/{id}/events`.
- Downstream: Phase 6 adds the **YouTube URL submit** path (a URL input alongside the drop zone) + timestamp link-out in the transcript pane; Phase 7 fills the **speaker label** column in each transcript row + the speaker chip bar; Phase 8 fills the **summary** right pane (replacing the D-08 placeholder); Phase 9 adds **inline editing** + the **export** button (the deferred re-export, D-10); Phase 10 adds the **settings** UI.

</code_context>

<specifics>
## Specific Ideas

- **"As simple as possible" is the standing steer** (user) — the first UI is a clean minimal shell, not a feature-rich app. Where two implementations satisfy a success criterion, pick the simpler; defer the cleverer (rich job-detail panel, search/filter, dark mode, export stub).
- **History = completed jobs only, separate page, rows show filename/date/duration** — the user was explicit and uninterested in richer job detail ("I don't care about the details of the job"). Active jobs live near the drop zone, not in history.
- **The 3-pane requirement (UI-01) is implemented as history-page + 2-pane detail (D-04)** — the user explicitly chose this over a literal left-pane history. Downstream agents MUST respect this refinement and not re-litigate UI-01.
- **Re-export is Phase 9** — do not build export in Phase 5 (D-10). SC-5 splits: "re-open + see existing transcript" = Phase 5; "re-export" = Phase 9.
- **Space management** (standing principle): the upload streams to disk (no full-file memory buffer) per SC-1; consistent with Phase 4 D-04 (reference-in-place, no duplication) and D-05 (delete YouTube audio after transcription — Phase 6).
- **User defers ML/technical specifics**; **cross-AI review (codex+gemini) is a standing preference** — run it on the Phase 5 plans after `/gsd-plan-phase 5` and on the implementation after execution (Phase 3 D-09 / Phase 4 D-12). Do not treat Claude's D-11..D-14 as above review — they are the starting position the reviewers should pressure-test.
- **The user's "open previous transcripts later" remark** is already covered by the minimal click→load-transcript (SC-3/SC-5, D-06) — kept as simple as possible; anything richer is deferred.

</specifics>

<deferred>
## Deferred Ideas

- **Re-export / Markdown export** — Phase 9 (EXPORT-01/02/03). D-10. SC-5's "re-export" half.
- **YouTube URL submit / yt-dlp / playlist fan-out / pause-resume / timestamp link-out** — Phase 6 (the drop zone is local-file only in Phase 5; a URL input lands in Phase 6 alongside the drop zone).
- **Speaker labels / chip bar / per-line reassign / find-replace speaker** — Phase 7 (the transcript row leaves space but renders no speaker yet).
- **Summary content in the right pane** — Phase 8 (placeholder empty state until then, D-08).
- **Inline transcript editing / find-replace text / Markdown export with edits applied** — Phase 9.
- **Settings panel / quality preset / per-category model overrides / first-run card / HF token UI** — Phase 10.
- **Dark mode / responsive / mobile** — Out of Scope (PROJECT.md: desktop browser only).
- **Rich job-detail metadata view** — the user said "easy to implement later if needed"; not in Phase 5 beyond the minimal click→load-transcript (D-06).
- **History search / filter / pagination beyond the API's `?limit`/`?offset`** — not requested; "as simple as possible." Future if the list grows large.
- **Content-hash idempotency (same source file → reuse existing job)** — future option (Phase 4 D-07); Phase 5 uses the client `Idempotency-Key` header.
- **"Keep YouTube audio after transcription" toggle** — future settings option (Phase 10); default is delete (Phase 4 D-05).
- **Global WebSocket stream (`/ws/events` for all jobs)** — future; MVP is per-job (Phase 4 D-08). The history page's active cards each open their own per-job WS.

</deferred>

---

*Phase: 5-Local File Ingest + History UI + 3-Pane Layout*
*Context gathered: 2026-06-23 via /gsd-discuss-phase (interactive, default mode; product gray areas resolved by explicit user guidance — two upload entry points, history on a separate page showing filename/date/duration, history = completed only with active jobs near the drop zone, export deferred to Phase 9, UI-01 refined to history-page + 2-pane detail; technical areas Claude's Discretion + cross-AI review per D-09/D-12)*