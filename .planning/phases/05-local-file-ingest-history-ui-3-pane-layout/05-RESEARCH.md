# Phase 5: Local File Ingest + History UI + 3-Pane Layout - Research

**Researched:** 2026-06-23
**Domain:** Greenfield React SPA + FastAPI streaming upload + scroll-spy transcript
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Two ingest entry points — a full-window drag overlay (works on any page) AND a dedicated drop area at the top of the history page (the landing page). Dropping file(s) starts a new job; the job appears as an active card near the drop area.
- **D-02:** Per-file upload progress shown for every file (streaming-to-disk percent). Multiple files in one drop are accepted → each becomes a job; extras queue (worker=1 serial FIFO, Phase 4 D-10).
- **D-03:** Active/queued/in-progress jobs are NOT in the history list. Their live progress (status badge, transcribing %, ETA) renders as cards near the drop area, subscribed to the existing per-job WebSocket `/ws/jobs/{id}/events` (Phase 4 D-08). Terminal jobs leave the active area and appear in the completed history list below.
- **D-04:** History is a SEPARATE page (the landing route `/`), NOT the left pane of a 3-pane working view. This REFINES UI-01: implemented as a history index page + a 2-pane (transcript | summary) job detail view. Downstream agents MUST respect this and not re-litigate UI-01.
- **D-05:** History list shows completed (terminal) jobs only — `done`, `failed`, `cancelled`. Each row shows filename, date, duration. Sort newest-first. No rich job-detail metadata, no search/filter in v1.
- **D-06:** Clicking a completed history row opens the 2-pane detail view with that job's existing transcript loaded. Kept minimal — no extra job-detail metadata UI.
- **D-07:** The job detail view is 2-pane: transcript (left) | summary (right) — no left history pane, NO embedded video player (UI-02). Transcript renders one row per `TranscriptSegment` with the timestamp on the left (e.g. `[00:12] text`).
- **D-08:** The summary (right) pane shows a placeholder empty state ("Summaries will appear here once summarization is enabled") and stays visible from day one. Phase 8 fills it.
- **D-09:** Active-line highlight (UI-03) is scroll-position based, local files only. The segment row nearest the viewport anchor is highlighted. No video player, no click-to-seek on local files in v1.
- **D-10:** No export UI in Phase 5. SC-5's "re-export" clause is deferred to Phase 9. Do not ship an Export button — not even a disabled stub unless the planner wants one for layout stability (default: none). (UI-SPEC §6 specifies a disabled "Export (Coming Soon)" stub for layout stability —this is an allowed exception per D-10's "unless the planner wants one" clause.)
- **D-11:** The browser upload streams the file to disk without holding it in memory (SC-1) — a new streaming upload endpoint writes directly to `data/jobs/<id>/source.<ext>` (stream to `source.<ext>.tmp` → `os.replace`, atomic). The existing `POST /jobs` takes `source_path`; a browser can't supply a server path, so Phase 5 adds a streaming route. The generalized `ingested` check (Phase 4 D-04) already accepts the in-job-dir `source.<ext>` variant. The upload uses the existing Idempotency-Key path (Phase 4 D-07).
- **D-12:** Greenfield React front-end. Recommended stack: Vite + React + TypeScript, TS types generated from the FastAPI OpenAPI schema via `openapi-typescript`. Server state via TanStack Query; routing via React Router (history page `/`, job detail `/jobs/:id`); native browser WebSocket for `/ws/jobs/{id}/events`. The front-end is a SEPARATE codebase from the Python back-end (PROJECT.md: FE/BE separated; the back-end is the only thing that touches models + the filesystem).
- **D-13:** Clean, minimal theme — no heavy design-system dependency. Light, neutral palette, system font stack, modest spacing. Dark mode is not a v1 requirement.
- **D-14:** The front-end needs a read endpoint for a job's transcript. `transcript.json` lives at `data/jobs/<id>/transcript.json` (Phase 3) but there is no `GET /jobs/{id}/transcript` endpoint yet — Phase 5 adds one returning the parsed `Transcript` (Phase 3 schema). Must 404 when the job has no transcript yet so the detail view can show a "transcribing…" state.

### Claude's Discretion
D-11 (streaming upload mechanism — chunked streaming body vs. multipart streamed by FastAPI), D-12 (exact FE stack versions/pins + state mgmt + routing + WS client), D-13 (visual theme details), D-14 (transcript read endpoint route/shape), D-09's exact scroll-spy mechanism, and whether to show a disabled Export placeholder (D-10 default: none; UI-SPEC §6 opts in for layout stability).

### Deferred Ideas (OUT OF SCOPE)
- Re-export / Markdown export — Phase 9 (D-10).
- YouTube URL submit / yt-dlp / playlist fan-out / pause-resume / timestamp link-out — Phase 6.
- Speaker labels / chip bar / per-line reassign / find-replace speaker — Phase 7.
- Summary content in the right pane — Phase 8.
- Inline transcript editing / find-replace text / Markdown export with edits applied — Phase 9.
- Settings panel / quality preset / per-category model overrides / first-run card / HF token UI — Phase 10.
- Dark mode / responsive / mobile — Out of Scope (PROJECT.md: desktop browser only).
- Rich job-detail metadata view — deferred (D-06).
- History search / filter / pagination beyond the API's `?limit`/`?offset` — not requested.
- Content-hash idempotency — future; Phase 5 uses client Idempotency-Key header.
- Global WebSocket stream (`/ws/events` for all jobs) — future; MVP is per-job.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | User can submit a local video file via drag-and-drop in the browser | Streaming upload endpoint (`request.stream()` + `aiofiles`) writes `source.<ext>` atomically; browser XHR-primary sends the raw octet-stream body + `X-Filename` header (`xhr.send(file)` streams from disk; `xhr.upload.onprogress` gives real 0→100 percent). See Architecture Patterns §1-2, Code Examples §1-2. |
| JOB-03 | App persists all completed jobs to local history; user can revisit, edit, and re-export | History page consumes `GET /jobs?status=done/failed/cancelled`; re-open loads transcript via new `GET /jobs/{id}/transcript` (D-14). Re-export half is Phase 9 (D-10). See §3. |
| UI-01 | Main working layout is 3-pane: history (left) \| transcript (middle) \| summary (right) | REFINED per D-04 to history index page (`/`) + 2-pane detail view (`/jobs/:id`). CSS Grid layout. See §2. |
| UI-02 | No embedded video player; YouTube jobs show an "open in YouTube" link at the current timestamp | No `<video>` element anywhere. The detail view renders transcript + summary placeholder only. See §2. |
| UI-03 | Active transcript line is highlighted based on current scroll position (for local files only) | `IntersectionObserver` with `rootMargin: "-49% 0px -49% 0px"` (2% center focal line per UI-SPEC §3); pixel-offset fallback for fast scroll. See §3, Code Examples §4. |
</phase_requirements>

## Summary

Phase 5 builds the first front-end (a greenfield React SPA in a new `web/` directory) and the last back-end ingest seam the orchestrator needs: a streaming upload endpoint that writes a multi-gigabyte file directly to `data/jobs/<id>/source.<ext>` without buffering it in process memory, plus a transcript read endpoint. The back-end is FastAPI 0.136.3 (verified in the codebase), and CORS is already configured for `http://localhost:5173` in `app/main.py` (allow_origins includes both localhost and 127.0.0.1:5173). The existing job spine from Phase 4 — queue, state machine, WebSocket progress, idempotency, cancel — is reused as-is; Phase 5 adds no new back-end ML imports and touches the filesystem only through the new upload + transcript-read routes and the existing atomic-write helpers.

