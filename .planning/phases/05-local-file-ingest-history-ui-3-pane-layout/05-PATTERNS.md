# Phase 5: Local File Ingest + History UI + 3-Pane Layout - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 30 (7 back-end modifications/new tests + 23 greenfield FE files)
**Analogs found:** 7 / 30 (FE tree is greenfield — no in-repo analog; references UI-SPEC + framework defaults instead)

## File Classification

Legend — Match Quality:
- `exact` = same role AND same data flow
- `role-match` = same role, different data flow
- `partial` = different role, same data flow
- `none` = no in-repo analog (greenfield)

### Back-end (existing `app/` tree — modifications)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|----------|----------------|---------------|
| `app/api/routes_jobs.py` (ADD `POST /jobs/upload`, `GET /jobs/{id}/transcript`) | route / controller | request-response (streaming body in; JSON out) | `app/api/routes_jobs.py::post_job` + `get_job_by_id` (same file) | exact |
| `app/jobs/service.py` (ADD `create_upload_job`) | service | CRUD (DB insert + job dir + manifest) | `app/jobs/service.py::create_job` (same file) | exact |
| `app/models/job.py` (ADD `'uploading'` to `JobStatus` Literal) | model | config (schema literal) | `app/models/job.py::JobStatus` (same file) | exact |
| `app/jobs/queue.py` (WIDEN `enqueue` WHERE clause to include `'uploading'`) | service | event-driven (worker wake) | `app/jobs/queue.py::enqueue` (same file) | exact |
| `app/main.py` (verify CORS already configured — no change expected; no multipart dependency needed under XHR-primary) | config | request-response | `app/main.py::CORSMiddleware` block (same file) | exact |

### Back-end tests (new files under `tests/`)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|----------|----------------|---------------|
| `tests/test_upload_stream.py` | test | integration (httpx ASGI + streaming body) | `tests/test_idempotency.py` + `tests/test_post_jobs_201_response.py` | role-match |
| `tests/test_upload_memory.py` | test | integration (`tracemalloc` peak assertion) | `tests/conftest.py::client` fixture (reuse) + `tests/test_post_jobs_201_response.py` | role-match |
| `tests/test_upload_atomic.py` | test | unit (abort mid-stream, assert no `source.<ext>`) | `tests/test_atomic_windows_retry.py` (atomic-write cleanup pattern) | role-match |
| `tests/test_upload_race.py` | test | integration (worker does not claim `'uploading'` job) | `tests/test_cancel.py::_make_local_job` helper + `tests/conftest.py::run_worker_off` fixture | role-match |
| `tests/test_upload_idempotency.py` | test | integration (re-drop collapses to existing job) | `tests/test_idempotency.py::test_concurrent_race_integrity_error_no_orphan` | exact |
| `tests/test_transcript_endpoint.py` | test | integration (GET returns Transcript; 404 when none) | `tests/test_get_job_by_id.py` (the 404-on-miss pattern) + `tests/test_get_jobs.py` | role-match |
| `tests/test_history_list.py` | test | integration (completed jobs newest-first) | `tests/test_get_jobs.py::test_status_filter_returns_matching` + `test_list_orders_newest_first` | exact |

