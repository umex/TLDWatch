# Phase 04: Job Orchestrator + Persistent Queue + WebSocket Progress - Research

**Researched:** 2026-06-22
**Domain:** async job orchestration, SQLite-backed persistent queue, WebSocket progress pub/sub
**Confidence:** HIGH (grounded in local codebase + locked CONTEXT decisions)

## Summary

Phase 4 builds the spine of the system: a serial worker draining a SQLite-queued job list, a file-as-truth state machine (`queued → ingesting → transcribing → done`) whose transitions are guarded by stage-output files on disk, an in-process asyncio event bus feeding a per-job WebSocket, and idempotent job submission via an `Idempotency-Key` header. Every later feature reduces to "add a stage."

The codebase already provides the primitives: `app/jobs/cleanup.py` (cancel_job, mark_failed, mark_stale, is_stale, `_TERMINAL_STATUSES`), `app/jobs/reconcile.py` (reconcile_all), `app/jobs/manifest.py` (update_stage), `app/storage/db.py` (apply_migrations), and `app/models/stt/protocol.py` (STTAdapter). Phase 4 wires these into a single asyncio worker loop + lifespan-managed watchdog, adds a progress callback to `STTAdapter.transcribe`, and adds one migration (`0008_idempotency_keys.sql`).

**Primary recommendation:** one asyncio worker task (poll-on-short-sleep + `asyncio.Event` signal on enqueue), one asyncio event bus (`dict[job_id → list[asyncio.Queue]]` with `maxsize=32` drop-oldest backpressure), one Starlette WebSocket endpoint that snapshots-on-connect then drains the bus, and one `idempotency_keys` table with `UNIQUE` PK + `IntegrityError`-catch race handling. Test WebSocket via `starlette.testclient.TestClient.websocket_connect` (httpx cannot do WS).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Job state machine (queued→ingesting→transcribing→done) | API / Backend (orchestrator) | Database (status column) + FS (stage-output files) | Transitions guarded by on-disk stage outputs = file-as-truth; DB mirrors status |
| Persistent queue + restart resume | Database (SQLite) | API boot lifecycle | SQLite `jobs` table is the queue; boot reconcile heals drift |
| Worker dispatch (FIFO serial, worker=1) | API / Backend (asyncio task) | — | HW-09 + Phase 2 D-04 409 forbids concurrency; single loop owns model access |
| WebSocket progress broadcast | API / Backend (Starlette WS) | In-process asyncio event bus | No external broker; per-job pub/sub |
| Idempotent submit (Idempotency-Key) | API / Backend (route handler) | Database (idempotency_keys table) | HTTP header → table → 200 existing on dup |
| Cancel (queued instant / running cooperative / terminal no-op) | API / Backend | Database (cancel_job) + FS (rmtree) | D-06 locked: DB-first + rmtree; cooperative flag checked between chunks |
| Boot interrupted sweep | API lifespan | Database (mark_failed) | D-03: after reconcile_all, before worker start |
| Stale-sweep watchdog | API lifespan (asyncio task) | Database (is_stale/mark_stale) | D-11: 60s cadence, 10-min threshold |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** local + youtube ingest separate; Phase 4 = ONLY `source_type=local`; youtube = dispatch stub (Phase 6).
- **D-02:** NO mid-transcription resume; reuse `infer_resume_point`; crashed transcribe re-transcribes from scratch.
- **D-03:** NO auto-resume on restart; boot step AFTER `reconcile_all` marks active-stage jobs `failed` w/ `error="interrupted (backend restarted)"` + preserves source name; runs before worker starts.
- **D-04:** local file referenced IN PLACE (no copy); `manifest.source_path`; generalized `ingested` check = "manifest.source_path resolves OR `source.<ext>` exists in job dir"; `source_sha256` optional/best-effort.
- **D-06:** queued cancel = instant (`cancel_job` DB-first + `rmtree`); running cancel = cooperative (cancel flag checked between chunks, stop after current chunk, discard partial, mark `cancelled`); idempotent on terminal = no-op returning current row.
- **D-07 [Discretion]:** `Idempotency-Key` HTTP header → `idempotency_keys` table (`key TEXT PK, job_id TEXT NOT NULL, created_at TEXT NOT NULL`) → 200 existing `JobResponse` on dup; missing key = new job; TTL ~24h.
- **D-08 [Discretion]:** per-job WS `GET /ws/jobs/{id}/events`; snapshot-on-connect (current stage/percent/ETA/status) then live events; in-process asyncio event bus (no external broker); events: `stage_changed`, `progress`, `done`, `failed`, `cancelled`; client-driven reconnect (no server resume buffer).
- **D-09 [Discretion]:** per-stage binary progress for `ingesting` (0→100%); per-chunk percent for `transcribing` (chunks done/total + faster-whisper segment progress within a chunk when cheap); ETA = elapsed/percent with min-sample threshold before emitting.
- **D-10:** worker=1 strict FIFO serial (HW-09 + Phase 2 D-04 409 ConcurrentModelRefused); fully serial one-job-at-a-time.
- **D-11 [Discretion]:** stale-sweep watchdog reusing `is_stale`/`mark_stale`, 10-min D-13 threshold, status-aware (skip done/failed/cancelled).
- **D-12:** cross-AI review (codex + gemini) pressure-tests D-07..D-11 after planning (informational).