The single most important integration finding is a **race condition between job creation and file streaming**: `app.jobs.service.create_job` inserts the DB row with `status='queued'` and the Phase 4 worker polls every 2s (`run_worker` → `pull_next` selects `WHERE status='queued'`). If the upload route creates the job (status=queued) before the file finishes streaming, the worker picks it up mid-upload, `run_job`'s ingest stage sees no `source.<ext>` yet, and marks the job `failed` with `"source file missing or empty"`. The clean fix is a **pre-queued status** (`'uploading'`) added to the `JobStatus` Literal so the worker's `pull_next` (which selects only `status='queued'`) never sees an uploading job; the upload route enqueues (`status='queued'`) only after `os.replace` lands `source.<ext>` atomically. The `enqueue` helper's `WHERE status IN ('created','queued')` clause must be widened to include `'uploading'`. The generalized `ingested` check in `app.jobs.resume.is_stage_complete` already handles `source.<ext>` in the job dir (Phase 4 D-04), so once the file lands and `source_path` is patched into the manifest, the orchestrator skips the ingest stage and goes straight to transcribing.

**Primary recommendation:** Build the streaming upload as a combined submit+stream route (`POST /jobs/upload`) that reserves the Idempotency-Key, creates the job in `status='uploading'`, streams the raw request body via `request.stream()` + `aiofiles` to `source.<ext>.tmp`, `os.replace` to `source.<ext>`, patches `manifest.source_path`, then calls `enqueue`. The browser uses XHR as the PRIMARY (and only) upload path: `xhr.send(file)` streams the File/Blob body directly from disk without buffering it in JS heap (raw octet-stream body + `X-Filename` header), and `xhr.upload.onprogress` gives real acked-byte percent 0→100 on every browser (honoring locked D-02). No `fetch`/`duplex:"half"` path, no multipart/FormData fallback, no `/jobs/upload-multipart` route, no python-multipart dependency. The FE is Vite 8 + React 19 + TypeScript 6 in a separate `web/` dir, types codegen'd from `/openapi.json` via `openapi-typescript 7`, server state via TanStack Query 5, routing via React Router 8.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| File streaming upload (write source.<ext> to disk) | API / Backend | — | Back-end is the only thing that touches the filesystem (PROJECT.md). Browser streams bytes to a FastAPI route; the route writes to disk. |
| Upload progress (streaming-to-disk %) | Browser / Client | API / Backend | Browser tracks bytes sent via XHR `xhr.upload.onprogress` (real 0→100 percent); back-end relays job-stage progress over the existing WS. Per-file upload % is client-computed from XHR progress events. |
| History list (completed jobs) | API / Backend | Browser / Client | `GET /jobs?status=...` is the source; browser renders the list. Back-end owns persistence + ordering. |
| 2-pane detail layout (transcript \| summary) | Browser / Client | — | Pure presentational; CSS Grid in React. No server state beyond the transcript fetch. |
| Active-line highlight (scroll-spy) | Browser / Client | — | Pure client-side `IntersectionObserver`; no back-end involvement. |
| Transcript read endpoint | API / Backend | — | New `GET /jobs/{id}/transcript` serves the parsed Phase 3 `Transcript`; 404 when none. |
| Job creation + ingest stage transition | API / Backend | — | Upload route creates job + writes file + enqueues; orchestrator (Phase 4) drives stages. |
| WebSocket progress relay | API / Backend | Browser / Client | Phase 4 WS endpoint already ships; browser subscribes. No back-end WS work in Phase 5. |

## Standard Stack

### Core (Front-end — new `web/` directory)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vite | 8.1.0 | Dev server + build | The modern standard; fast HMR; CORS origin already configured for :5173 in `app/main.py` [VERIFIED: npm registry] |
| react | 19.2.7 | UI library | D-12 locked; React 19 is current stable [VERIFIED: npm registry] |
| react-dom | 19.2.7 | React DOM renderer | Pairs with react [VERIFIED: npm registry] |
| typescript | 6.0.3 | Type system | D-12 locked; TS 6 is current [VERIFIED: npm registry] |
| @vitejs/plugin-react | 6.0.3 | Vite React plugin | Canonical Vite+React bridge [VERIFIED: npm registry] |
| @tanstack/react-query | 5.101.1 | Server state (job list, transcript fetch) | D-12 locked; the standard server-state library for React [VERIFIED: npm registry] |
| react-router | 8.0.1 | Routing (`/`, `/jobs/:id`) | D-12 locked; React Router 8 is the current package (react-router-dom is deprecated/legacy at 7.x — DO NOT use react-router-dom) [VERIFIED: npm registry] |
| openapi-typescript | 7.13.0 | Codegen TS types from `/openapi.json` | D-12 locked; Phase 1/2 already anticipated this codegen [VERIFIED: npm registry] |

### Supporting (Front-end)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| lucide-react | 1.21.0 | Icon library | UI-SPEC §Design System locks lucide-react [VERIFIED: npm registry] |
| @radix-ui/react-dialog | 1.1.17 | Primitive dialog (if needed for confirm) | UI-SPEC locks radix as component library; use only if a modal is needed (cancel confirm) [VERIFIED: npm registry] |

