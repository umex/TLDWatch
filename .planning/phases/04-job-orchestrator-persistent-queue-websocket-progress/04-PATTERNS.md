# Phase 04: Job Orchestrator + Persistent Queue + WebSocket Progress - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 13 new/modified
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/jobs/orchestrator.py` (NEW) | service | event-driven / batch | `app/jobs/reconcile.py` + `app/jobs/cleanup.py` | role-match (async loop + UPDATE pattern) |
| `app/jobs/queue.py` (NEW) | service | CRUD | `app/jobs/service.py` (`list_jobs` SELECT pattern) | role-match |
| `app/jobs/progress.py` (NEW) | service / provider | pub-sub | `app/api/routes_models.py` SSE in-memory `_in_flight` dict | partial (different transport — WS vs SSE, but same in-process registry pattern) |
| `app/jobs/interrupt.py` (NEW) | service | batch | `app/jobs/reconcile.py` | exact (boot sweep, same shape) |
| `app/jobs/watchdog.py` (NEW, optional split) | service | event-driven | `app/jobs/cleanup.py::mark_stale` | role-match |
| `app/api/routes_ws.py` (NEW) | route / controller | streaming | `app/api/routes_models.py` (SSE `event_generator`) + `app/api/routes_jobs.py` (router pattern) | role-match |
| `migrations/0008_idempotency_keys.sql` (NEW) | migration | — | `migrations/0001_initial.sql` (CREATE TABLE IF NOT EXISTS) | exact |
| `app/api/routes_jobs.py` (MODIFIED) | route / controller | request-response | itself + `app/jobs/service.py::create_job` | exact |
| `app/models/job.py` (MODIFIED) | model | — | itself (add WS event models alongside `JobResponse`) | exact |
| `app/models/stt/protocol.py` (MODIFIED) | model / protocol | — | itself (kw-only superset, mirrors 03-02 `decode_audio` addition) | exact |
| `app/models/stt/chunker.py` (MODIFIED) | service | transform / streaming | itself (chunk loop already the seam for progress_cb + cancel_flag) | exact |
| `app/jobs/resume.py` / `manifest.py` (MODIFIED) | service | — | itself (refine `ingested` branch per D-04) | exact |
| `app/main.py` lifespan (MODIFIED) | config | event-driven | itself (insert sweep + worker + watchdog tasks between `reconcile_all` and `yield`) | exact |
| `tests/conftest.py` (MODIFIED) | test | — | itself (`mock_stt_adapter` + `tmp_data_dir` + `app_under_test` pattern) | exact |

## Pattern Assignments

### `app/jobs/orchestrator.py` (service, event-driven / batch)

**Analogs:** `app/jobs/reconcile.py` (async loop + per-job session) + `app/jobs/cleanup.py` (DB UPDATE pattern) + `app/models/manager.py` (asyncio task lifecycle)

**Imports pattern** — copy from `app/jobs/reconcile.py` lines 31-43:
```python
from __future__ import annotations

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.manifest import update_stage, read_manifest
from app.jobs.cleanup import cancel_job, mark_failed
from app.jobs.resume import infer_resume_point
from app.models.settings import Settings

_log = logging.getLogger(__name__)
```

**Async session-per-job pattern** — copy from `app/jobs/reconcile.py` lines 97-107 (open a short-lived session per job, keep tx scope small):
```python
async with session_factory() as session:
    result = await session.execute(
        text("SELECT ... FROM jobs WHERE id = :id"),
        {"id": entry},
    )
    row = result.fetchone()
    ...
    await session.execute(text("UPDATE jobs SET ... WHERE id = :id"), {...})
    await session.commit()