### Claude's Discretion
D-07, D-08, D-09, D-11 implementation details (event bus shape, WS testing, TTL enforcement, ETA cadence, watchdog cadence).

### Deferred Ideas (OUT OF SCOPE)
- youtube ingest (Phase 6) — only a dispatch stub here.
- mid-transcription resume (D-02 explicitly forbids).
- auto-resume on restart (D-03 explicitly forbids — mark interrupted as failed).
- external message broker (D-08 forbids — in-process only).
- server-side WS resume buffer (D-08 forbids — client reconnects).
- multiple workers / parallel jobs (D-10 forbids — worker=1).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| JOB-02 | Background jobs / state machine (SC-1) | `run_job` state machine: queued→ingesting→transcribing→done via `update_stage` (D-01, D-04) |
| JOB-04 | Job queue state persists across restarts (SC-2) | SQLite `jobs` table + boot reconcile + interrupted sweep marks active failed (D-03); queued re-join FIFO |
| JOB-05 | Cancel queued/running job, idempotent (SC-4) | `cancel_job` DB-first + cooperative `threading.Event` flag; terminal no-op (D-06) |
| JOB-06 | Per-job progress via WebSocket (SC-3) | asyncio event bus + `GET /ws/jobs/{id}/events` snapshot-then-live (D-08) |

> Note: SC-5 (idempotent submit — `POST /jobs` with same `Idempotency-Key` → existing job ID) is a roadmap success criterion with **no dedicated JOB-XX label**; delivered by 04-03 via `Idempotency-Key` header → `idempotency_keys` table (D-07).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | (existing) | HTTP + WebSocket routes | Already in project; Starlette WS support built-in |
| starlette | (transitive) | `TestClient.websocket_connect` for WS tests | Only viable WS test path (httpx cannot do WS) |
| sqlite3 | (stdlib) | persistent queue | Already used via `app/storage/db.py` |
| asyncio | (stdlib) | worker loop + event bus + watchdog | Already used |
| aiosqlite | (existing if present) | async DB access | TODO confirm via db.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | (existing) | JobResponse / WS event schemas | Already in project |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| in-process asyncio event bus | Redis pub/sub | D-08 forbids external broker; keep in-process |
| starlette TestClient WS | `websockets` lib | TestClient reuses app + auth/lifespan; prefer it |

**Installation:** No new packages — all stdlib + existing project deps. DB access is **async via aiosqlite + SQLAlchemy `AsyncSession`** (`app/storage/db.py` uses `sqlite+aiosqlite:///`), so the worker awaits DB calls directly — no `run_in_executor` for DB. [VERIFIED: app/storage/db.py]

## Package Legitimacy Audit

No new external packages installed in this phase. All work uses stdlib (`asyncio`, `sqlite3`) and existing project deps (`fastapi`, `starlette`, `pydantic`).

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
POST /jobs (Idempotency-Key?)
   │
   ▼
routes_jobs.create_job
   │  ├─ key present? → lookup idempotency_keys → 200 existing on hit
   │  └─ else INSERT jobs(status='queued') + idempotency_keys row
   │
   ▼
SQLite jobs table (queue: status='queued', ORDER BY created_at)
   │  ▲ enqueue signals asyncio.Event
   │  │