### Front-end (new `web/` tree — greenfield, no in-repo analog)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------------|------|-----------|----------------|---------------|
| `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html` | config | build (Vite + React-TS template) | `npm create vite@latest . -- --template react-ts` default output | none (framework default) |
| `web/src/main.tsx` | entry | bootstrap (QueryClientProvider + RouterProvider) | TanStack Query + React Router 8 docs quickstart | none (framework default) |
| `web/src/App.tsx` | route | request-response (route table) | React Router 8 `createBrowserRouter` pattern | none (UI-SPEC §5 + RESEARCH Pattern 3) |
| `web/src/api/client.ts` | utility | request-response (fetch wrapper) | RESEARCH §Pattern 2 + UI-SPEC §1 (Idempotency-Key derivation) | none (RESEARCH example) |
| `web/src/api/types.ts` | model | codegen (OpenAPI → TS) | `openapi-typescript` CLI default output; source = `app/main.py::_custom_openapi` (exposes `Transcript`/`TranscriptSegment`/`JobResponse` via `_EXTRA_OPENAPI_MODELS`) | none (codegen) |
| `web/src/api/jobs.ts` | hook / api client | request-response (TanStack Query) | RESEARCH §Pattern 3 example | none (RESEARCH example) |
| `web/src/api/ws.ts` | hook | event-driven (native WebSocket) | RESEARCH §Example 4 + `app/api/routes_ws.py` snapshot/event contract | partial (event shapes from back-end) |
| `web/src/components/DropZone.tsx` | component | file-I/O (drag-and-drop + `useUpload`) | UI-SPEC §1 (drop zone + full-window overlay contract) | none (UI-SPEC) |
| `web/src/components/ActiveJobCard.tsx` | component | event-driven (WS-driven card) | UI-SPEC §2 (lifecycle states + WS mapping) + `app/api/routes_ws.py` snapshot/event types | partial (event shapes from back-end) |
| `web/src/components/HistoryList.tsx`, `HistoryRow.tsx` | component | request-response (render `JobResponse[]`) | `app/models/job.py::JobResponse` (the row shape) + UI-SPEC §5/§6 | partial (data shape from back-end) |
| `web/src/components/TranscriptPane.tsx`, `TranscriptRow.tsx` | component | transform (render `TranscriptSegment[]`) | `app/models/transcript.py::TranscriptSegment` (row shape) + UI-SPEC §4 (CSS Grid: 64px \| 80px \| body) | partial (data shape from back-end) |
| `web/src/components/SummaryPane.tsx` | component | static (placeholder empty state) | UI-SPEC §6 (Summary Pane Placeholder copy) | none (UI-SPEC) |
| `web/src/components/ExportStub.tsx` | component | static (disabled button) | UI-SPEC §6 (Layout Stability Stub) | none (UI-SPEC) |
| `web/src/pages/HistoryPage.tsx` | page/route | composite (drop + active cards + history) | UI-SPEC §5 (route `/`) + RESEARCH §Pattern 3 | none (UI-SPEC) |
| `web/src/pages/DetailPage.tsx` | page/route | composite (2-pane transcript \| summary) | UI-SPEC §5 (route `/jobs/:id`) + RESEARCH §Example 5 (CSS Grid) | none (UI-SPEC) |
| `web/src/hooks/useScrollSpy.ts` | hook | event-driven (IntersectionObserver) | RESEARCH §Pattern 4 + UI-SPEC §3 (`rootMargin: "-49% 0px -49% 0px"`) | none (RESEARCH example) |
| `web/src/hooks/useUpload.ts` | hook | file-I/O (XHR-primary: `xhr.send(file)` raw octet-stream + `X-Filename` header, `xhr.upload.onprogress` 0→100%) | RESEARCH §Pattern 2 (XHR-primary, raw octet-stream) | none (RESEARCH example) |
| `web/src/styles.css` | config | static (CSS variables + grid) | UI-SPEC §Design System (spacing scale, color, typography) + RESEARCH §Example 5 | none (UI-SPEC) |
| `web/scripts/gen-types.sh` | utility | build (openapi-typescript codegen) | `openapi-typescript` CLI usage | none (tool default) |
| `web/vitest.config.ts` | config | test (Vitest jsdom env) | Vite+Vitest default config | none (framework default) |
| `web/src/test/setup.ts` | utility | test (mock `IntersectionObserver` / `WebSocket` / `fetch`) | RESEARCH §Validation Architecture (Wave 0 gaps) | none (RESEARCH) |
| `web/src/hooks/useScrollSpy.test.ts` | test | unit (mock IntersectionObserver) | Vitest + Testing Library default patterns | none (framework default) |
| `web/src/api/jobs.test.ts` | test | unit (mock fetch / msw) | Vitest + Testing Library default patterns | none (framework default) |
| `web/src/pages/DetailPage.test.tsx` | test | unit (jsdom render of 2-pane grid) | Vitest + Testing Library default patterns | none (framework default) |

## Pattern Assignments

### `app/api/routes_jobs.py` (route, request-response + streaming)

**Analog:** `app/api/routes_jobs.py::post_job` (lines 46-97) and `get_job_by_id` (lines 120-129) — same file.