```

**Worker=1 FIFO poll+signal loop** — RESEARCH Pattern 4; the `reconcile_all` `for entry in sorted(os.listdir(...))` (reconcile.py:76) is the analog for "iterate the work list"; the hybrid `asyncio.Event` + `asyncio.wait_for(signal.wait(), timeout=2.0)` is new (no existing analog — use RESEARCH Pattern 4 verbatim).

**Stage transition call** — the orchestrator's every transition goes through `update_stage`; reuse the exact call shape from `app/api/routes_jobs.py` lines 148-156:
```python
manifest = await update_stage(
    settings, session, canonical_id, payload.stage, payload.manifest_patch
)
```
The orchestrator passes a `ManifestPatch` carrying ingest metadata (`source_path`, `duration_s`, `language`).

**Cooperative cancel — threading.Event, NOT asyncio** — RESEARCH Pattern 5 (VERIFIED: chunker.py:80 `transcribe_file` is sync; protocol.py:104 `transcribe` is sync). The orchestrator runs transcribe via `await loop.run_in_executor(None, transcribe_file, ...)`; `cancel_flag.is_set()` is callable from the worker thread. Store `cancel_flag` in `orchestrator._running: dict[job_id, threading.Event]`. No existing analog — the `threading.Event` + `release_event` pattern in `tests/conftest.py` lines 336-382 (`slow_mock_hf_hub_download`) is the closest threading-Evergreen reference.

**Error handling** — mirror `app/jobs/cleanup.py::mark_failed` (cleanup.py:88-102) for the failure path: `UPDATE jobs SET status='failed', error=:error, updated_at=:now WHERE id=:id` + commit. Orchestrator wraps each stage in try/except and calls `mark_failed` + `bus.publish(job_id, {"type":"failed", "error":...})`.

---

### `app/jobs/queue.py` (service, CRUD)

**Analog:** `app/jobs/service.py::list_jobs` (service.py:117-155) — the SELECT-from-`jobs` pattern.

**Next-queued SELECT** — copy the `list_jobs` SQLAlchemy Core select pattern (service.py:131-150); for FIFO serial dispatch, ORDER BY `created_at` ASC (not DESC like `list_jobs`) with `WHERE status='queued' LIMIT 1`:
```python
base_query = (
    sa.select(sa.column("id"), sa.column("created_at"), sa.column("status"),
              sa.column("source_type"), sa.column("source_path"))
    .select_from(sa.table("jobs"))
    .where(sa.column("status") == "queued")
    .order_by(sa.column("created_at").asc())
    .limit(1)
)
result = await session.execute(base_query)
```
Re-join on restart is automatic: a job left `queued` in SQLite is still `queued` after the boot interrupted sweep (D-03 only marks `ingesting`/`transcribing` failed — `queued` jobs re-join).

**Imports pattern** — copy `app/jobs/service.py` lines 20-35 (sqlalchemy as sa, AsyncSession, text, utcnow_iso, Settings).

---

### `app/jobs/progress.py` (service / provider, pub-sub)

**Analog:** `app/api/routes_models.py::_in_flight` in-process registry (the SSE pattern) — same "dict keyed by id, mutated by worker, drained by stream" shape, only the transport differs (SSE polling vs WS queue pub/sub).

**In-process registry pattern** — `routes_models.py` keeps a module-level `_in_flight: dict[str, DownloadProgress]` and the SSE generator polls it. Phase 4 inverts this to push-based: `dict[job_id → list[asyncio.Queue]]` per RESEARCH Pattern 1. Use that Pattern 1 excerpt verbatim — no existing codebase analog for `put_nowait` + drop-oldest backpressure.

**Threading marshalling** — the worker thread (running `transcribe_file` via `run_in_executor`) calls `progress_cb` from off-loop; the orchestrator wraps it:
```python
loop = asyncio.get_running_loop()
def _on_progress(p: ChunkProgress) -> None:
    loop.call_soon_threadsafe(bus.publish, job_id, {"type":"progress", **p.__dict__})