WORKER LOOP (worker=1, FIFO serial)
   │  pull next queued job
   │  ▼
   ├─ stage: ingesting   → manifest update_stage('ingesting') → verify ingested (D-04)
   ├─ stage: transcribing → STTAdapter.transcribe(progress_cb=..., cancel_flag=...)
   │       │  progress_cb fires per chunk → bus.publish(job_id, 'progress', ...)
   │       │  cancel_flag checked between chunks → raise CancelledError
   │       └─ at end → atomic_write_json(transcript) → manifest update_stage('done')
   │
   ▼
asyncio EVENT BUS (dict[job_id → list[asyncio.Queue maxsize=32]])
   │  publish: stage_changed / progress / done / failed / cancelled
   │
   ▼
GET /ws/jobs/{id}/events
   │  on connect: snapshot (read manifest/DB stage/percent/ETA/status)
   │  then: drain subscriber Queue → send_json(event)
   │  on disconnect: remove Queue from registry
   │
POST /jobs/{id}/cancel
   │  queued → cancel_job + rmtree → bus.publish('cancelled') (instant)
   │  running → set cancel_flag → worker stops after chunk → cancel_job → bus.publish('cancelled')
   │  terminal → no-op, return current row
   │
LIFESPAN (app/main.py)
   1. reconcile_all()                       # heal DB/FS drift
   2. interrupted sweep → mark active failed # D-03
   3. start worker task                     # asyncio.create_task
   4. start stale-sweep watchdog (60s)      # D-11
   on shutdown: cancel worker + watchdog tasks