**Imports pattern** (lines 20-43):
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import get_session, get_settings
from app.api.idempotency import resolve_or_create
from app.jobs.ids import validate_job_id
# ... service + model imports
```
New route additionally needs: `Header` from `fastapi`, `aiofiles`, `os`, `app.storage.fs.{source_path, validate_source_ext, transcript_path}`, `app.storage.atomic.retry_windows`, `app.jobs.queue.enqueue`, `app.jobs.manifest.{read_manifest, write_manifest}`, `app.jobs.service.create_upload_job`, `app.models.transcript.Transcript`.

**Idempotency + create pattern** (lines 76-97) — the new `POST /jobs/upload` reuses `resolve_or_create` with a `create_upload_job` callable:
```python
try:
    response, status_code = await resolve_or_create(
        request, session, settings,
        lambda job_id=None: create_upload_job(session, settings, job_id=job_id),
    )
except ValueError:
    raise HTTPException(status_code=422, detail="invalid Idempotency-Key")
return Response(content=response.model_dump_json(), media_type="application/json", status_code=status_code)
```

**404-on-miss + id validation pattern** (lines 120-129, 159-162) — the new `GET /jobs/{id}/transcript` mirrors `get_job_by_id` + `post_cancel`'s `validate_job_id` guard:
```python
try:
    canonical_id = validate_job_id(job_id)
except ValueError as exc:
    raise HTTPException(status_code=400, detail="invalid job id") from exc
# ... lookup; raise HTTPException(status_code=404, detail="transcript not found")
```

**What to replicate:** `APIRouter(prefix="/jobs", tags=["jobs"])` registration (already established — just add `@router.post("/upload", ...)` and `@router.get("/{job_id}/transcript", ...)` to the existing router); strict-in / lax-out at the boundary (D-15); `Response(content=..., status_code=...)` for per-response status codes; `validate_job_id` → 400 / `HTTPException(404)` for misses.
**What to change:** the upload route takes `request: Request` (not a JSON `payload`) and streams via `request.stream()` + `aiofiles`; do NOT call `update_stage("ingested")` (it sets `status="ingesting"` which blocks `enqueue` — Pitfall 3); patch `manifest.source_path` directly then `await enqueue(job_id, session)`. The transcript route returns the parsed `Transcript` (not `JobResponse`) and 404s when `transcript_path(...).exists()` is False.

---

### `app/jobs/service.py` (service, CRUD — DB insert + job dir + manifest)

**Analog:** `app/jobs/service.py::create_job` (lines 47-123) — same file.

**Imports pattern** (lines 20-35): `new_job_id`, `empty_manifest`, `write_manifest`, `JobResponse`, `ensure_job_dir`, `utcnow_iso`.

**Core INSERT + compensation pattern** (lines 68-115):
```python
if job_id is None:
    job_id = new_job_id()
now_iso = utcnow_iso()
await session.execute(
    text("INSERT INTO jobs (id, created_at, status, source_type, source_path, current_stage) "
         "VALUES (:id, :created_at, :status, :source_type, :source_path, :current_stage)"),
    {"id": job_id, "created_at": now_iso, "status": "queued", ...},
)
await session.commit()
try:
    await ensure_job_dir(settings, job_id)
    await write_manifest(settings, empty_manifest(job_id))
except Exception:
    # H5: compensation DELETE the just-INSERTed row, then re-raise
    await session.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
    await session.commit()
    raise
return JobResponse(id=job_id, status="queued", created_at=datetime.fromisoformat(now_iso), ...)
```

**What to replicate:** the INSERT → ensure_job_dir → write_manifest → compensation-DELETE-on-failure ordering (H5); `empty_manifest(job_id)` for the initial manifest; `JobResponse(...)` construction.
**What to change:** the INSERT hardcodes `status='queued'` — `create_upload_job` must INSERT `status='uploading'`, `source_type='local'`, `current_stage=NULL` (and no `source_path` yet). Returns `JobResponse(..., status="uploading", source_type="local")`. Everything else (folder + manifest + compensation) is identical.

---

### `app/models/job.py` (model, schema literal)

**Analog:** `app/models/job.py::JobStatus` (lines 11-21) — same file.

```python
JobStatus = Literal[
    "queued", "starting", "ingesting", "transcribing",
    "diarizing", "summarizing", "done", "failed", "cancelled",
]
```

**What to replicate:** nothing — `JobResponse` (lines 99-141) is unchanged; it already carries `status: JobStatus` and the `@field_serializer` for `created_at`/`updated_at` (the `+00:00` offset, not `Z`).
**What to change:** add `"uploading"` to the `JobStatus` Literal (Pitfall 1 + Assumption A3). Without this, `_row_to_response` (lines 160-188) fails strict validation when the upload route returns a `status='uploading'` row. No other model changes — `JobResponse`/`CreateJobRequest`/`ManifestPatch` stay as-is. The FE's TS types are codegen'd from the OpenAPI schema, so adding the Literal value propagates automatically via `openapi-typescript`.

---

### `app/jobs/queue.py` (service, event-driven — worker wake)

**Analog:** `app/jobs/queue.py::enqueue` (lines 52-80) — same file.

**Status-aware conditional UPDATE** (lines 66-73):
```python
result = await session.execute(
    text(
        "UPDATE jobs SET status = 'queued', updated_at = :now "
        "WHERE id = :id AND status IN ('created','queued')"
    ),
    {"now": utcnow_iso(), "id": job_id},
)
await session.commit()
if result.rowcount:
    _log.info("enqueue: job %s queued", job_id)