```
No existing analog; this is the load-bearing bridge between sync chunker and asyncio bus.

---

### `app/jobs/interrupt.py` (service, batch)

**Analogs:** `app/jobs/reconcile.py` (exact shape) + `app/jobs/cleanup.py::mark_failed` (the UPDATE).

**Function signature** — mirror `reconcile_all` (reconcile.py:48-51):
```python
async def mark_interrupted_failed(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
```

**Body** — a single bulk UPDATE (no per-job loop needed, unlike `reconcile_all` which reads manifests). Per RESEARCH Pattern 6:
```python
async with session_factory() as session:
    await session.execute(
        text(
            "UPDATE jobs SET status='failed', "
            "error='interrupted (backend restarted)', updated_at=:now "
            "WHERE status IN ('ingesting','transcribing')"
        ),
        {"now": utcnow_iso()},
    )
    await session.commit()
```
`queued` jobs are NOT touched (they re-join the queue). `done`/`failed`/`cancelled` are untouched (not in the IN list). This matches `_TERMINAL_STATUSES` in cleanup.py:40.

---

### `app/jobs/watchdog.py` (service, event-driven)

**Analog:** `app/jobs/cleanup.py::mark_stale` (cleanup.py:120-155) — already status-aware (short-circuits terminal statuses via `_TERMINAL_STATUSES`, cleanup.py:148-149).

**Watchdog loop** — a single asyncio task on a cadence (60s recommended) that scans active jobs and calls `mark_stale`. The per-job `mark_stale` is reused as-is. The watchdog is just a loop wrapper:
```python
async def watchdog_loop(settings, session_factory, interval_s=60):
    while True:
        async with session_factory() as session:
            # SELECT id FROM jobs WHERE status IN ('ingesting','transcribing')
            # for each: await mark_stale(session, settings, id, threshold_s=600)
        await asyncio.sleep(interval_s)
```
The `is_stale` default `threshold_s=600` (cleanup.py:105) already matches D-13's 10-min threshold — reuse, do not redefine.

---

### `app/api/routes_ws.py` (route / controller, streaming)

**Analogs:** `app/api/routes_jobs.py` (router pattern) + `app/api/routes_models.py::download_progress_sse` (streaming-on-a-job-id pattern).

**Router pattern** — copy `app/api/routes_jobs.py` line 41:
```python
from fastapi import APIRouter, Depends
router = APIRouter(prefix="/ws/jobs", tags=["ws"])
```
Register in `app/main.py` alongside the other routers (main.py:330-334) via `app.include_router(ws_router)`.

**WebSocket handler shape** — use RESEARCH Pattern 2 verbatim. The SSE `event_generator` in `routes_models.py:236-267` is the closest existing codebase analog for "loop + pull + yield"; the WS version swaps `yield` for `await ws.send_json(...)` and the SSE-poll for a `await queue.get()` blocking pull (no busy-poll, no 0.1s sleep). Snapshot-on-connect is new (no analog).

**Snapshot build** — read the manifest via `app.jobs.manifest.read_manifest(settings, job_id)` (manifest.py:129-140) — raises `FileNotFoundError` (map to WS close code 1008) — plus the DB row via `get_job` for `status`. Emit `{"type":"snapshot","status":...,"current_stage":...,"percent":...,"eta":...}` as the first frame.

**Subscriber cap (DoS mitigation)** — Security Domain V5: cap subscribers per `job_id` to 16; reject extra with `WebSocket.close(code=1008)` before `ws.accept()`.

---

### `migrations/0008_idempotency_keys.sql` (migration)

**Analogs:** `migrations/0001_initial.sql` (CREATE TABLE IF NOT EXISTS pattern) + `migrations/0002_add_source_sha256.sql` (one-line ALTER pattern).

**Content** — follow the 0001 `CREATE TABLE IF NOT EXISTS` idempotent style (0001_initial.sql:6-9):
```sql
-- Migration 0008: idempotency_keys table for POST /jobs Idempotency-Key (D-07).
-- Idempotent: CREATE TABLE IF NOT EXISTS so re-running is safe.

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_idempotency_keys_created_at
    ON idempotency_keys(created_at);
```
The `created_at` index supports the TTL janitor (`WHERE created_at < :cutoff`). The runner in `app/storage/db.py::apply_migrations` (db.py:94-203) handles `schema_version` recording and the duplicate-column guard automatically — no extra wiring.

**Naming convention** — `NNNN_description.sql` (db.py:131-135 enforces the int prefix parse). Next number is `0008` (migrations/ dir currently ends at `0007_add_stage_timestamps_json.sql`).

---

### `app/api/routes_jobs.py` (MODIFIED — idempotency)

**Analog:** itself + `app/jobs/service.py::create_job` (the INSERT path to wrap).

**POST /jobs idempotency-key handling** — add header reading before the existing `create_job` call (routes_jobs.py:44-59). Per RESEARCH Pattern 3:
```python
@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def post_job(
    payload: CreateJobRequest,
    request: Request,                                # NEW
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    key = request.headers.get("Idempotency-Key")
    if key:
        # validate charset/length (V5): ^[A-Za-z0-9_-]{1,128}$
        # SELECT job_id FROM idempotency_keys WHERE key=? AND created_at > :cutoff
        # on hit: return JSONResponse(existing, status_code=200)
    job = await create_job(session, settings, source_type=payload.source_type,
                           source_path=payload.source_path)
    if key:
        # INSERT INTO idempotency_keys(key, job_id, created_at) VALUES (?,?,?)
        # except IntegrityError -> re-read existing, return 200
    return job
```
Import `from fastapi import Request` and `from starlette.responses import JSONResponse`. The existing `create_job` (service.py:47-114) is unchanged — idempotency wraps it (pre-check + post-insert), mirroring how `create_job` already wraps the INSERT with H5 compensation (service.py:80-106).

**`/stage` + `/stale-check` routes** — CONTEXT D-11 / canonical_refs say "admin-only or removed (planner decides — single-user no-auth)". The orchestrator now drives stages via the service layer (not HTTP); these routes become admin-only or are removed. They are NOT deleted in the pattern map — planner decides.

**Cancel route** — the existing `post_cancel` (routes_jobs.py:94-118) already calls `cancel_job` (DB-first + rmtree). Phase 4 adds: if the job is running, set `orchestrator._running[job_id]` cancel flag first (cooperative), then let the worker call `cancel_job` after the current chunk; if terminal, no-op returning the current row (D-06). The route body's `validate_job_id` + `HTTPException(400/404)` pattern (routes_jobs.py:107-117) is reused unchanged.

---

### `app/models/job.py` (MODIFIED — WS event models)

**Analog:** itself — add event models alongside `JobResponse` (job.py:98-139).

**Strict-in / lax-out** — per CONTEXT "Established Patterns": new request models (`Idempotency-Key` is a header, no body model needed) and event payloads are strict-in at the API boundary; `JobResponse` and event models stay lax-out (job.py:113 `model_config = ConfigDict(strict=True, extra="forbid")` is the response — event models should use `extra="allow"` or omit strict for lax-out).

**Event model shape** — discriminator union (`type: Literal["stage_changed","progress","done","failed","cancelled","snapshot"]`); mirror `StageUpdateRequest` (job.py:69-80) for strict-in style if events are ever request bodies (they are NOT — they are server-emitted, so lax-out).

---

### `app/models/stt/protocol.py` (MODIFIED — kw-only superset)

**Analog:** itself — the 03-02 `decode_audio` addition (protocol.py:112-121) is the exact precedent for "extend the Protocol with a kw-only strict superset; existing implementations remain valid."

**Additions** — per RESEARCH Code Examples:
```python
from dataclasses import dataclass
from typing import Callable
import threading

@dataclass
class ChunkProgress:
    chunks_done: int
    chunks_total: int
    chunk_start_s: float | None = None
    within_chunk_percent: float | None = None

class STTAdapter(Protocol):
    def transcribe(
        self,
        audio: "str | object",
        language: str | None = None,
        vad_filter: bool = True,
        condition_on_previous_text: bool = True,
        *,
        progress_cb: Callable[[ChunkProgress], None] | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> SttTranscription: ...
```
The `*,` makes the new params keyword-only so the existing `FasterWhisperAdapter.transcribe` and the standalone CLI call (`chunker.transcribe_file` calling `adapter.transcribe(audio, language=..., vad_filter=..., condition_on_previous_text=...)` at chunker.py:111-117 and :227) remain valid without changes. This mirrors how 03-02 added `decode_audio` as a strict superset (protocol.py:98-101 NOTE).

**SC-4 boundary check preserved** — no new `faster_whisper`/`ctranslate2` imports; `threading` is stdlib. The grep `grep -rE 'from faster_whisper|import ctranslate2' app/` must still match only `app/models/stt/adapter.py`.

---

### `app/models/stt/chunker.py` (MODIFIED — progress_cb + cancel_flag at chunk boundary)

**Analog:** itself — the chunk loop (chunker.py:147-181) is the exact seam.

**Add kwargs to `transcribe_file`** — extend the signature (chunker.py:80-86) with the same kw-only superset:
```python
def transcribe_file(
    adapter: STTAdapter,
    audio_path: str,
    *,
    language: Optional[str] = None,
    job_id: str = "cli",
    progress_cb: Callable[[ChunkProgress], None] | None = None,
    cancel_flag: threading.Event | None = None,
) -> Transcript:
```
The standalone CLI call (`app/cli/transcribe.py`) does not pass the new kwargs — backward compatible.

**Cooperative cancel check** — at the TOP of the `while start_sample < total_samples` loop (chunker.py:147), before the transcribe call:
```python
if cancel_flag is not None and cancel_flag.is_set():
    raise JobCancelled(job_id)  # new exception, or reuse asyncio.CancelledError
```
D-06 "stop after the current chunk" = check at the chunk boundary, not mid-chunk.

**Progress emit** — at each chunk boundary, after `chunk_count += 1` (chunker.py:151):
```python
if progress_cb is not None:
    progress_cb(ChunkProgress(
        chunks_done=chunk_count,
        chunks_total=total_chunks,  # compute once before the loop
        chunk_start_s=chunk_start,
    ))
```
The fast-path single-call branch (chunker.py:110-131) emits one `ChunkProgress(chunks_done=1, chunks_total=1)` after the call.

**Pitfall 4 guard (VERIFIED)** — chunker.py returns `Transcript` at the end (chunker.py:127, :190) and writes NO file inside the loop. The orchestrator's `atomic_write_json(transcript_path, ...)` fires only after `transcribe_file` returns; a mid-run cancel leaves no `transcript.json` → partial discarded automatically.

---

### `app/jobs/resume.py` / `manifest.py` (MODIFIED — D-04 `ingested` refinement)

**Analog:** itself — `is_stage_complete("ingested", ...)` in resume.py:157-166.

**Generalized `ingested` check per D-04** — refine the branch to "either `manifest.source_path` resolves OR a `source.<ext>` exists in the job dir":
```python
if stage == "ingested":
    # D-04: local-reference ingest sets manifest.source_path (no copy);
    # browser upload (Phase 5) / YouTube (Phase 6) write source.<ext>.
    # Either path satisfies the ingested check.
    if manifest.source_path and Path(manifest.source_path).exists():
        if Path(manifest.source_path).stat().st_size > 0:
            return True
    d = job_dir(settings, job_id)
    if not d.is_dir():
        return False
    for p in d.glob("source.*"):
        if parse_stage_file(p):
            return True
    return False
```
Keep the existing `parse_stage_file` non-empty guard (resume.py:103-109). `source_sha256` stays optional/best-effort per D-04 — do not add it to this check.

---

### `app/main.py` lifespan (MODIFIED — insert sweep + worker + watchdog)

**Analog:** itself — the lifespan (main.py:81-243) already runs `reconcile_all` at lines 200-214.

**Insertion point** — between the existing `reconcile_all` try/except (main.py:202-214) and the `print("...ready...")` (main.py:219), per RESEARCH Pattern 6:
```python
# (existing) reconcile_all ...

# NEW D-03: mark interrupted in-flight jobs failed (after reconcile,
# before worker starts so the worker does not double-process).
from app.jobs.interrupt import mark_interrupted_failed
await mark_interrupted_failed(settings, session_factory)

# NEW D-10/D-11: start worker + watchdog as asyncio tasks.
import asyncio
from app.jobs.orchestrator import worker_loop
from app.jobs.watchdog import watchdog_loop
worker_task = asyncio.create_task(worker_loop(settings, session_factory))
watchdog_task = asyncio.create_task(watchdog_loop(settings, session_factory))

print(f"TranscriptionAndNotes backend ready: data_dir={settings.data_dir}")

try:
    yield
finally:
    worker_task.cancel()
    watchdog_task.cancel()
    # (existing) model unload + engine.dispose ...
```
The teardown ordering (cancel tasks BEFORE `engine.dispose()` at main.py:238) is critical — the worker holds `session_factory` references. Mirror the existing `try/finally` shape (main.py:221-242) with `await asyncio.gather(worker_task, watchdog_task, return_exceptions=True)` after cancel to await quiet shutdown.

**Test guard** — add a `settings.run_worker: bool = True` field (RESEARCH Open Question 2) so tests set it `False` and drive the worker manually; the lifespan wraps the `create_task` calls in `if settings.run_worker:`.

---

### `tests/conftest.py` (MODIFIED — fake STTAdapter + WS support + run_worker)

**Analog:** itself — the `mock_stt_adapter` fixture (conftest.py:428-506) and `tmp_data_dir`/`app_under_test` (conftest.py:34-113) are the pattern to extend.

**Fake STTAdapter fixture** — extend `mock_stt_adapter` (or add a sibling `fake_stt_adapter`) so the mocked `transcribe`:
1. Accepts the new `progress_cb` and `cancel_flag` kwargs (the `_WhisperModel.transcribe` at conftest.py:469 already takes `**_kwargs`).
2. Calls `progress_cb(ChunkProgress(chunks_done=i+1, chunks_total=N))` per fake chunk.
3. Checks `cancel_flag.is_set()` between chunks and raises `JobCancelled`.

**WS test client** — RESEARCH Pattern: use `starlette.testclient.TestClient.websocket_connect` (httpx cannot do WS — Pitfall 6). Add a sync fixture:
```python
@pytest.fixture
def ws_client(app_under_test):
    from starlette.testclient import TestClient
    with TestClient(app_under_test) as client:
        yield client
```
Tests use `with ws_client.websocket_connect("/ws/jobs/J-1/events") as ws: ws.receive_json()`.

**`settings.run_worker = False`** — the `tmp_data_dir` fixture (conftest.py:55-62) writes a `Settings(...)`; extend it to set `run_worker=False` so the lifespan does not auto-start the worker. Tests drive the worker manually via `asyncio.create_task(worker_loop(...))`.

---

## Shared Patterns

### Async session-per-operation
**Source:** `app/jobs/reconcile.py` lines 97-107, `app/jobs/cleanup.py` lines 57-64, 94-101
**Apply to:** `orchestrator.py`, `queue.py`, `interrupt.py`, `watchdog.py` — every DB mutation opens a short-lived `async with session_factory() as session:` and commits before exit. Do not hold a session across stage boundaries (the chunker is sync and off-loop).

```python
async with session_factory() as session:
    result = await session.execute(text("UPDATE jobs SET ... WHERE id = :id"), {...})
    await session.commit()
```

### Write-manifest-first / commit-DB-last
**Source:** `app/jobs/manifest.py::update_stage` lines 218-248
**Apply to:** every orchestrator stage transition. The orchestrator MUST call `update_stage(settings, session, job_id, stage, manifest_patch)` — never a raw `UPDATE jobs`. A crash between the manifest write and the DB commit is healed by `reconcile_all` on next boot.

### Atomic writes (D-04 Phase 1)
**Source:** `app/storage/atomic.py::atomic_write_json` (used in manifest.py:125)
**Apply to:** the orchestrator's `transcript.json` write after `transcribe_file` returns; any event-snapshot file written for WS snapshot-on-connect. Never write a JSON file without this helper.

### Error handling — mark_failed on any stage exception
**Source:** `app/jobs/cleanup.py::mark_failed` lines 88-102
**Apply to:** `orchestrator.py` — wrap each stage in try/except; on any exception (except `JobCancelled`), call `mark_failed(session, job_id, str(exc))` and `bus.publish(job_id, {"type":"failed","error":str(exc)})`. The existing `JobResponse.error` field (job.py:126) carries the message.

### Idempotent SQL migrations
**Source:** `migrations/0001_initial.sql` (CREATE TABLE IF NOT EXISTS), `migrations/0002..0007` (ALTER TABLE ADD COLUMN with duplicate-column guard in db.py:165-174)
**Apply to:** `migrations/0008_idempotency_keys.sql` — use `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`. The runner records the version row automatically.

### Lazy in-body imports + package boundary (SC-4)
**Source:** `app/models/stt/adapter.py` (the ONLY `faster_whisper`/`ctranslate2` import site), `app/jobs/manifest.py` lines 194 (lazy `ManifestPatch` import to avoid circular)
**Apply to:** `orchestrator.py` — import `STTAdapter` (the Protocol) lazily inside the `transcribing` stage function, never `faster_whisper`/`ctranslate2`. Verify: `grep -rE 'from faster_whisper|import ctranslate2' app/` matches only `app/models/stt/adapter.py`.

### Strict-in / lax-out at the API boundary (Phase 1 D-15)
**Source:** `app/models/job.py::CreateJobRequest` (job.py:37 `strict=True, extra="forbid"`), `JobResponse` (job.py:113 strict)
**Apply to:** new WS event payload models if they are ever request bodies (they are NOT — server-emitted). The `Idempotency-Key` header is validated with a charset allowlist `^[A-Za-z0-9_-]{1,128}$` before DB lookup (V5, Security Domain).

### Test isolation — tmp_data_dir + mocked seams
**Source:** `tests/conftest.py` lines 34-113 (`tmp_data_dir`, `app_under_test`, `client`), lines 428-506 (`mock_stt_adapter`)
**Apply to:** all Phase 4 test files (`test_orchestrator.py`, `test_event_bus.py`, `test_ws.py`, `test_idempotency.py`, `test_cancel.py`). Reuse `tmp_data_dir` + `app_under_test` unchanged; add `run_worker=False` to the settings file written at conftest.py:57-62; extend `mock_stt_adapter` to honor `progress_cb` + `cancel_flag`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `app/jobs/progress.py` (EventBus) | service / provider | pub-sub | No existing asyncio pub/sub in the codebase; the SSE `_in_flight` dict is closest but poll-based. Use RESEARCH Pattern 1 verbatim. |
| `app/api/routes_ws.py` (WebSocket handler) | route | streaming | No existing WS endpoint in the codebase (SSE is the closest). Use RESEARCH Pattern 2 + Starlette TestClient WS (RESEARCH Code Examples). |
| `orchestrator.py` worker loop (hybrid Event + 2s poll) | service | event-driven | No existing long-running asyncio worker task in the codebase. Use RESEARCH Pattern 4 verbatim. |
| Cooperative cancel `threading.Event` marshalling | service | event-driven | No existing cross-thread cancel in app code (only in test fixture `slow_mock_hf_hub_download`). Use RESEARCH Pattern 5 + `loop.call_soon_threadsafe`. |

## Metadata

**Analog search scope:** `app/` (all .py), `migrations/` (all .sql), `tests/conftest.py`. Key files read: `app/jobs/{service,manifest,cleanup,reconcile,resume}.py`, `app/api/{routes_jobs,routes_models,dependencies}.py`, `app/main.py`, `app/models/{job,manifest,stt/protocol,stt/chunker,stt/adapter}.py`, `app/storage/{db,fs}.py`, `migrations/0001..0007_*.sql`, `tests/conftest.py`.
**Files scanned:** 18
**Pattern extraction date:** 2026-06-22

## PATTERN MAPPING COMPLETE