```

### Recommended Project Structure
```
app/
├── jobs/
│   ├── orchestrator.py    # NEW: worker loop, run_job, stage transitions
│   ├── event_bus.py       # NEW: in-process pub/sub
│   ├── watchdog.py        # NEW: stale-sweep task (D-11)
│   ├── interrupted.py     # NEW: boot interrupted sweep (D-03)
│   ├── cleanup.py         # EXISTING: cancel_job, mark_failed, mark_stale, is_stale
│   ├── reconcile.py       # EXISTING: reconcile_all
│   └── manifest.py        # EXISTING: update_stage
├── api/
│   ├── routes_jobs.py     # EDIT: idempotency + cancel wiring
│   └── routes_ws.py       # NEW: GET /ws/jobs/{id}/events
├── models/stt/
│   ├── protocol.py        # EDIT: add progress_cb + cancel_flag to transcribe
│   └── chunker.py         # EDIT: invoke progress_cb per chunk
├── storage/
│   └── db.py              # EXISTING: apply_migrations
└── main.py                # EDIT: lifespan ordering (reconcile → sweep → worker → watchdog)
migrations/
└── 0008_idempotency_keys.sql  # NEW
tests/
├── conftest.py            # fixtures: fake STTAdapter, tmp_data_dir, TestClient
├── test_orchestrator.py   # NEW
├── test_event_bus.py      # NEW
├── test_ws.py             # NEW (starlette TestClient websocket_connect)
├── test_idempotency.py    # NEW
└── test_cancel.py         # NEW
```

### Pattern 1: In-process asyncio Event Bus (D-08) — RECOMMENDED
**What:** `dict[job_id → list[asyncio.Queue]]` registry. Each WS connect creates a `asyncio.Queue(maxsize=32)` and appends to `bus[job_id]`. `publish(job_id, event)` iterates subscribers and does `queue.put_nowait(event)`; on `QueueFull` drop oldest (pop front then put) to bound memory.
**When to use:** single-process, no external broker. Matches D-08.
**Example:**
```python
class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                del self._subs[job_id]

    def publish(self, job_id: str, event: dict) -> None:
        for q in self._subs.get(job_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()  # drop oldest
                    q.put_nowait(event)
                except Exception:
                    pass  # lost race; skip
```

### Pattern 2: WebSocket Endpoint (D-08)
**What:** `GET /ws/jobs/{id}/events` Starlette WS. On accept: build snapshot from manifest/DB (current stage, percent, ETA, status), `send_json(snapshot)`, then loop `await queue.get()` → `send_json(event)`. On `WebSocketDisconnect`: unsubscribe + cleanup.
**When to use:** all WS progress.
**Example:**
```python
from starlette.websockets import WebSocket, WebSocketDisconnect

@app.websocket("/ws/jobs/{job_id}/events")
async def job_events(ws: WebSocket, job_id: str):
    await ws.accept()
    q = bus.subscribe(job_id)
    try:
        await ws.send_json(build_snapshot(job_id))  # reads manifest/DB
        while True:
            event = await q.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(job_id, q)
```

### Pattern 3: Idempotency-Key Flow (D-07) — RECOMMENDED
```python
# POST /jobs
key = request.headers.get("Idempotency-Key")
if key:
    row = db.execute("SELECT job_id FROM idempotency_keys WHERE key=? AND created_at > ?", (key, cutoff)).fetchone()
    if row:
        existing = load_job(row["job_id"])
        return JSONResponse(existing, status_code=200)
# create job
job_id = new_id()
db.execute("INSERT INTO jobs(...) VALUES(...)", ...)  # status='queued'
if key:
    try:
        db.execute("INSERT INTO idempotency_keys(key, job_id, created_at) VALUES(?,?,?)", (key, job_id, now_iso))
        db.commit()
    except sqlite3.IntegrityError:  # race: concurrent dup key
        row = db.execute("SELECT job_id FROM idempotency_keys WHERE key=?", (key,)).fetchone()
        return JSONResponse(load_job(row["job_id"]), status_code=200)
bus_signal.set()  # wake worker
return JSONResponse(job, status_code=201)
```
TTL: janitor task (or inline on lookup) deletes rows with `created_at < now - 24h`. `cutoff = (now - 24h).isoformat()`.

### Pattern 4: Worker=1 FIFO Loop (D-10) — RECOMMENDED
**What:** single asyncio task. `while True: row = next_queued(); if row: await run_job(row); else: await asyncio.wait_for(signal.wait(), timeout=2.0)` — hybrid: Event signals on enqueue for responsiveness, 2s poll fallback guards against missed signals across restarts.
**Why hybrid:** pure Event can be missed if set before worker waits; poll fallback covers it. 2s is cheap.

### Pattern 5: Cooperative Cancel (D-06)
**What:** `cancel_flag = threading.Event()` stored in `orchestrator._running[job_id]` (threading, NOT asyncio — because `transcribe_file`/chunker is SYNC and runs in a worker thread via `loop.run_in_executor`; `threading.Event.is_set()` is callable from that thread). [VERIFIED: chunker.py is sync; protocol.py `transcribe` is sync] Chunker checks `cancel_flag.is_set()` between chunks → raise `JobCancelled`. Orchestrator catches it → `cancel_job(job_id)` (DB-first + rmtree, already implemented in `app/jobs/cleanup.py`) → `bus.publish(job_id, 'cancelled')`. `atomic_write_json` only fires at the end of `transcribe_file` (chunker assembles the full `Transcript` in memory then the caller writes), so a mid-run cancel leaves NO transcript file → partial discarded automatically. [VERIFIED: chunker.py returns Transcript at end; no incremental file writes inside the chunk loop]

### Pattern 6: Boot Interrupted Sweep (D-03)
**Where:** `app/main.py` `lifespan`. Today the lifespan runs `apply_migrations` → `configure` → `configure_manager` → `reconcile_all` → `print("ready")` → `yield`. Phase 4 inserts the interrupted sweep + worker + watchdog tasks BETWEEN `reconcile_all` and `yield`. [VERIFIED: app/main.py lifespan order]

```python
# lifespan (after reconcile_all)
await reconcile_all(settings, session_factory)          # 1. heal DB/FS drift (EXISTING)
await mark_interrupted_failed(session_factory)          # 2. NEW D-03: active → failed
worker_task = asyncio.create_task(worker_loop(...))     # 3. NEW D-10
watchdog_task = asyncio.create_task(watchdog_loop(...)) # 4. NEW D-11
print("...ready...")
try:
    yield
finally:
    worker_task.cancel(); watchdog_task.cancel()
    # existing model unload + engine.dispose
```
`mark_interrupted_failed`: `UPDATE jobs SET status='failed', error='interrupted (backend restarted)', updated_at=:now WHERE status IN ('ingesting','transcribing')` — run in its own short-lived `async with session_factory() as session`. "Active-stage" = jobs whose status is `ingesting` or `transcribing` (the two non-terminal active statuses from `_STAGE_STATUSES` minus `queued`; `queued` jobs are NOT interrupted — they re-join the queue). [VERIFIED: `_TERMINAL_STATUSES={'done','failed','cancelled'}` in cleanup.py; `stage_to_status` maps ingested→ingesting, transcribed→transcribing in manifest.py]

### Anti-Patterns to Avoid
- **Server WS resume buffer:** D-08 forbids; client drives reconnect; snapshot-on-connect is enough.
- **Mid-transcription resume:** D-02 forbids; re-transcribe from scratch.
- **Multiple workers:** D-10 forbids (HW-09 409 ConcurrentModelRefused).
- **Auto-resume on restart:** D-03 forbids — mark interrupted as failed, do NOT resume.
- **Copying local source file:** D-04 forbids — reference in place via `manifest.source_path`.
- **Hand-rolling atomic transitions:** use `manifest.update_stage` + stage-output file guards (file-as-truth).
- **httpx for WS tests:** httpx cannot do WebSockets — use `starlette.testclient.TestClient.websocket_connect`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic stage transitions | Custom status mutation | `manifest.update_stage` + stage-output file check | File-as-truth already implemented |
| Cancel / mark_failed / mark_stale | New status helpers | `app/jobs/cleanup.py` cancel_job/mark_failed/mark_stale | D-06 reuses these |
| DB/FS drift healing | New reconcile | `reconcile_all` | Already exists |
| Migrations | Custom DDL runner | `app/storage/db.py` apply_migrations + one `0008_*.sql` | Existing pattern |
| Resume point inference | New logic | `infer_resume_point` | D-02 reuses it |
| WS test client | `websockets` lib wiring | `starlette.testclient.TestClient.websocket_connect` | Shares app + lifespan + auth |

**Key insight:** Phase 4 is mostly wiring existing primitives into a loop + bus; the only new surface is the event bus, WS route, watchdog, interrupted sweep, idempotency migration, and a progress callback on `STTAdapter.transcribe`.

## Common Pitfalls

### Pitfall 1: Missed asyncio.Event signal
**What goes wrong:** worker stuck after enqueue.
**Why:** `Event.set()` before worker `await`s is a no-op if already set then cleared.
**How to avoid:** hybrid Event + 2s poll fallback (Pattern 4).
**Warning signs:** queued job sits >2s without ingesting.

### Pitfall 2: Slow WS subscriber blocks worker
**What goes wrong:** `bus.publish` blocks → worker stalls.
**Why:** naive `await queue.put(event)` on full queue.
**How to avoid:** `put_nowait` + drop-oldest on `QueueFull` (Pattern 1); never await in publish.
**Warning signs:** worker progress pauses when a client is connected.

### Pitfall 3: Idempotency race creates duplicate job
**What goes wrong:** two concurrent POSTs same key → two jobs.
**Why:** lookup-then-insert not atomic.
**How to avoid:** `UNIQUE(key)` PK + catch `IntegrityError` → re-read existing (Pattern 3).
**Warning signs:** two job_ids for one key.

### Pitfall 4: Partial transcript committed on cancel
**What goes wrong:** cancelled job shows partial transcript file.
**Why:** transcript written incrementally.
**How to avoid:** `atomic_write_json` only at end (confirm in chunker.py); cancel discards partial via rmtree. Ensure chunker does NOT write transcript file mid-run.
**Warning signs:** transcript.json present on cancelled job.

### Pitfall 5: Worker starts before interrupted sweep
**What goes wrong:** worker picks up an `ingesting` job from a previous crashed run and double-processes.
**Why:** lifespan ordering wrong.
**How to avoid:** strict order: reconcile_all → interrupted sweep → worker + watchdog (Pattern 6).
**Warning signs:** duplicate in-flight jobs after restart.

### Pitfall 6: httpx WebSocket test hangs
**What goes wrong:** test deadlocks.
**Why:** httpx cannot do WS.
**How to avoid:** `starlette.testclient.TestClient.websocket_connect`.
**Warning signs:** test timeout with no output.

### Pitfall 7: Stale-sweep marks terminal jobs
**What goes wrong:** done/failed/cancelled jobs marked stale.
**Why:** watchdog not status-aware.
**How to avoid:** D-11: skip `status IN ('done','failed','cancelled')`; only check active.
**Warning signs:** done jobs reappearing as failed.

## Code Examples

### Progress callback signature (to add to STTAdapter.transcribe + chunker)
```python
# Source: app/models/stt/protocol.py (to be edited — currently sync, no callbacks)
# VERIFIED current signature:
#   def transcribe(self, audio: "str | object", language: str | None = None,
#                  vad_filter: bool = True, condition_on_previous_text: bool = True) -> SttTranscription
# RECOMMENDED addition (kw-only, strict superset like 03-02's decode_audio):
@dataclass
class ChunkProgress:
    chunks_done: int
    chunks_total: int
    chunk_start_s: float | None = None   # absolute start of current chunk
    within_chunk_percent: float | None = None  # faster-whisper segment progress if cheap

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
**Threading model (VERIFIED):** `transcribe_file` (chunker.py) is SYNC and loops chunks in a plain `while`. The orchestrator runs it via `await loop.run_in_executor(None, transcribe_file, adapter, path, ...)`. Therefore:
- `cancel_flag` MUST be `threading.Event` (`.is_set()` callable from the worker thread). NOT `asyncio.Event`.
- `progress_cb` is invoked from the worker thread; the orchestrator passes a wrapper that marshals back to the asyncio loop: `lambda p: loop.call_soon_threadsafe(bus.publish, job_id, {"type":"progress", **p.__dict__})`.
- Chunker calls `progress_cb(ChunkProgress(chunks_done=i+1, chunks_total=total, chunk_start_s=chunk_start))` at each chunk boundary, and checks `if cancel_flag and cancel_flag.is_set(): raise JobCancelled(...)` at the TOP of the while loop (between chunks — D-06 "stop after current chunk"). Within-chunk segment progress is only emitted if faster-whisper exposes it cheaply (else None).
- ETA: orchestrator computes `eta = elapsed_s / percent * (1 - percent)`; emit only after `chunks_done >= 2` (D-09 min-sample threshold) and throttle within-chunk emits to ≤1/s.

### WS test via Starlette TestClient
```python
# Source: starlette docs (TestClient.websocket_connect)
from starlette.testclient import TestClient

def test_ws_snapshot_then_events(app, fake_stt):
    with TestClient(app) as client:
        with client.websocket_connect("/ws/jobs/J-1/events") as ws:
            snapshot = ws.receive_json()
            assert snapshot["status"] in ("queued","ingesting","transcribing","done")
            # ... drive worker, assert receive_json events
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| httpx WebSocket | starlette TestClient WS | httpx never supported WS | Use TestClient for WS tests |
| External broker (Redis) | in-process asyncio bus | D-08 decision | No Redis dep; single-process only |

**Deprecated/outdated:**
- Any `websockets`-lib-based server WS in FastAPI — prefer native Starlette `@app.websocket`.

## Assumptions Log

| # | Claim | Section | Status |
|---|-------|---------|--------|
| A1 | `cleanup.py` exposes `cancel_job`, `mark_failed`, `mark_stale`, `is_stale`, `_TERMINAL_STATUSES` | Patterns | **VERIFIED** — all present, async, DB-first cancel_job [VERIFIED: app/jobs/cleanup.py] |
| A2 | `manifest.update_stage(session, settings, job_id, stage, ...)` is the transition call | Patterns | **VERIFIED** — async, writes manifest-first/DB-last, uses `stage_to_status` [VERIFIED: app/jobs/manifest.py] |
| A3 | chunker + `transcribe` are SYNC → cancel_flag must be `threading.Event` | Code Examples | **VERIFIED** — both sync [VERIFIED: chunker.py, protocol.py] |
| A4 | `apply_migrations` runs `.sql` files in `migrations/` ordered by filename; next = `0008` | Patterns | **VERIFIED** — migrations/0001..0007 exist [VERIFIED: migrations/ dir listing] |
| A5 | `atomic_write_json` only at end; chunker assembles Transcript in memory | Pitfall 4 | **VERIFIED** — chunker.py returns Transcript at end, no file writes in chunk loop [VERIFIED: chunker.py] |
| A6 | DB is async via aiosqlite/SQLAlchemy AsyncSession | Standard Stack | **VERIFIED** — `sqlite+aiosqlite:///` in db.py [VERIFIED: app/storage/db.py] |
| A7 | `mark_stale` is already status-aware (skips terminal) | Patterns | **VERIFIED** — D-11 watchdog reuses it directly [VERIFIED: cleanup.py] |
| A8 | `is_stale` default threshold = 600s (matches D-13 10-min) | Patterns | **VERIFIED** [VERIFIED: cleanup.py] |
| A9 | `create_job` already exists in `app/jobs/service.py` (idempotency wraps it) | Patterns | **VERIFIED** — routes_jobs.py imports it [VERIFIED: app/api/routes_jobs.py] |
| A10 | Starlette TestClient supports `websocket_connect` | Validation | [ASSUMED] — from training; planner should confirm in Wave 0 |

**Remaining [ASSUMED]:** A10 only. All other claims verified against local codebase this session.

## Open Questions (RESOLVED)

1. **Does `update_stage` take metadata kwargs (language/duration_s) or just stage?** Confirmed it writes full projected metadata in one UPDATE — orchestrator should pass metadata known after ingest (language, duration_s). Planner should check the exact kwarg names in `manifest.py` beyond line 80. **RESOLVED:** 04-01 Task 2 calls `update_stage(settings, session, job_id, "ingested", ManifestPatch(source_path=...))` — the manifest-first/DB-last full-projection path is used.
2. **Starlette TestClient `websocket_connect` behavior with the async lifespan** — does `with TestClient(app) as client` run the lifespan (starting the real worker)? If yes, tests must use a fixture that swaps in a fake STTAdapter + a worker that does NOT auto-start, OR use `TestClient(app, raise_server_exceptions=True)` with a flag to disable the worker in tests. **Recommendation:** add a `settings.run_worker` flag (default True) that tests set False, then tests drive the worker manually. Planner must define this fixture in Wave 0. **RESOLVED:** 04-01 Task 1 adds `Settings.run_worker: bool = True`; 04-02 Task 2 consumes it (does NOT re-add); tests set it False and drive the worker manually.
3. **Idempotency-Key charset/length** — recommend `^[A-Za-z0-9_-]{1,128}$` allowlist (reject before DB — V5 input validation). **RESOLVED:** 04-03 Task 3 implements `validate_idempotency_key` with regex `^[A-Za-z0-9_-]{1,128}$`, rejected before DB write.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | runtime | ✓ | (existing) | — |
| SQLite | persistent queue | ✓ (stdlib) | — | — |
| fastapi / starlette | HTTP + WS | ✓ (existing) | — | — |
| starlette TestClient | WS tests | ✓ (transitive) | — | `websockets` lib (fallback) |
| real GPU / faster-whisper model | actual transcription | ✗ for tests | — | Fake STTAdapter (yields chunks + calls progress_cb) |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** real GPU → fake STTAdapter for all tests (no model load)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (existing — confirm) |
| Config file | pyproject.toml / pytest.ini (confirm) |
| Quick run command | `pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py tests/test_cancel.py -x` |
| Full suite command | `pytest -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JOB-02 / SC-1 | queued→ingesting→transcribing→done transitions guarded by stage-output files | unit | `pytest tests/test_orchestrator.py::test_state_machine -x` | ❌ Wave 0 |
| JOB-02 / SC-2 | queue persists across restart; re-joinable; resume inferred from files | integration | `pytest tests/test_orchestrator.py::test_restart_rejoin -x` | ❌ Wave 0 |
| JOB-04 / SC-3 | WS broadcasts stage/percent/ETA | integration | `pytest tests/test_ws.py::test_progress_events -x` | ❌ Wave 0 |
| JOB-05 / SC-4 | cancel queued (instant) / running (cooperative) / terminal (no-op) | unit | `pytest tests/test_cancel.py::test_cancel_queued tests/test_cancel.py::test_cancel_running tests/test_cancel.py::test_cancel_terminal -x` | ❌ Wave 0 |
| JOB-06 / SC-5 | POST /jobs same Idempotency-Key → same job_id + 200 | unit | `pytest tests/test_idempotency.py::test_dup_key_returns_existing -x` | ❌ Wave 0 |
| D-03 | boot sweep marks active failed | integration | `pytest tests/test_orchestrator.py::test_boot_interrupted_sweep -x` | ❌ Wave 0 |
| D-11 | stale-sweep watchdog marks stale after 10min | unit | `pytest tests/test_orchestrator.py::test_watchdog_stale -x` | ❌ Wave 0 |
| D-10 | worker=1 serial (no concurrency) | unit | `pytest tests/test_orchestrator.py::test_serial_no_concurrency -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py tests/test_cancel.py -x`
- **Per wave merge:** `pytest -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_orchestrator.py` — covers JOB-02/SC-1/SC-2, D-03, D-10, D-11
- [ ] `tests/test_event_bus.py` — covers pub/sub, backpressure drop-oldest
- [ ] `tests/test_ws.py` — covers SC-3 (snapshot + live events via TestClient)
- [ ] `tests/test_idempotency.py` — covers JOB-06/SC-5 + race
- [ ] `tests/test_cancel.py` — covers JOB-05/SC-4 (queued/running/terminal)
- [ ] `tests/conftest.py` — fake STTAdapter fixture (yields chunks + calls progress_cb + honors cancel_flag), tmp_data_dir SQLite queue, TestClient with lifespan
- [ ] Confirm pytest-asyncio installed — if missing, add to dev deps

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (existing) | reuses existing route auth — not new in Phase 4 |
| V3 Session Management | no | WS reuses existing session/auth |
| V4 Access Control | yes | existing route ACL on POST /jobs + cancel + WS |
| V5 Input Validation | yes | pydantic JobResponse + WS event schemas; Idempotency-Key header validation (max length, charset) |
| V6 Cryptography | no | no new crypto |

### Known Threat Patterns for asyncio + WS + SQLite

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Idempotency-Key injection (oversized/malicious header) | Tampering | cap key length (e.g., 256), charset allowlist; reject before DB |
| WS unbounded subscriber growth (DoS) | Denial of Service | cap subscribers per job_id (e.g., 16); reject extra with 403 |
| Event bus memory blowup | Denial of Service | Queue maxsize=32 + drop-oldest (Pattern 1) |
| Concurrent duplicate job (race) | Tampering | UNIQUE(key) + IntegrityError catch (Pattern 3) |
| Cancel race (cancel + terminal commit) | Tampering | DB-first cancel_job; terminal check before mark |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/04-.../04-CONTEXT.md` — D-01..D-12 locked decisions
- `.planning/REQUIREMENTS.md` — JOB-02/04/05/06
- `app/jobs/cleanup.py` — cancel_job (DB-first + rmtree), mark_failed, mark_stale (status-aware), is_stale (600s default), `_TERMINAL_STATUSES={'done','failed','cancelled'}`
- `app/jobs/reconcile.py` — reconcile_all (heals DB from manifest; manifest is source of truth)
- `app/jobs/manifest.py` — update_stage (manifest-first/DB-last), stage_to_status (file-as-truth mapping: ingested→ingesting, transcribed→transcribing, done→done)
- `app/models/stt/protocol.py` — STTAdapter.transcribe is SYNC; no progress_cb/cancel_flag yet (to add as kw-only superset)
- `app/models/stt/chunker.py` — transcribe_file is SYNC, loops chunks in while, OOM split-both-halves retry, returns Transcript at end (no incremental file writes)
- `app/main.py` — lifespan order (migrations → configure → configure_manager → reconcile_all → yield); Phase 4 inserts sweep+worker+watchdog before yield
- `app/storage/db.py` — async aiosqlite engine, `apply_migrations` runs `migrations/*.sql` in filename order
- `migrations/` — 0001..0007 exist; next = `0008_idempotency_keys.sql`
- `app/api/routes_jobs.py` — POST /jobs (create_job), POST /jobs/{id}/cancel (cancel_job already wired)

### Secondary (MEDIUM confidence)
- Starlette TestClient `websocket_connect` API — `[ASSUMED]` from training; planner confirms in Wave 0

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing deps, no new packages
- Architecture: HIGH — patterns grounded in locked D-01..D-12 + existing codebase primitives
- Pitfalls: HIGH — derived from known asyncio/WS/SQLite failure modes + D-constraints

**Research date:** 2026-06-22
**Valid until:** 2026-07-22 (stable; codebase-local)