else:
    _log.info("enqueue: job %s not re-queued (terminal or active state)", job_id)
_work_signal.set()
```

**What to replicate:** the conditional UPDATE + `_work_signal.set()` wake (Fix 1 hybrid wakeup); the rowcount logging.
**What to change:** widen the `WHERE status IN ('created','queued')` clause to `('uploading','created','queued')` so an `'uploading'` job becomes queueable after the file lands. `pull_next` (lines 83-121) is UNCHANGED — it already selects `WHERE status = 'queued'` only, so `'uploading'` jobs stay invisible to the worker (Pitfall 1). `cancel` and `run_watchdog` are unchanged.

---

### `app/main.py` (config, request-response — CORS)

**Analog:** `app/main.py::CORSMiddleware` block (lines 411-417) — same file.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
    allow_credentials=False,
)
```

**What to replicate:** nothing to change — CORS already allows the Vite dev origin (`:5173`) and the `POST` method the upload route needs. The `TrustedHostMiddleware` (lines 418-421) allow-lists `localhost` / `127.0.0.1` / `0.0.0.0`, which the FE dev server hits as `localhost`.
**What to change:** verify the dev port (A2 — Vite default is 5173). If the FE dev server ends up on a different port, add it to `allow_origins`. Optionally add `OPTIONS` to `allow_methods` (CORS preflight) if the streaming upload triggers a preflight. The OpenAPI patch (`_EXTRA_OPENAPI_MODELS`, lines 359-409) already registers `Transcript`/`TranscriptSegment` so the codegen sees them — no schema work needed.

---

### `tests/test_upload_stream.py` (test, integration — streaming upload)

**Analog:** `tests/test_idempotency.py` (full file) + `tests/test_post_jobs_201_response.py` (full file) + `tests/conftest.py::client` fixture (lines 122-129).

**Client fixture pattern** (`tests/conftest.py:122-129`):
```python
@pytest_asyncio.fixture
async def client(app_under_test: object) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app_under_test)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        yield ac
```

**Job-creation + assertion pattern** (`tests/test_post_jobs_201_response.py:48-65`):
```python
@pytest.mark.asyncio
async def test_live_post_jobs_returns_job_response_shape(client: httpx.AsyncClient) -> None:
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "id" in body
    assert body["status"] == "queued"
```

**Idempotency-key header pattern** (`tests/test_idempotency.py:60-71`):
```python
headers = {"Idempotency-Key": "abc"}
r1 = await client.post("/jobs", json={}, headers=headers)
assert r1.status_code == 201, r1.text
```

**What to replicate:** `@pytest.mark.asyncio` + the `client` fixture (no worker auto-start — `tmp_data_dir` writes `run_worker=False`); `httpx.ASGITransport` for in-process routing through `TrustedHostMiddleware`; assert on `resp.status_code` + `resp.json()["id"]`/`["status"]`; reuse the `_count_jobs_with_key` helper pattern for orphan assertions.
**What to change:** POST to `/jobs/upload` with `headers={"Idempotency-Key": ..., "X-Filename": "video.mp4", "Content-Type": "application/octet-stream"}` and `content=b"<bytes>"` (not `json={}`); assert `source.mp4` exists in `job_dir(settings, id)` after the call and that the row is `status='queued'` (not `'uploading'` — `enqueue` should have flipped it). Use `app.state.settings` to resolve the data dir (`tests/test_idempotency.py:45` shows the pattern: `Path(app.state.settings.data_dir) / "jobs" / job_id`).