### Back-end (additions to existing Python project)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-multipart | 0.0.32 (installed: 0.0.29) | NOT REQUIRED under XHR-primary (raw octet-stream body) | Not used in Phase 5 — the XHR-primary path sends a raw body + `X-Filename` header and the back-end reads it via `request.stream()`; no multipart parsing occurs. Listed only because it is already installed in pyproject.toml from earlier phases. [VERIFIED: pip index] |
| aiofiles | 25.1.0 (already installed) | Async streaming write to `source.<ext>.tmp` | Already a dependency; used by `atomic_write_bytes` and the upload route [VERIFIED: pip index] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `request.stream()` (raw body) | `UploadFile` + chunked `read()` | `UploadFile` uses SpooledTemporaryFile (1 MB threshold) and `read(byte_count)` waits for the ENTIRE upload before returning the first chunk (FastAPI issue #3136) — defeats true streaming. `request.stream()` is the only true streaming path. [CITED: github.com/fastapi/fastapi/issues/3136] |
| fetch ReadableStream body | XHR (raw octet-stream + `X-Filename`) | XHR is the PRIMARY (and only) path: `xhr.send(file)` streams from disk without JS-heap buffering, `xhr.upload.onprogress` gives real 0→100 percent on every browser (honoring D-02), and works on HTTP/1.1 + Firefox/Safari. fetch streaming requires Chrome 105+ / HTTP2+ and gives no reliable upload progress (Pitfall 5) — NOT used. [CITED: developer.mozilla.org/en-US/docs/Web/API/XMLHttpRequest/upload] |
| TanStack Query | SWR / native fetch+state | TanStack Query is D-12-locked; provides cache invalidation, retries, background refetch — needed for history list + transcript fetch. |
| React Router 8 | TanStack Router | D-12 locks React Router; TanStack Router is newer but not the locked decision. |

**Installation (Front-end — new `web/` dir):**
```bash
cd web
npm create vite@latest . -- --template react-ts
npm install @tanstack/react-query react-router lucide-react @radix-ui/react-dialog
npm install -D openapi-typescript
```

**Installation (Back-end — existing pyproject.toml):**
```bash
# No new back-end dependency required for Phase 5.
# python-multipart is NOT used (XHR-primary sends a raw octet-stream body;
# the back-end reads it via request.stream() — no multipart parsing).
# aiofiles (already installed) is the only streaming-write dependency used.
```

**Version verification (run 2026-06-23):**
- `npm view vite version` → 8.1.0 (modified 2026-06-23)
- `npm view react version` → 19.2.7
- `npm view typescript version` → 6.0.3
- `npm view @vitejs/plugin-react version` → 6.0.3
- `npm view openapi-typescript version` → 7.13.0 (modified 2026-06-15)
- `npm view @tanstack/react-query version` → 5.101.1
- `npm view react-router version` → 8.0.1 (modified 2026-06-18; react-router-dom is 7.18.0 — DO NOT USE, it is the legacy track)
- `npm view lucide-react version` → 1.21.0 (modified 2026-06-18)
- `npm view @radix-ui/react-dialog version` → 1.1.17
- `pip index versions python-multipart` → 0.0.32 (installed 0.0.29)
- `python -c "import fastapi; print(fastapi.__version__)"` → 0.136.3

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| vite | npm | ~6 yrs (created 2020-04-21) | top-tier | github.com/vitejs/vite | OK | Approved |
| react | npm | ~12 yrs | top-tier | github.com/facebook/react | OK | Approved |
| typescript | npm | ~12 yrs | top-tier | github.com/microsoft/TypeScript | OK | Approved |
| @vitejs/plugin-react | npm | ~5 yrs | top-tier | github.com/vitejs/vite | OK | Approved |
| @tanstack/react-query | npm | ~5 yrs | top-tier | github.com/TanStack/query | OK | Approved |
| react-router | npm | ~12 yrs (v8 published 2026-06-18) | top-tier | github.com/remix-run/react-router | OK | Approved |
| openapi-typescript | npm | ~6 yrs | high | github.com/openapi-ts/openapi-typescript | OK | Approved |
| lucide-react | npm | ~6 yrs (v1 published 2026-04-23) | high | github.com/lucide-icons/lucide | OK | Approved |
| @radix-ui/react-dialog | npm | ~4 yrs | high | github.com/radix-ui/primitives | OK | Approved |
| python-multipart | PyPI | ~5 yrs | top-tier | github.com/Kludex/python-multipart | OK | Approved |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*All packages are well-known, high-download, established-registry packages with recent publish dates (verified via `npm view` / `pip index` on 2026-06-23). No `[ASSUMED]` package-name claims — every recommended package was verified on the correct ecosystem registry.*

## Architecture Patterns

### System Architecture Diagram

```
Browser (web/ — Vite dev :5173)                    Back-end (FastAPI :8000)
═══════════════════════════════                    ═════════════════════════
                                                    
 ┌──────────────────────────┐                       ┌─────────────────────────┐
 │ History page (/)         │                       │  POST /jobs/upload       │
 │  ┌────────────────────┐  │  XHR (raw octet-stream)│  (Idempotency-Key hdr)   │
 │  │ Drop zone + overlay│──┼──────────────────────►│  request.stream() →      │
 │  │ (drag + file-pick) │  │  X-Filename + xhr.send │  aiofiles → source.ext.tmp
 │  └────────────────────┘  │  xhr.upload.onprogress │  → os.replace → source.ext│
 │  ┌────────────────────┐  │  (real 0→100 %)       │  patch manifest.source_path
 │  │ Active job cards   │◄─┼─── WS /ws/jobs/{id}/events ─┐ enqueue → status=queued │
 │  │ (WS-driven %, ETA) │  │   (snapshot + live)  │  └───────────┬─────────────┘
 │  └────────────────────┘  │                                   │
 │  ┌────────────────────┐  │                                   │
 │  │ History list      │◄─┼─── GET /jobs?status=done ─────────┤
 │  │ (completed jobs)  │  │   (newest-first)       ┌───────────▼─────────────┐
 │  │  filename/date/dur│  │                       │ Phase 4 worker (serial)   │
 │  └──────┬─────────────┘  │                       │ run_job → skip ingest     │
 │         │ click row       │                       │ → transcribe → done      │
 │         ▼                 │                       │ (writes transcript.json)  │
 │ ┌──────────────────────┐ │                       └───────────┬─────────────┘
 │ │ Detail (/jobs/:id)   │ │                                   │
 │ │  ┌────────┐ ┌──────┐ │ │  GET /jobs/{id}/transcript        │
 │ │  │Trans-  │ │Sum-  │ │◄┼───────────────────────────────────┤
 │ │  │cript  │ │mary  │ │ │  (404 if none → "Transcribing…")    │
 │ │  │(left) │ │(plc- │ │ │                       ┌───────────▼─────────────┐
 │ │  │scroll │ │holdr)│ │ │                       │ data/jobs/<id>/          │
 │ │  │-spy   │ │      │ │ │                       │  source.<ext>            │
 │ │  └───────┘ └──────┘ │ │                       │  manifest.json           │
 │ └──────────────────────┘ │                       │  transcript.json         │
 └──────────────────────────┘                       │  progress.json           │
       IntersectionObserver                         └──────────────────────────┘
       (rootMargin -49%/-49%)
```

### Recommended Project Structure

```
web/                          # NEW — greenfield React SPA (separate codebase)
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx              # entry: QueryClientProvider + RouterProvider
│   ├── App.tsx               # routes: / (history), /jobs/:id (detail)
│   ├── api/
│   │   ├── client.ts         # fetch wrapper (base URL, idempotency key)
│   │   ├── types.ts          # CODEGEN'd from /openapi.json (openapi-typescript)
│   │   ├── jobs.ts           # useJobs (history list), useJob, useTranscript
│   │   └── ws.ts             # useJobEvents(jobId) — native WebSocket hook
│   ├── components/
│   │   ├── DropZone.tsx      # full-window drag overlay + history drop area
│   │   ├── ActiveJobCard.tsx # WS-driven card (queued/ingesting/transcribing)
│   │   ├── HistoryList.tsx   # completed jobs list (filename/date/duration)
│   │   ├── HistoryRow.tsx    # one completed row → navigate to /jobs/:id
│   │   ├── TranscriptPane.tsx # segment list + scroll-spy
│   │   ├── TranscriptRow.tsx  # [mm:ss] text (CSS Grid: 64px | 80px | body)
│   │   ├── SummaryPane.tsx   # placeholder empty state
│   │   └── ExportStub.tsx    # disabled "Export (Coming Soon)" (UI-SPEC §6)
│   ├── pages/
│   │   ├── HistoryPage.tsx   # route / — drop zone + active cards + history
│   │   └── DetailPage.tsx    # route /jobs/:id — 2-pane (transcript | summary)
│   ├── hooks/
│   │   ├── useScrollSpy.ts   # IntersectionObserver, rootMargin -49%/-49%
│   │   └── useUpload.ts      # XHR-PRIMARY (raw octet-stream body + X-Filename header)
│   └── styles.css           # CSS variables from UI-SPEC (spacing, color, type)
└── scripts/
    └── gen-types.sh          # openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts

# Back-end additions (existing app/ tree):
app/api/routes_jobs.py        # ADD: POST /jobs/upload (streaming), GET /jobs/{id}/transcript
app/models/job.py             # ADD: 'uploading' to JobStatus Literal
app/jobs/queue.py             # WIDEN enqueue WHERE clause to include 'uploading'
app/jobs/service.py           # ADD: create_upload_job (status='uploading') helper
```

### Pattern 1: Streaming upload endpoint (back-end — `request.stream()` + `aiofiles`)
**What:** A combined submit+stream route that creates the job, streams the raw body to disk, and enqueues — all in one request. Avoids the race where the worker picks up a queued job before the file lands.
**When to use:** Always for browser uploads (the browser cannot supply a server-side `source_path`).
**Key insight — the race:** `create_job` sets `status='queued'`; the Phase 4 worker polls every 2s. If the job is queued before the file finishes streaming, the worker's `run_job` enters the ingest stage, finds no `source.<ext>`, and marks the job `failed`. The fix: a pre-queued `'uploading'` status invisible to `pull_next` (which selects only `status='queued'`).
**Example:**
```python
# Source: FastAPI docs + StackOverflow (request.stream() pattern) + codebase
# [CITED: fastapi.tiangolo.com/tutorial/request-files/]
# [CITED: stackoverflow.com/questions/65342833/fastapi-uploadfile-is-slow]
# [VERIFIED: codebase — app/jobs/queue.py pull_next selects status='queued' only]

from fastapi import APIRouter, Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse
import aiofiles, os
from pathlib import Path

from app.storage.fs import job_dir, validate_source_ext, source_path
from app.storage.atomic import retry_windows
from app.jobs.service import create_upload_job  # NEW: status='uploading'
from app.jobs.queue import enqueue
from app.jobs.manifest import read_manifest, write_manifest
from app.models.job import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.post("/upload", response_model=JobResponse, status_code=201)
async def upload_source(
    request: Request,
    filename: str = Header(..., alias="X-Filename"),  # e.g. "video.mp4"
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session=Depends(get_session),
    settings=Depends(get_settings),
) -> JobResponse:
    # 1. Validate extension BEFORE writing (path-traversal safe).
    ext = validate_source_ext(filename.rsplit(".", 1)[-1] if "." in filename else "")
    # 2. Reserve idempotency key + create job in status='uploading'.
    response, status_code = await resolve_or_create_upload(
        request, session, settings, idempotency_key,
        lambda job_id=None: create_upload_job(session, settings, job_id=job_id),
    )
    job_id = response.id
    # 3. Stream the raw body to source.<ext>.tmp (NOT buffered in memory).
    final_path = source_path(settings, job_id, ext)  # job_dir/source.<ext>
    tmp_path = final_path.parent / f".tmp_{final_path.name}"  # source.ext.tmp_<uuid> style
    try:
        async with aiofiles.open(tmp_path, "wb") as f:
            async for chunk in request.stream():  # true streaming, ~64KB chunks
                await f.write(chunk)
            await f.flush()
            os.fsync(f.fileno())
        # 4. Atomic rename → source.<ext> (retry on Windows AV locks).
        retry_windows(os.replace, tmp_path, final_path)
    except BaseException:
        try: os.unlink(tmp_path)
        except FileNotFoundError: pass
        raise
    # 5. Patch manifest.source_path so the orchestrator's transcribe stage finds it.
    manifest = await read_manifest(settings, job_id)
    manifest = manifest.model_copy(update={"source_path": str(final_path), "source_type": "local"})
    await write_manifest(settings, manifest)
    # 6. Enqueue → status='queued', wake worker. Worker skips ingest (source_path resolves).
    await enqueue(job_id, session)
    return response
```

### Pattern 2: Browser streaming upload (XHR-primary, raw octet-stream body + `X-Filename` header)
**What:** The browser streams the file without loading it fully into memory using XHR as the PRIMARY (and only) upload path. `xhr.send(file)` passes the File/Blob handle directly to the browser, which streams bytes from disk without buffering the whole file in JS heap (INGEST-01 memory guarantee preserved on the FE side too). `xhr.upload.onprogress` with `e.lengthComputable` yields the real acked-byte percent, updating 0→100 on every browser (Chrome/Edge/Firefox/Safari), honoring locked D-02.
**When to use:** Drop zone + file picker. This is the single upload path — no `fetch`/`duplex:"half"` path, no multipart/FormData fallback, no `/jobs/upload-multipart` route, no python-multipart dependency.
**Why XHR-primary:** fetch streaming request bodies (`duplex:"half"`) require Chrome/Edge 105+ AND HTTP/2+, are unsupported on Firefox/Safari (Pitfall 4), and give no reliable upload progress (Pitfall 5) — which would force an indeterminate "Uploading..." indicator and violate locked D-02 (per-file PERCENT for every file). XHR gives real upload progress events and universal browser support. See Open Questions #1 + #2 (RESOLVED).
**Example:**
```typescript
// Source: MDN XMLHttpRequest upload progress + RESEARCH Open Questions #1/#2 (RESOLVED)
// [CITED: developer.mozilla.org/en-US/docs/Web/API/XMLHttpRequest/upload]

async function streamFileToJob(file: File, idempotencyKey: string) {
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/jobs/upload");
  // Raw octet-stream body + X-Filename header (NOT FormData/multipart).
  xhr.setRequestHeader("Idempotency-Key", idempotencyKey);
  xhr.setRequestHeader("X-Filename", file.name);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");

  // Real acked-byte percent 0->100 (Pitfall 5 mitigation: real % on XHR, never indeterminate).
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      onProgress(Math.round((e.loaded / e.total) * 100));
    }
  };

  return new Promise((resolve, reject) => {
    xhr.onload = () => {
      if (xhr.status === 201 || xhr.status === 200) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`upload failed: ${xhr.status} ${xhr.statusText}`));
      }
    };
    xhr.onerror = () => reject(new Error("upload failed"));
    // xhr.send(file) streams the File/Blob body directly from disk WITHOUT
    // buffering the whole file in JS heap (FE-side INGEST-01 memory guarantee).
    xhr.send(file);
  });
}
```

### Pattern 3: History list + active-job cards (TanStack Query + WS)
**What:** The history page fetches completed jobs via `GET /jobs?status=done` (and `failed`, `cancelled`) newest-first, renders active-job cards subscribed to per-job WS, and moves a card to the history list when it receives a terminal WS event.
**When to use:** Always on the `/` route.
**Example:**
```typescript
// useJobs: server state via TanStack Query
const { data: doneJobs } = useQuery({
  queryKey: ["jobs", "done"],
  queryFn: () => fetch("/jobs?status=done").then(r => r.json()),
});
// Active cards: each opens its own WS via useJobEvents(jobId).
// On {type:"done"|"failed"|"cancelled"}, invalidate ["jobs","done"] to refetch.
```

### Pattern 4: Scroll-spy active-line highlight (IntersectionObserver)
**What:** A single `IntersectionObserver` with `rootMargin: "-49% 0px -49% 0px"` (per UI-SPEC §3) creates a 2% focal line at the vertical center. The segment row passing through that line is highlighted. A pixel-offset fallback handles the gap when no row intersects (fast scroll / short transcripts).
**When to use:** Always in the transcript pane (local files only — D-09).
**Example:**
```typescript
// Source: MDN IntersectionObserver + UI-SPEC §3
// [CITED: developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API]

function useScrollSpy(containerRef: Ref<HTMLDivElement>, rowIds: string[]) {
  const [activeId, setActiveId] = useState<string | null>(null);
  useEffect(() => {
    if (!containerRef.current || rowIds.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const intersecting = entries.filter(e => e.isIntersecting);
        if (intersecting.length > 0) {
          // Pick the one closest to center (last intersecting = lowest in DOM).
          setActiveId(intersecting[intersecting.length - 1].target.id);
        } else {
          // Fallback: closest row by pixel offset to viewport center.
          const center = window.innerHeight / 2;
          let best: string | null = null, bestDist = Infinity;
          for (const id of rowIds) {
            const el = document.getElementById(id);
            if (!el) continue;
            const rect = el.getBoundingClientRect();
            const dist = Math.abs(rect.top + rect.height / 2 - center);
            if (dist < bestDist) { bestDist = dist; best = id; }
          }
          if (best) setActiveId(best);
        }
      },
      { root: containerRef.current, rootMargin: "-49% 0px -49% 0px", threshold: 0 },
    );
    rowIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [rowIds]);
  return activeId;
}
```

### Anti-Patterns to Avoid
- **Do NOT use `UploadFile` for the streaming path.** `UploadFile` uses `SpooledTemporaryFile` and `read(byte_count)` waits for the entire upload before returning (FastAPI issue #3136). Use `request.stream()` for true streaming. [CITED: github.com/fastapi/fastapi/issues/3136]
- **Do NOT create the job as `status='queued'` before the file lands.** The worker polls every 2s and will pick it up mid-upload, marking it `failed`. Use `status='uploading'` then `enqueue`.
- **Do NOT use `react-router-dom`.** It is the legacy 7.x track; `react-router` 8.x is the current package. [VERIFIED: npm registry — react-router 8.0.1 vs react-router-dom 7.18.0]
- **Do NOT use `threshold: 1.0` for the scroll-spy observer.** It never fires on rows taller than the viewport. Use `threshold: 0` with negative `rootMargin`. [CITED: developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API]
- **Do NOT treat fetch ReadableStream enqueued bytes as upload progress.** Enqueued ≠ acked bytes. Use XHR `upload.progress` for real progress, or the back-end WS job-stage events. [CITED: developer.chrome.com/docs/capabilities/web-apis/fetch-streaming-requests]
- **Do NOT hand-write TS types for the back-end models.** Use `openapi-typescript` to codegen from `/openapi.json` (D-12; Phase 1/2 already patched the OpenAPI schema to expose `Transcript`, `TranscriptSegment`, `JobResponse`).
- **Do NOT add a `<video>` element anywhere.** UI-02 forbids it; there is no click-to-seek on local files in v1.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multipart parsing | Manual boundary parsing | N/A — not used in Phase 5 | XHR-primary sends a raw octet-stream body + `X-Filename` header (no multipart), so no boundary parsing occurs and `python-multipart` is not needed. Listed for completeness: if a multipart path were ever reintroduced, use `python-multipart`. |
| TS types from OpenAPI | Hand-written interfaces | `openapi-typescript 7` | Codegen stays in sync with the back-end; Phase 1/2 already patched the schema. |
| Server state cache/invalidation | Manual useEffect + fetch | TanStack Query 5 | Handles refetch-on-focus, dedup, invalidation — needed when a terminal WS event must refresh the history list. |
| Scroll-spy from scratch | Manual scroll event math | `IntersectionObserver` API | Native, performant, handles rootMargin focal lines; scroll-event math is janky and expensive. |
| Atomic file write | Manual open+write+rename | `app.storage.atomic.atomic_write_bytes` (existing) | Already handles tmp+fsync+`os.replace` with the Windows retry helper. |
| Path validation | Manual string checks | `app.storage.fs.validate_source_ext` (existing) | Already rejects path traversal, enforces the allowlist. |

**Key insight:** The back-end already has atomic writes, path validation, the generalized `ingested` check, idempotency, and the WS relay. Phase 5 plugs into these — it does not rebuild them.

## Runtime State Inventory

> Phase 5 is a greenfield + additive phase (new FE codebase + new back-end routes), NOT a rename/refactor. The Runtime State Inventory is included for completeness because the new `'uploading'` status touches the `JobStatus` Literal.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — new jobs are created fresh by the upload route; no existing rows are renamed. | None |
| Live service config | None — the back-end is extended, not reconfigured. CORS is already set for :5173 in `app/main.py`. | None |
| OS-registered state | None. | None |
| Secrets/env vars | None. | None |
| Build artifacts | None — the FE is a new `web/` dir with its own `package.json`; no existing build artifacts to rename. The back-end `egg-info` is unaffected. | None |

## Common Pitfalls

### Pitfall 1: Worker picks up the job before the file finishes streaming
**What goes wrong:** The upload route creates the job (`status='queued'`), the Phase 4 worker polls every 2s (`run_worker` → `pull_next` selects `WHERE status='queued'`), picks up the job mid-upload, `run_job`'s ingest stage finds no `source.<ext>`, raises `ValueError("source file missing or empty")`, and marks the job `failed`.
**Why it happens:** `create_job` hardcodes `status='queued'`; the worker's `pull_next` only selects `status='queued'`; a multi-GB upload takes minutes.
**How to avoid:** Create the job in a pre-queued `status='uploading'` state (NEW — add to `JobStatus` Literal in `app/models/job.py`). The worker's `pull_next` already filters to `status='queued'` only, so `'uploading'` jobs are invisible. After `os.replace` lands `source.<ext>`, call `enqueue(job_id)` which sets `status='queued'`. Widen `enqueue`'s `WHERE status IN ('created','queued')` to `('uploading','created','queued')`.
**Warning signs:** Jobs immediately `failed` with `error="source file missing or empty"` after a drop.

### Pitfall 2: `UploadFile.read(byte_count)` does NOT stream in real time
**What goes wrong:** Using `UploadFile` with chunked `read(1024*1024)` appears to stream but actually blocks until the ENTIRE upload is received by the server before returning the first chunk.
**Why it happens:** FastAPI issue #3136 — `UploadFile` wraps a `SpooledTemporaryFile` that buffers the whole body first.
**How to avoid:** Use `request.stream()` (the raw Starlette body stream) which yields chunks as they arrive. Combined with `aiofiles` for async disk writes.
**Warning signs:** Uploads of large files consume a full core and take 2x as long as expected; memory grows.

### Pitfall 3: `manifest.source_path` is `None` at transcribe time
**What goes wrong:** The upload route writes `source.<ext>` but does not patch `manifest.source_path`. The orchestrator's transcribe stage reads `manifest.source_path` (line 253 of `orchestrator.py`: `if source_path is None: raise ValueError`).
**Why it happens:** The generalized `ingested` check (`resume.py`) accepts `source.<ext>` in the job dir even without `source_path`, so `skip_ingested` is True — but the transcribe stage still reads `manifest.source_path`.
**How to avoid:** After writing `source.<ext>`, patch the manifest: `manifest.source_path = str(final_path)`, `manifest.source_type = "local"`, then `write_manifest`. Do NOT call `update_stage("ingested")` (that sets status="ingesting" which blocks `enqueue`); just patch the manifest fields directly.
**Warning signs:** Job fails with `"manifest.source_path is None at transcribe time"`.

### Pitfall 4: fetch streaming request body unsupported on Firefox/Safari
**What goes wrong:** `fetch` with a `ReadableStream` body rejects on Firefox/Safari with `ERR_H2_OR_QUIC_REQUIRED` or silently buffers.
**Why it happens:** Streaming request bodies require Chrome/Edge 105+ AND HTTP/2+. Firefox has not implemented it (Bugzilla 1387483, open since 2017).
**How to avoid:** Phase 5 uses XHR as the PRIMARY (and only) upload path — `xhr.send(file)` streams the raw octet-stream body + `X-Filename` header and works on HTTP/1.1 + every browser (Firefox/Safari included), so this pitfall is moot. No `fetch`/`duplex:"half"` path, no multipart/FormData fallback, no python-multipart dependency. See Open Questions #1 (RESOLVED).
**Warning signs:** N/A — XHR-primary sidesteps this entirely. (If fetch streaming were used, the warning sign would be: upload fails on Firefox; works on Chrome. The project is desktop-browser-only but Firefox is a common desktop browser.)

### Pitfall 5: No reliable upload progress from fetch streaming
**What goes wrong:** The UI shows a stuck progress bar because `controller.enqueue`'d bytes are not network-acked bytes.
**Why it happens:** The fetch streaming spec does not expose acked-byte counts.
**How to avoid:** Phase 5 uses XHR as the PRIMARY upload path: `xhr.upload.onprogress` with `e.lengthComputable` yields the real acked-byte percent 0→100 on every browser, honoring locked D-02 (per-file PERCENT for every file). No `fetch`/`duplex:"half"` path is used, so there is no indeterminate "Uploading..." indicator. The back-end WS separately relays stage-level progress (ingesting 0→100 binary, per-chunk transcribing %) per Phase 4 D-09.
**Warning signs:** N/A — XHR-primary gives real progress. (If fetch streaming were used, the warning sign would be: progress bar jumps from 0 to 100 with no intermediate updates.)

### Pitfall 6: `react-router-dom` vs `react-router` version mismatch
**What goes wrong:** Installing `react-router-dom` gets the legacy 7.x track; the current package is `react-router` 8.x.
**Why it happens:** React Router 7 deprecated `react-router-dom` in favor of a single `react-router` package.
**How to avoid:** Install `react-router` (not `react-router-dom`). Import from `react-router`.
**Warning signs:** Type errors; missing APIs; stale docs referencing `react-router-dom`.

## Code Examples

### Example 1: Back-end streaming upload route (full, `request.stream()`)
```python
# app/api/routes_jobs.py — ADD this route
# Source: [CITED: stackoverflow.com/questions/65342833] + codebase patterns

@router.post("/upload", response_model=JobResponse, status_code=201)
async def upload_source(
    request: Request,
    x_filename: str = Header(..., alias="X-Filename"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    # Validate ext (path-traversal safe, allowlist enforced).
    ext = validate_source_ext(x_filename.rsplit(".", 1)[-1] if "." in x_filename else "")
    # Idempotency + create job in status='uploading' (NOT queued).
    response, status_code = await resolve_or_create(
        request, session, settings,
        lambda job_id=None: create_upload_job(session, settings, job_id=job_id),
    )
    job_id = response.id
    final = source_path(settings, job_id, ext)  # job_dir/source.<ext>
    tmp = final.parent / f".tmp_{final.name}"
    try:
        async with aiofiles.open(tmp, "wb") as f:
            async for chunk in request.stream():
                await f.write(chunk)
            await f.flush()
            os.fsync(f.fileno())
        retry_windows(os.replace, tmp, final)
    except BaseException:
        os.unlink(tmp) if tmp.exists() else None
        raise
    # Patch manifest source_path (NOT update_stage — avoids status="ingesting").
    manifest = await read_manifest(settings, job_id)
    manifest = manifest.model_copy(update={"source_path": str(final), "source_type": "local"})
    await write_manifest(settings, manifest)
    # Enqueue → status='queued', wake worker.
    await enqueue(job_id, session)
    return Response(content=response.model_dump_json(), media_type="application/json", status_code=status_code)
```

### Example 2: `create_upload_job` helper (status='uploading')
```python
# app/jobs/service.py — ADD this helper
# Mirrors create_job but inserts status='uploading' so pull_next never sees it.

async def create_upload_job(session, settings, job_id=None) -> JobResponse:
    if job_id is None:
        job_id = new_job_id()
    now_iso = utcnow_iso()
    await session.execute(
        text("INSERT INTO jobs (id, created_at, status, source_type, current_stage) "
             "VALUES (:id, :created_at, 'uploading', 'local', NULL)"),
        {"id": job_id, "created_at": now_iso},
    )
    await session.commit()
    try:
        await ensure_job_dir(settings, job_id)
        await write_manifest(settings, empty_manifest(job_id))
    except Exception:
        await session.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        await session.commit()
        raise
    return JobResponse(id=job_id, status="uploading", created_at=datetime.fromisoformat(now_iso), source_type="local")
```

### Example 3: Transcript read endpoint (D-14)
```python
# app/api/routes_jobs.py — ADD this route
from app.models.transcript import Transcript
from app.storage.fs import transcript_path

@router.get("/{job_id}/transcript", response_model=Transcript,
             responses={404: {"description": "job or transcript not found"}})
async def get_transcript(job_id: str, settings: Settings = Depends(get_settings)) -> Transcript:
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc
    path = transcript_path(settings, canonical_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="transcript not found")
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))
```

### Example 4: WS client hook (native browser WebSocket)
```typescript
// web/src/api/ws.ts
// The back-end snapshot + event shapes are in app/api/routes_ws.py.
export function useJobEvents(jobId: string | null) {
  const [event, setEvent] = useState<any>(null);
  useEffect(() => {
    if (!jobId) return;
    const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}/events`);
    ws.onmessage = (e) => setEvent(JSON.parse(e.data));
    return () => ws.close();
  }, [jobId]);
  return event; // {type:"snapshot",...} | {type:"progress",...} | {type:"done",...}
}
```

### Example 5: 2-pane CSS Grid layout (UI-SPEC §4)
```css
/* web/src/styles.css — from UI-SPEC spacing scale + transcript row layout */
.detail-layout {
  display: grid;
  grid-template-columns: 60% 40%; /* transcript | summary (UI-SPEC §6: summary 40%) */
  gap: 24px; /* lg token */
  height: 100vh;
  padding: 32px; /* xl token */
}
.transcript-pane { overflow-y: auto; }
.transcript-row {
  display: grid;
  grid-template-columns: 64px 80px 1fr; /* timestamp | speaker gutter | body */
  line-height: 1.5;
  padding: 8px; /* sm */
  border-left: 4px solid transparent;
}
.transcript-row.active {
  border-left-color: #2563EB; /* accent */
  background: rgba(37, 99, 235, 0.05);
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `react-router-dom` (separate DOM package) | `react-router` (single package, v7+) | React Router 7 (2024-2025) | Import from `react-router`, not `react-router-dom`. `react-router-dom` 7.x is legacy; v8 is `react-router`. |
| `UploadFile` chunked read | `request.stream()` for true streaming | FastAPI issue #3136 (2021, still open) | `UploadFile.read(n)` buffers the whole body first; `request.stream()` yields chunks live. |
| IntersectionObserver scroll math | `rootMargin` negative margins for focal line | MDN, stable since 2020 | No manual scroll-event math; `rootMargin: "-49% 0px -49% 0px"` = 2% center focal line. |
| Hand-written TS types from OpenAPI | `openapi-typescript 7` codegen | openapi-typescript 7 (2025) | Codegen from `/openapi.json`; Phase 1/2 already patched the schema. |

**Deprecated/outdated:**
- `react-router-dom`: use `react-router` 8.x instead. [VERIFIED: npm registry — react-router 8.0.1 is current; react-router-dom 7.18.0 is the legacy track]
- `UploadFile` for large streaming uploads: use `request.stream()`. [CITED: github.com/fastapi/fastapi/issues/3136]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | XHR-primary works on every desktop browser (Chrome, Edge, Firefox, Safari). | Pattern 2, Pitfall 4 | No browser constraint — `xhr.send(file)` + `xhr.upload.onprogress` are universally supported. No fetch/duplex path is used, so the former Chrome/Edge-only assumption is moot. Low risk. |
| A2 | The Vite dev server runs on :5173 (matching the CORS config in `app/main.py`). | Standard Stack | If the port is different, CORS must be updated. Low risk — :5173 is the Vite default. |
| A3 | `create_upload_job` with `status='uploading'` requires adding `'uploading'` to the `JobStatus` Literal so `JobResponse` strict validation passes. | Pattern 1, Pitfall 1 | If not added, `_row_to_response` fails on the new status. Medium risk — but it is a straightforward model change. |
| A4 | The upload route should patch the manifest directly (not call `update_stage("ingested")`) to avoid setting `status="ingesting"` which blocks `enqueue`. | Pitfall 3 | If `update_stage("ingested")` is called instead, `enqueue`'s `WHERE status IN ('created','queued')` won't match and the job never gets queued. Medium risk — documented clearly above. |
| A5 | HTTP/1.1 is sufficient (XHR-primary does not require HTTP/2). | Pattern 2 | XHR upload works over HTTP/1.1 on every browser; no HTTP/2 dependency. The former fetch-streaming HTTP/2 requirement is moot because fetch is not used. Low risk. |

**If this table is empty:** All claims in this research were verified or cited. Five `[ASSUMED]` claims are listed — A1, A3, A4, A5 are low-to-medium risk and covered by fallbacks or are straightforward model changes the planner will include. A2 is the Vite default port.

## Open Questions (RESOLVED)

1. **HTTP/2 on the dev server (historically considered for fetch streaming).** fetch streaming request bodies would have required HTTP/2 (Chrome rejects with `ERR_H2_OR_QUIC_REQUIRED` on HTTP/1.1). This is now moot — XHR-primary is adopted and works on HTTP/1.1 on every browser, so no HTTP/2 dev-server config is needed.
   - What we know: uvicorn[standard] supports HTTP/1.1 by default; HTTP/2 requires `uvicorn ... --h11-max-incomplete-event-size` + h2 package. The project runs uvicorn[standard].
   - What's unclear: whether the dev launch config enables HTTP/2.
   - RESOLVED: XHR is the PRIMARY (and only) upload path in plan 05-02b Task 2 (`useUpload.ts`). `xhr.send(file)` streams the File/Blob body directly from disk WITHOUT buffering the whole file in JS heap (INGEST-01 memory guarantee preserved on the FE side too), and works on HTTP/1.1 + every browser (Firefox/Safari included — Pitfall 4 moot). The fetch `duplex:"half"` streaming path is NOT used — it gives no upload progress (Pitfall 5) and would deliver indeterminate "Uploading…" on Chrome/Edge, violating locked D-02 which requires PERCENT for every file. The back-end `POST /jobs/upload` route (05-01) reads the raw body via `request.stream()` (HTTP-version-agnostic); the FE XHR path sends the raw octet-stream body + `X-Filename` header (NOT FormData/multipart), matching that contract. No `/jobs/upload-multipart` fallback route is needed.

2. **Per-file upload progress on the fetch path.** fetch streaming gives no reliable byte-level upload progress.
   - What we know: XHR `upload.onprogress` gives real progress; fetch does not.
   - What's unclear: whether the user cares about upload % vs. just "Uploading…".
   - RESOLVED: The user cares — locked decision D-02 requires "Per-file upload progress is shown for every file (streaming-to-disk percent)." Plan 05-02b Task 2 uses XHR-primary with `xhr.upload.onprogress` so every browser shows real 0->100 percent on the primary path (not a static "Uploading…"). The fetch streaming path (which would force indeterminate progress) is dropped entirely. The `jobs.test.ts` useUpload progress assertion (loaded:500/total:1000 -> 50, loaded:1000/total:1000 -> 100) verifies D-02 is honored. The back-end WS separately relays the `ingesting`/`transcribing` stage percent per Phase 4 D-09.

3. **Idempotency key derivation.** UI-SPEC §1 specifies `[filename]-[size]-[lastmodified]`.
   - What we know: `validate_idempotency_key` restricts charset to `[A-Za-z0-9_-]` and caps at 128 chars. The UI-SPEC format uses `-` separators which is valid.
   - What's unclear: whether long filenames exceed 128 chars.
   - RESOLVED: Plan 05-02a Task 2 implements `idempotencyKey(filename, size, lastModified)` in `web/src/api/client.ts` that hashes `[filename]-[size]-[lastmodified]` via `crypto.subtle` SHA-256 and truncates to 32 hex chars, staying well under the 128-char cap. The 05-02b `useUpload` hook consumes this helper to set the `Idempotency-Key` header on the XHR-primary upload.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | FE build (Vite) | ✓ | 24.16.0 | — |
| npm | FE package install | ✓ | 11.14.0 | — |
| Python | Back-end runtime | ✓ | 3.12.5 | — |
| FastAPI | Back-end framework | ✓ | 0.136.3 | — |
| aiofiles | Streaming write to disk | ✓ | 25.1.0 | — |
| python-multipart | (not required — XHR-primary, no multipart) | N/A | — | Not needed; XHR sends raw octet-stream body, no multipart/FormData path |
| Chrome/Edge 105+ | (not required — XHR-primary) | N/A | — | XHR works on all browsers; no fetch-streaming dependency |
| HTTP/2 (uvicorn) | (not required — XHR-primary) | N/A | — | XHR works on HTTP/1.1; no HTTP/2 dependency |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — XHR-primary works on HTTP/1.1 + every browser; no fetch-streaming or python-multipart dependency.

## Validation Architecture

> Nyquist validation is enabled (`workflow.nyquist_validation: true` in `.planning/config.json`). This section is REQUIRED and is consumed downstream to generate VALIDATION.md.

### Test Framework

| Property | Value |
|----------|-------|
| Framework (back-end) | pytest 8 + pytest-asyncio (existing, `asyncio_mode="auto"`) |
| Config file (back-end) | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"]) |
| Quick run command (back-end) | `pytest tests/test_<module>.py -x` |
| Full suite command (back-end) | `pytest` |
| Framework (front-end) | Vitest 8 (ships with Vite) — NEW, to be configured in `web/` |
| Config file (front-end) | `web/vitest.config.ts` (Wave 0 — does not exist yet) |
| Quick run command (front-end) | `cd web && npx vitest run <file>` |
| Full suite command (front-end) | `cd web && npx vitest run` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | Streaming upload writes `source.<ext>` without buffering in memory | unit + integration | `pytest tests/test_upload_stream.py -x` | ❌ Wave 0 |
| INGEST-01 (memory) | Heap does not grow proportionally to file size during upload | integration | `pytest tests/test_upload_memory.py -x` (assert `tracemalloc` peak < threshold during a large fixture upload) | ❌ Wave 0 |
| INGEST-01 (atomic) | Crashed upload leaves no partial `source.<ext>` | unit | `pytest tests/test_upload_atomic.py -x` (abort mid-stream, assert no `source.<ext>` exists, only `.tmp_*` cleanup) | ❌ Wave 0 |
| INGEST-01 (race) | Worker does not pick up job mid-upload (status='uploading' invisible to pull_next) | unit + integration | `pytest tests/test_upload_race.py -x` (start slow upload, assert worker does not claim it; after enqueue, worker claims it) | ❌ Wave 0 |
| JOB-03 | Completed jobs appear in history list | integration | `pytest tests/test_history_list.py -x` (create + complete jobs, GET /jobs?status=done returns them newest-first) | ❌ Wave 0 (uses existing list_jobs) |
| JOB-03 (re-open) | Clicking a completed job loads its transcript | integration (FE) + e2e | `cd web && npx vitest run src/api/jobs.test.ts` (GET /jobs/{id}/transcript returns Transcript; 404 when none) | ❌ Wave 0 |
| UI-01 | 3-pane refined to history page + 2-pane detail | manual + FE unit | `cd web && npx vitest run src/pages/DetailPage.test.tsx` (2-pane grid renders transcript + summary placeholder) | ❌ Wave 0 |
| UI-02 | No embedded video player | manual + FE lint | grep test: `grep -r "<video" web/src/` returns no matches | ❌ Wave 0 (lint check) |
| UI-03 | Active transcript line highlighted on scroll | FE unit (jsdom) + manual | `cd web && npx vitest run src/hooks/useScrollSpy.test.ts` (mock IntersectionObserver, assert activeId updates) | ❌ Wave 0 |
| D-14 | GET /jobs/{id}/transcript returns Transcript, 404 when none | unit + integration | `pytest tests/test_transcript_endpoint.py -x` | ❌ Wave 0 |
| D-11 (idempotency) | Re-drop mid-upload collapses to existing job | integration | `pytest tests/test_upload_idempotency.py -x` (reuse existing idempotency test patterns) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit (back-end):** `pytest tests/test_upload_stream.py tests/test_transcript_endpoint.py -x` (new Phase 5 tests only)
- **Per task commit (front-end):** `cd web && npx vitest run` (FE unit tests)
- **Per wave merge:** `pytest` (full back-end suite — must stay green; 42 existing test files) + `cd web && npx vitest run`
- **Phase gate:** Full back-end + front-end suites green before `/gsd-verify-work`. The memory-bound guarantee test (tracemalloc peak assertion) MUST pass.

### Wave 0 Gaps
- [ ] `tests/test_upload_stream.py` — covers INGEST-01 (streaming write, atomic rename, race prevention, idempotency)
- [ ] `tests/test_upload_memory.py` — covers INGEST-01 memory-bound guarantee (`tracemalloc` peak < N MB during a >100MB fixture upload)
- [ ] `tests/test_transcript_endpoint.py` — covers D-14 (GET /jobs/{id}/transcript, 404 when none)
- [ ] `web/vitest.config.ts` — Vitest config for the new FE codebase (jsdom environment for scroll-spy + component tests)
- [ ] `web/src/test/setup.ts` — Vitest setup (mock IntersectionObserver, mock WebSocket, fetch polyfill via msw or vi.fn)
- [ ] `web/src/hooks/useScrollSpy.test.ts` — covers UI-03
- [ ] `web/src/api/jobs.test.ts` — covers JOB-03 (history list fetch + transcript fetch)
- [ ] FE framework install: `cd web && npm install -D vitest @testing-library/react jsdom` — if not present after `npm create vite`

*(Existing back-end test infrastructure (pytest, conftest.py, httpx ASGITransport) covers the integration test path — the new routes are tested via the same `httpx.AsyncClient` + FastAPI app pattern used by the 42 existing test files.)*

## Security Domain

> Single-user, no-auth, local-only app (PROJECT.md). `TrustedHostMiddleware` (allowed_hosts: localhost, 127.0.0.1, 0.0.0.0) is the boundary. No auth on upload/WS/control endpoints. The security posture is unchanged from Phase 4.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user, no-auth (PROJECT.md) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | TrustedHostMiddleware is the boundary (localhost-only) |
| V5 Input Validation | yes | `validate_source_ext` (path-traversal reject + allowlist) on the upload route; `validate_job_id` on the transcript route; strict-in Pydantic models |
| V6 Cryptography | no | No secrets in transit (localhost); `source_sha256` is optional/best-effort (Phase 4 D-04) |
| V12 Files & Resources | yes | `validate_source_ext` enforces an extension allowlist (mp4/mkv/webm/mov/mp3/wav/m4a/flac/ogg); atomic writes prevent partial files; `.tmp_*` cleanup on failure |

### Known Threat Patterns for FastAPI streaming upload

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via filename | Tampering | `validate_source_ext` rejects `..`, `/`, `\`, `:`, `*`, etc. (existing in `app/storage/fs.py`) |
| Partial file on crash | Tampering | Atomic write: `.tmp_<uuid>` → `fsync` → `os.replace` (retry on Windows AV locks) |
| Disk exhaustion / oversized upload | DoS | Back-end streams to disk (not memory); the OS disk is the limit. Consider a max-size guard if needed (not required for single-user local). |
| Worker race (job picked up mid-upload) | Tampering | Pre-queued `status='uploading'` (Pitfall 1) |
| Malicious idempotency key | Tampering | `validate_idempotency_key` (charset + 128-char cap, existing Phase 4) |
| CORS abuse | Spoofing | `CORSMiddleware` allow_origins restricted to `localhost:5173` + `127.0.0.1:5173` (existing in `app/main.py`) |

## Sources

### Primary (HIGH confidence)
- Codebase: `app/api/routes_jobs.py`, `app/main.py`, `app/jobs/queue.py`, `app/jobs/orchestrator.py`, `app/jobs/resume.py`, `app/jobs/manifest.py`, `app/jobs/service.py`, `app/storage/fs.py`, `app/storage/atomic.py`, `app/api/routes_ws.py`, `app/api/idempotency.py`, `app/models/job.py`, `app/models/transcript.py`, `app/models/manifest.py` — read directly, verified the actual FastAPI stack, the generalized `ingested` check, the worker poll cadence, the atomic-write pattern, the WS snapshot + relay contract, the idempotency flow, and the CORS config.
- npm registry (`npm view <pkg> version` + `time`) — verified vite 8.1.0, react 19.2.7, typescript 6.0.3, @vitejs/plugin-react 6.0.3, openapi-typescript 7.13.0, @tanstack/react-query 5.101.1, react-router 8.0.1, lucide-react 1.21.0, @radix-ui/react-dialog 1.1.17 (all with 2026 publish dates).
- pip index (`pip index versions`) — verified python-multipart 0.0.32 (installed 0.0.29), aiofiles 25.1.0 (installed).
- `.planning/phases/05-...-05-UI-SPEC.md` — the approved UI design contract (spacing scale, color, scroll-spy rootMargin, transcript row grid, routes, copywriting).

### Secondary (MEDIUM confidence)
- [FastAPI Request Files docs](https://fastapi.tiangolo.com/tutorial/request-files/) — UploadFile/SpooledTemporaryFile behavior.
- [FastAPI issue #3136](https://github.com/fastapi/fastapi/issues/3136) — `UploadFile.read(byte_count)` waits for full upload; `request.stream()` is the true streaming path.
- [StackOverflow: FastAPI UploadFile is slow](https://stackoverflow.com/questions/65342833/fastapi-uploadfile-is-slow-compared-to-flask) — `request.stream()` + `aiofiles` pattern.
- [MDN — XMLHttpRequest upload progress](https://developer.mozilla.org/en-US/docs/Web/API/XMLHttpRequest/upload) — `xhr.upload.onprogress`, `lengthComputable`, real acked-byte percent.
- [Chrome for Developers — fetch streaming requests](https://developer.chrome.com/docs/capabilities/web-apis/fetch-streaming-requests) — `duplex:"half"`, browser support, feature detection, progress caveats (now-inapplicable: the fetch path is NOT used; XHR-primary replaces it).
- [MDN — Intersection Observer API](https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API) — rootMargin, threshold, scroll-spy patterns.

### Tertiary (LOW confidence)
- [chriskirknielsen.com — Table of Contents Highlighter](https://chriskirknielsen.com/blog/simple-table-of-contents-highlighter/) — "last visible heading" fallback technique (adapted to pixel-offset fallback in Pattern 4).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all package versions verified on npm/pip registries with 2026 publish dates; back-end stack verified by reading the codebase.
- Architecture: HIGH — grounded in the actual codebase (FastAPI, the queue/worker poll cadence, the generalized ingested check, atomic writes, WS contract, CORS config); the race-condition finding is verified by reading `pull_next` (selects `status='queued'` only) and `create_job` (inserts `status='queued'`).
- Pitfalls: HIGH — Pitfall 1 (race), Pitfall 2 (UploadFile buffering), Pitfall 3 (source_path None) are all verified against the actual codebase; Pitfalls 4-6 are cited from official docs.
- Streaming upload: HIGH — `request.stream()` pattern verified via FastAPI docs + issue #3136 + StackOverflow; XHR-primary upload progress verified via MDN XMLHttpRequest upload docs; the fetch-streaming path is documented as NOT used (Open Questions #1/#2 RESOLVED).

**Research date:** 2026-06-23
**Valid until:** 2026-07-23 (30 days — stable stack; the FE versions are current as of June 2026)