---

### `tests/test_upload_memory.py` (test, integration — `tracemalloc` peak)

**Analog:** `tests/conftest.py::client` fixture + `tests/test_post_jobs_201_response.py`.

**What to replicate:** the `client` fixture; the `httpx` POST pattern.
**What to change:** wrap the upload in `tracemalloc.start()` / `tracemalloc.get_traced_memory()`; upload a >100MB fixture (generate in-test with `b"\x00" * N` streamed via `httpx` content); assert the peak is well below the file size (the back-end `request.stream()` + `aiofiles` path must NOT buffer the whole body — Pitfall 2). Reuse the `run_worker_off` fixture (`tests/conftest.py:556-571`) so the worker does not pick the job up mid-test.

---

### `tests/test_upload_atomic.py` (test, unit — abort mid-stream)

**Analog:** `tests/test_atomic_windows_retry.py` (atomic-write cleanup pattern).

**What to replicate:** the temp-file cleanup assertion style (assert no `source.<ext>` exists, only `.tmp_*` or nothing).
**What to change:** start a streaming POST, abort the `httpx` request mid-body (use `httpx.AsyncClient.stream(...)` + `ac.aclose()` after N bytes), then assert `job_dir(...).glob("source.*")` is empty and `.tmp_*` files are cleaned up (the route's `except BaseException: os.unlink(tmp)` — RESEARCH §Pattern 1 lines 295-298).

---

### `tests/test_upload_race.py` (test, integration — worker invisible to `'uploading'`)

**Analog:** `tests/test_cancel.py::_make_local_job` (lines 58-76) + `tests/conftest.py::run_worker_off` (lines 556-571).

**Local-source job helper** (`tests/test_cancel.py:58-76`):
```python
async def _make_local_job(s: Settings, sf) -> str:
    async with sf() as session:
        job = await create_job(session, s, source_type="local")
        job_id = job.id
        await ensure_job_dir(s, job_id)
        src = job_dir(s, job_id) / "source.mp4"
        src.write_bytes(b"\x00" * 16)
        # ... patch manifest.source_path, UPDATE jobs, commit
    return job_id
```

**What to replicate:** the manual `_session_factory` + `make_engine` + `apply_migrations` setup (lines 50-55); the `run_worker=False` settings opt-out; the direct `UPDATE jobs SET status=...` test-only bypass (lines 79-80 of `test_cancel.py`).
**What to change:** start a slow upload (status `'uploading'`), manually call `pull_next(session)` (or drive `run_worker` for one tick), assert it returns `None` (no `'uploading'` job is claimed). Then `await enqueue(job_id, session)`, call `pull_next` again, assert it returns the job_id.

---

### `tests/test_upload_idempotency.py` (test, integration — re-drop collapses)

**Analog:** `tests/test_idempotency.py::test_concurrent_race_integrity_error_no_orphan` (lines 124-144) — exact match.

**Race + orphan-count pattern** (lines 124-144):
```python
headers = {"Idempotency-Key": "race-key-001"}
r1 = await client.post("/jobs", json={}, headers=headers)
assert r1.status_code == 201, r1.text
job_id_a = r1.json()["id"]
r2 = await client.post("/jobs", json={}, headers=headers)
assert r2.status_code == 200, r2.text
assert r2.json()["id"] == job_id_a
assert _count_jobs_with_key(client, "race-key-001") == 1
```

**What to replicate:** the precise 201/200 status-code split; the orphan-count assertion via `_count_jobs_with_key`; the duplicate-key header pattern.
**What to change:** POST to `/jobs/upload` instead of `/jobs`, with `X-Filename` + octet-stream content. The Idempotency-Key derivation in the FE (UI-SPEC §1 — `[filename]-[size]-[lastmodified]` hashed to stay under 128 chars, RESEARCH §Open Questions #3) is a FE concern; the back-end test just sends a fixed key.

---

### `tests/test_transcript_endpoint.py` (test, integration — GET returns Transcript; 404)

**Analog:** `tests/test_get_job_by_id.py` (404-on-miss pattern) + `tests/test_get_jobs.py` (route assertions).

**What to replicate:** the `client.get("/jobs/{id}/...")` + `assert resp.status_code == 404` pattern; the `await client.post("/jobs", json={})` setup to create a job.
**What to change:** create a job, write a real `transcript.json` via `app.jobs.manifest.write_manifest`-equivalent (or directly `transcript_path(settings, id).write_text(Transcript(...).model_dump_json())`), then `GET /jobs/{id}/transcript` and assert the returned JSON has `segments: [...]` and the `Transcript` shape. Also test the 404 path (no transcript file yet → `{"detail": "transcript not found"}`).

---

### `tests/test_history_list.py` (test, integration — completed jobs newest-first)

**Analog:** `tests/test_get_jobs.py::test_status_filter_returns_matching` (lines 30-44) + `test_list_orders_newest_first` (lines 13-27) — exact match.

**Status-filter + ordering pattern** (lines 30-44):
```python
resp = await client.get("/jobs", params={"status": "queued"})
assert resp.status_code == 200
items = resp.json()
assert all(j["status"] == "queued" for j in items)
```

**What to replicate:** the `client.get("/jobs", params={"status": ...})` call; the ordering index assertion (`ids.index(b["id"]) < ids.index(a["id"])`).
**What to change:** create jobs, force them to terminal states (`done`/`failed`/`cancelled`) via direct `UPDATE jobs SET status=...` (the test-only bypass from `tests/test_cancel.py:79-80`), then assert `GET /jobs?status=done` returns them newest-first and excludes active/queued jobs. Reuses the existing `list_jobs` service (no back-end change).

---

### Front-end files (no in-repo analog — use UI-SPEC + RESEARCH + framework defaults)

The entire `web/` tree is greenfield. There is NO existing React/TS/JS code in the repo (confirmed: no `package.json`, no `web/`, no `.ts`/`.tsx` outside `.planning/`). Each FE file's "analog" is one of:

1. **Framework default** — `npm create vite@latest . -- --template react-ts` output for `package.json`/`tsconfig.json`/`vite.config.ts`/`index.html`/`main.tsx`/`App.tsx`. The planner should scaffold via that command and not hand-write these.
2. **UI-SPEC contract** — `05-UI-SPEC.md` is the design lead:
   - §Design System → `styles.css` (spacing scale tokens xs=4px…3xl=64px, color palette `#FAFAFA`/`#FFFFFF`/`#2563EB`/`#DC2626`, typography 14/12/20/28px, system font stack)
   - §1 Drop Zone → `DropZone.tsx` + `useUpload.ts`
   - §2 Active-Job Card → `ActiveJobCard.tsx` + `api/ws.ts`
   - §3 Scroll-Spy → `useScrollSpy.ts` (`rootMargin: "-49% 0px -49% 0px"`, 4px accent border, `rgba(37,99,235,0.05)` tint)
   - §4 Transcript Row → `TranscriptRow.tsx` (CSS Grid `64px 80px 1fr`, line-height 1.5)
   - §5 Routes → `App.tsx` (`/`, `/jobs/:id`), `HistoryPage.tsx`, `DetailPage.tsx`
   - §6 States → `SummaryPane.tsx` ("Summaries will appear here once summarization is enabled"), `ExportStub.tsx` (disabled "Export (Coming Soon)"), empty-state copy
3. **RESEARCH code examples** — `05-RESEARCH.md` has ready-to-paste excerpts:
   - §Pattern 2 → `useUpload.ts` (XHR-primary: `xhr.send(file)` raw octet-stream body + `X-Filename` header + `xhr.upload.onprogress` 0→100%; no fetch/duplex, no multipart)
   - §Pattern 3 → `api/jobs.ts` (`useQuery({queryKey: ["jobs","done"], queryFn: ...})`)
   - §Pattern 4 → `useScrollSpy.ts` (full `IntersectionObserver` + pixel-offset fallback)
   - §Example 4 → `api/ws.ts` (`useJobEvents(jobId)` native WebSocket hook)
   - §Example 5 → `DetailPage.tsx`/`styles.css` (CSS Grid 60%|40%, transcript row grid)
4. **Back-end contract** — the FE consumes the existing back-end; the type source is the OpenAPI schema:
   - `app/api/routes_ws.py` lines 180-188 — the `{type:"snapshot", job_id, stage, percent, eta, status}` shape + live `{type:"progress"|"stage_changed"|"done"|"failed"|"cancelled"}` events — `api/ws.ts` must parse these.
   - `app/models/job.py::JobResponse` (lines 99-141) — `HistoryRow`/`HistoryList` render `id`/`status`/`created_at`/`duration_s`/`source_path` (filename derived). Codegen via `openapi-typescript http://localhost:8000/openapi.json -o web/src/api/types.ts`.
   - `app/models/transcript.py::TranscriptSegment` — `TranscriptRow` renders `start_s` (formatted `[mm:ss]`), `text`, leaves `speaker` gutter empty (Phase 7).
   - `app/main.py::_EXTRA_OPENAPI_MODELS` (lines 359-380) — already registers `Transcript`/`TranscriptSegment` so the codegen sees them. No back-end schema work.
5. **Framework test defaults** — `web/vitest.config.ts` + `web/src/test/setup.ts` follow the Vitest jsdom + Testing Library standard setup; mock `IntersectionObserver`/`WebSocket`/`fetch` per RESEARCH §Validation Architecture Wave 0 gaps.

The planner should treat the FE files as "follow the UI-SPEC + RESEARCH excerpts verbatim" rather than "find an in-repo analog." No `## No Analog Found` listing needed — the entire FE block is uniformly greenfield and is mapped to UI-SPEC/RESEARCH above.

## Shared Patterns

### Strict-in / lax-out at the API boundary (D-15)
**Source:** `app/models/job.py::CreateJobRequest` (lines 38-41, `ConfigDict(strict=True, extra="forbid")`), `JobResponse` (lines 114, `strict=True, extra="forbid"` — but the lax output is the `datetime` iso serialization, not a relaxed schema).
**Apply to:** the new `POST /jobs/upload` route — it takes NO request body model (the file is read via `request.stream()` and the filename via the `X-Filename` header, per D-15 strict-in at the boundary). If a request body model were ever added, it MUST be `strict=True, extra="forbid"`. The `JobResponse` output stays as-is; the `Transcript` output is already lax (`app/models/transcript.py` — no `strict=True`, `speaker`/`confidence` optional).

### Atomic writes (Phase 1 D-04)
**Source:** `app/storage/atomic.py::atomic_write_bytes` (lines 31-58) — tmp + `aiofiles` + `fsync` + `retry_windows(os.replace)` + `except BaseException: os.unlink(tmp)`.
**Apply to:** the upload route. The RESEARCH §Pattern 1 excerpt (lines 287-298) shows the exact tmp → `os.replace` flow with `retry_windows`. The route should either reuse `atomic_write_bytes` (but it takes `bytes`, not a stream) or mirror its structure with `aiofiles.open(tmp, "wb")` + `request.stream()` + `os.fsync` + `retry_windows(os.replace, tmp, final)`. The `except BaseException` cleanup is mandatory so a crashed upload leaves no `.tmp_*` the orchestrator picks up.

### Idempotency-Key flow (Phase 4 D-07)
**Source:** `app/api/idempotency.py::resolve_or_create` (lines 87-243) + `validate_idempotency_key` (lines 60-84).
**Apply to:** the `POST /jobs/upload` route — call `resolve_or_create(request, session, settings, lambda job_id=None: create_upload_job(...))` exactly as `post_job` does (lines 76-88). The header validation (charset `[A-Za-z0-9_-]`, 128-char cap), the atomic key-first reservation, the IntegrityError → re-read-existing-job path, and the 422-on-invalid-header mapping are all reused unchanged. The FE must derive the key from `[filename]-[size]-[lastmodified]` and hash to stay under 128 chars (UI-SPEC §1 + RESEARCH §Open Questions #3).

### File-as-truth `ingested` check (Phase 1 D-11/D-12 + Phase 4 D-04)
**Source:** `app/jobs/resume.py::is_stage_complete` (lines 157-181) — checks `manifest.source_path` resolves FIRST, THEN falls back to in-job-dir `source.<ext>`.
**Apply to:** the upload route's post-write step — after `os.replace` lands `source.<ext>`, patch `manifest.source_path = str(final_path)` and `manifest.source_type = "local"` via `read_manifest` → `model_copy(update=...)` → `write_manifest` (RESEARCH §Pattern 1 lines 300-302). Do NOT call `update_stage("ingested")` (Pitfall 3 — it sets `status="ingesting"` which blocks `enqueue`). The generalized `ingested` check already accepts the in-job-dir variant, so the orchestrator skips ingest and goes straight to transcribing once the file lands.

### Worker race prevention (Pitfall 1)
**Source:** `app/jobs/queue.py::pull_next` (lines 83-121, selects `WHERE status='queued'` only) + `enqueue` (lines 52-80, conditional `WHERE status IN ('created','queued')`).
**Apply to:** the upload route's job-creation step — `create_upload_job` MUST insert `status='uploading'` (not `'queued'`) so `pull_next` never sees it mid-stream; after `os.replace`, `await enqueue(job_id, session)` flips it to `'queued'`. Widen `enqueue`'s `WHERE status IN (...)` to include `'uploading'` (see File Classification row 4). `pull_next` and `run_worker` are unchanged.

### Test fixtures (back-end)
**Source:** `tests/conftest.py` — `tmp_data_dir` (lines 34-93, writes `run_worker=False` settings), `app_under_test` (lines 95-119, drives the lifespan manually), `client` (lines 122-129, `httpx.ASGITransport`), `run_worker_off` (lines 556-571, sanity assertion).
**Apply to:** ALL new back-end tests. Reuse the `client` fixture as-is — do NOT add a new fixture. For tests that need a manual worker, use the `_session_factory` + `make_engine` + `apply_migrations` setup from `tests/test_cancel.py:50-55`. For tests that need a local-source job, reuse `_make_local_job` (`tests/test_cancel.py:58-76`). For DB-path introspection, reuse `Path(app.state.settings.data_dir) / "app.db"` + `sqlite3.connect` (`tests/test_idempotency.py:45-54`). WS tests must use `starlette.testclient.TestClient.websocket_connect` (httpx cannot do WS — `tests/test_ws.py:28-49`).

### Error handling / HTTPException mapping
**Source:** `app/api/routes_jobs.py` — `validate_job_id` → 400 (lines 159-162), `FileNotFoundError` → 404 (lines 204-205), `ValidationError` → 422 (lines 206-207), `ValueError` (idempotency) → 422 (lines 89-92).
**Apply to:** the new upload + transcript routes. The transcript route maps `ValueError` from `validate_job_id` → 400, missing `transcript.json` → 404. The upload route maps `ValueError` from `validate_source_ext` (bad extension) → 400 or 422 (planner's call — match the existing 422 convention for validation), `ValueError` from `validate_idempotency_key` → 422, and `BaseException` during stream → cleanup + re-raise (FastAPI returns 5xx).

## No Analog Found

The entire front-end `web/` tree has no in-repo analog (confirmed: no `package.json`, no `web/`, no `.ts`/`.tsx` outside `.planning/`). Each FE file is mapped to UI-SPEC §section + RESEARCH §Pattern/Example + framework defaults in the File Classification table above — the planner should reference those directly rather than search for in-repo analogs. No individual `No Analog Found` row is needed; the FE block is uniformly greenfield.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `web/**` (all 23 FE files) | various | various | Greenfield — no existing React/TS/JS code in the repo. Patterns sourced from `05-UI-SPEC.md` + `05-RESEARCH.md` §Patterns 2-4 + §Examples 4-5 + Vite/React-Router/TanStack-Query/Vitest framework defaults. |

## Metadata

**Analog search scope:**
- `app/api/` (routes_jobs.py, routes_ws.py, idempotency.py, dependencies.py)
- `app/jobs/` (service.py, queue.py, manifest.py, resume.py, orchestrator.py, cleanup.py)
- `app/storage/` (fs.py, atomic.py)
- `app/models/` (job.py, transcript.py, manifest.py, settings.py)
- `app/main.py`
- `tests/` (conftest.py, test_idempotency.py, test_post_jobs_201_response.py, test_get_jobs.py, test_get_job_by_id.py, test_cancel.py, test_ws.py, test_atomic_windows_retry.py)
- Repo root (no `web/`, no `package.json`, no FE code)
- No `CLAUDE.md`, no `.claude/skills/`, no `.agents/skills/` — project-context step had nothing to load.

**Files scanned:** ~20 source files + 8 test files + repo-root listing.
**Pattern extraction date:** 2026-06-23