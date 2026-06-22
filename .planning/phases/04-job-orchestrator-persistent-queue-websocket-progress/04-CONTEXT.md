# Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning
**Source:** /gsd-discuss-phase 04 (interactive, default mode). The user gave strong product-level guidance up front ("do it as simple as possible", "I don't need to start in the middle of transcribing", "space management is important", "reference in place, no duplicates") which resolved the four product-shaped gray areas directly. The remaining technical areas (WebSocket pub/sub, progress/ETA granularity, worker=1 serial dispatch, stale-sweep, idempotency-key mechanism) are Claude's Discretion + cross-AI review per the standing D-09 preference.

<domain>
## Phase Boundary

The job state machine, persistent queue, and real-time progress broadcast — the spine every later feature plugs into as "just add a stage." Phase 4 takes the file-as-truth machinery Phase 1 shipped and *drives* it: an in-process orchestrator runs jobs through `queued → ingesting → transcribing → done`, a SQLite-backed queue persists across restarts, a WebSocket broadcasts per-job progress, and submit/cancel are idempotent. Phase 3's `STTAdapter` becomes the `transcribing` stage (the CLI was the standalone proof; Phase 4 is the queue driving the same adapter).

In scope (ROADMAP success criteria SC-1..SC-5, requirements JOB-02, JOB-04, JOB-05, JOB-06):
- An in-process job runner that moves a job `queued → ingesting → transcribing → done` with atomic stage transitions guarded by the existing file-as-truth stage-output files (SC-1). The orchestrator calls `STTAdapter` (never `faster_whisper`/`ctranslate2`) for the `transcribing` stage.
- A SQLite-backed queue that persists across back-end restarts; queued and in-flight jobs are re-joinable (SC-2). **No auto-resume** — interrupted jobs are surfaced as failed with the source name preserved so the user can find and re-submit them (D-03).
- A WebSocket endpoint that broadcasts per-job progress events (current stage, percent, ETA) the front-end can subscribe to (SC-3, JOB-06).
- Cancel of a queued or running job; idempotent; partial files cleaned up deterministically (SC-4, JOB-05).
- Idempotent submit — a `POST /jobs` with the same idempotency key returns the existing job ID instead of creating a duplicate (SC-5).
- The `ingesting` stage for **local files only**: the job references a local file **in place** (no copy) and the orchestrator validates + records it (D-01, D-04).

Out of scope for Phase 4:
- Browser drag-and-drop upload UI / streaming upload endpoint (Phase 5 — that path *copies/streams* the file into `data/jobs/<id>/source.<ext>`).
- YouTube ingest / yt-dlp / playlist fan-out / pause-resume / timestamp link-out (Phase 6 — the `source_type=youtube` branch of the ingest stage is a seam here, NOT implemented).
- Diarization stage (Phase 7), summarization stage (Phase 8), transcript editor / export (Phase 9), settings panel / quality preset UI (Phase 10).
- A "restart from beginning" button in the UI (D-03 — the user re-submits manually for MVP).
- Mid-transcription (mid-chunk) resume / checkpointing (D-02 — explicitly rejected for MVP).
- Keeping downloaded YouTube audio after transcription (Phase 6 — D-05; deletion is the default, "keep" is a future option).

</domain>

<decisions>
## Implementation Decisions

### Ingest stage (no upload UI yet)
- **D-01:** The two ingest paths are **kept strictly separate, never mixed** (user explicit). `source_type` already distinguishes them on `CreateJobRequest` / `JobManifest`. Phase 4 implements **only `source_type=local`**; the `source_type=youtube` branch is a clean seam (dispatch stub) that Phase 6 fills in with yt-dlp. No half-built YouTube anything in Phase 4. The MVP ingest contract is "link a local file → transcribe it" (user: "in the MVP phase I just want to have to link youtube video or local files to be transcribed").
- **D-04:** Local-file ingest **references the file in place — no copy, no duplication** (user explicit: "only reference I don't need to do duplicates, space management is important"). The manifest records the absolute `source_path`; the transcriber reads from `source_path` directly. Nothing is copied into `data/jobs/<id>/`. This **refines Phase 1 D-11**: the `ingested` stage-completion check changes from "a `source.<ext>` file exists in the job dir" to "`manifest.source_path` is set and that path exists and is non-empty". Phase 5 (browser upload) and Phase 6 (YouTube download) still use the in-job-dir `source.<ext>` variant, so the generalized `ingested` check is "either `manifest.source_path` resolves OR a `source.<ext>` exists in the job dir". `source_sha256` for local-reference ingest is **optional / best-effort** — computing it for a multi-GB file is expensive and not needed for MVP idempotency (D-07 uses a client key, not a content hash). The researcher/planner may compute it lazily or skip it.
- **D-05 [forward, Phase 6]:** Downloaded YouTube audio is **deleted after transcription** (user explicit: "even for youtube videos I don't want to keep them after transcription, they should be deleted. Later we will add this as an option"). Space management is a standing principle. Recorded here so Phase 6 inherits it; the "keep after transcription" toggle is a future option (Phase 10 settings panel).

### Resume / restart behavior
- **D-02:** **No mid-transcription (mid-chunk) resume.** The chunker does **not** checkpoint partial progress. The orchestrator reuses the existing file-as-truth walker `infer_resume_point` (Phase 1 D-12) — a crashed transcription leaves **no** `transcript.json` (the atomic write only fires at the end of the whole transcribe call), so the walker naturally re-transcribes **from scratch** = "from the beginning" (user: "I don't need to start in the middle of transcribing"). This is low-complexity (the walker already exists), so it stays. We do **not** build a separate "clear all stage files and restart" path. A job that had `transcribed` complete and a *later* stage fail (Phase 7/8 territory) would resume from that later stage — acceptable, and out of Phase 4's scope anyway.
- **D-03:** **No auto-resume on backend restart.** A new boot step (in `lifespan`, after `reconcile_all`) marks any job left in an active stage (`ingesting` / `transcribing` / …) as **`failed`** with `error="interrupted (backend restarted)"`, and **preserves the source file/video name** (already on `manifest.source_path` + the `jobs.source_path` column) so the user can find it in history later (user: "just keep track that something got interrupted and have log with error saved same with file or video name so I can find it later and restart transcription. We don't even need to have a restart button for MVP"). No restart button in MVP — the user finds the failed job by name and re-submits manually. This composes with Phase 1 `reconcile_all` (which heals DB/FS drift) — the new step runs after reconcile and projects the interrupted status back to the DB.

### Cancel
- **D-06:** Cancel of a **queued** job is instant (Phase 1 `cancel_job` — DB-first, rmtree the job dir). Cancel of a **running** job is **cooperative**: the orchestrator sets a cancel flag the chunker checks between chunks (the chunker already runs chunk-by-chunk), stops after the current chunk, **discards the partial transcript** (no `transcript.json` was written yet), and marks the job `cancelled`. Because D-02 means we never resume mid-transcription anyway, there is no need to preserve partial output — discard is safe and simplest ("as simple as possible"). `cancel_job`'s DB-first-then-rmtree ordering and `retry_windows` rmtree (Phase 1 D-13) are reused. Cancellation is idempotent (cancelling an already-terminal job is a no-op that returns the current row).

### Idempotent submit (SC-5)
- **D-07 [Claude's Discretion + cross-AI review]:** Idempotency via a **client-provided `Idempotency-Key` HTTP header** (standard pattern). A new `idempotency_keys` table (migration in Phase 4: `key TEXT PRIMARY KEY, job_id TEXT NOT NULL, created_at TEXT NOT NULL`) maps a key → existing `job_id`. A `POST /jobs` carrying a key already present returns the existing `JobResponse` (200) instead of creating a duplicate; a missing key creates a new job as today. The key is held for a bounded TTL (e.g. 24h) — the researcher/planner picks the exact window. This avoids hashing multi-GB files (D-04 skips content hashing) and is the simplest SC-5-satisfying mechanism. **"Re-submitting the same source file reuses the existing job"** (content-based dedupe) is explicitly a **future option**, not MVP — the user did not ask for it and it would require a sha256 scan.

### Concurrency / queue dispatch
- **D-10 [locked by prior phases, recorded]:** **Worker = 1, strict FIFO serial.** One model-resident stage runs at a time. This is *forced* by HW-09 (no concurrent multi-model residency) + Phase 2 D-04 (a second model load is refused with `409 ConcurrentModelRefused` when `concurrent_models=False`, the default). The queue is a true FIFO with a single worker; `queued` jobs wait their turn. Non-GPU stages (ingest for a local file = a cheap path validation) could theoretically overlap, but for MVP simplicity the whole job runs serially end-to-end (one job at a time). The researcher/planner may overlap ingest of job N+1 with transcription of job N **only if it is low-complexity** — otherwise keep it fully serial.

### WebSocket progress (SC-3, JOB-06)
- **D-08 [Claude's Discretion + cross-AI review]:** A **per-job** WebSocket endpoint `GET /ws/jobs/{id}/events` (SC-3 says "per-job progress events … the front-end can subscribe to"; a global `/ws/events` stream is a future option, not MVP). On connect the server sends a **state snapshot** (current stage, percent, ETA, status) then live events thereafter, so a refresh/reconnect does not lose the current picture. The pub/sub backbone is an **in-process asyncio event bus** (single-process app, no external broker) — the orchestrator publishes progress events; the WS handler subscribes for the job. Events: `stage_changed`, `progress` (percent + ETA), `done`, `failed`, `cancelled`. Reconnection is client-driven (snapshot-on-connect makes it safe); no server-side resume buffer.
- **D-09 [Claude's Discretion + cross-AI review]:** Progress / ETA granularity: **per-stage binary** for `ingesting` (0% → 100% — local-file ingest is a cheap validation); **per-chunk percent** for `transcribing` (chunks completed / total chunks from the Phase 3 chunker, plus faster-whisper segment progress within a chunk when cheaply observable); ETA = `elapsed / percent` with a **minimum-sample threshold** before ETA is emitted (avoid wild early estimates; hide ETA until enough data). The exact event schema and emit cadence are the researcher/planner's call.

### Stale detection
- **D-11 [Claude's Discretion + cross-AI review]:** A periodic stale-sweep reuses Phase 1 `is_stale` / `mark_stale` with the **D-13 10-minute threshold**. The orchestrator runs a watchdog (e.g. an asyncio task on a cadence the planner picks) that calls `mark_stale` on active jobs; the existing `POST /jobs/{id}/stale-check` admin route stays. The sweep is status-aware (Phase 1 M3 already short-circuits `done`/`failed`/`cancelled`).

### Cross-AI review (standing, user-requested)
- **D-12 [informational, carried from Phase 3 D-09]:** Run a cross-AI review pass (codex + gemini, configured as `review.default_reviewers`) on the Phase 4 plans after `/gsd-plan-phase 4` and on the implementation after execution. They fire when their runtimes are present; if only one is, that one reviews. This is a standing project preference, not a Phase 4 deliverable. Claude's D-07..D-11 above are the **starting position** the reviewers should pressure-test.

### Carried forward from earlier phases (locked — not re-asked)
- **Phase 1 D-04:** atomic writes (`<name>.tmp` → fsync → `os.replace`) — every manifest / stage write the orchestrator does inherits this via `app/storage/atomic.py`.
- **Phase 1 D-05:** `manifest.json` is the rich "one read = full picture" snapshot; rewritten by every stage mutator.
- **Phase 1 D-11/D-12:** stage↔file mapping + the file-as-truth resume walker (`infer_resume_point`, `STAGE_ORDER`) — reused as-is by the orchestrator (D-02). The `ingested` check is refined per D-04.
- **Phase 1 D-13:** cancel = DB-first then rmtree (`cancel_job`); failure = keep folder + mark failed (`mark_failed`); stale = 10-min threshold (`is_stale`/`mark_stale`).
- **Phase 1 machinery the orchestrator drives:** `create_job` (INSERT → folder → manifest, H5 compensation), `update_stage` (write-manifest-first / commit-DB-last, `stage_to_status`, full projection), `reconcile_all` (boot DB/FS heal), the `jobs` table + migrations 0001..0007.
- **Phase 2 D-02:** just-in-time model load **at stage start** — the `transcribing` stage loads the STT model via `ModelManager.load(ModelCategory.STT)` right before it runs. **Prefetch-at-submit stays deferred** (carried from Phase 2; the user's "as simple as possible" keeps it deferred again for Phase 4).
- **Phase 2 D-03/D-04:** explicit-only model unload; a second model load is refused with `409 ConcurrentModelRefused`. This is what forces worker=1 serial (D-10). The orchestrator owns the load/unload sequence per stage (load STT → transcribe → unload, or leave resident per D-03 explicit-only until the next job needs the VRAM / the process exits).
- **Phase 3:** `STTAdapter` Protocol + `FasterWhisperAdapter` + chunker (`app/models/stt/`). The orchestrator's `transcribing` stage calls `STTAdapter.transcribe(...)` — **never imports `faster_whisper`/`ctranslate2`** (SC-4-style boundary check: `grep -rE 'from faster_whisper|import ctranslate2' app/` matches only `app/models/stt`). Device + compute_type resolve from persisted `settings.backend` via `device_for`.

### Claude's Discretion
D-07 (idempotency-key mechanism), D-08 (WS endpoint shape + snapshot-on-connect + in-process event bus), D-09 (progress/ETA granularity + emit cadence), D-10's "may overlap ingest if low-complexity" latitude, D-11 (stale-sweep cadence). All are recorded with a rationale and a recommended default above; cross-AI review (D-12) pressure-tests them.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher/planner/executor) MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — single-user no-auth (no auth surface on the WS / control endpoints), back-end is the only thing that touches models + filesystem, "Job queue persistence across restarts" constraint (the source of SC-2 / D-03), **space management is a stated concern** (the source of D-04 reference-in-place + D-05 delete-after-transcribe).
- `.planning/REQUIREMENTS.md` — Phase 4 owns `JOB-02` (background jobs), `JOB-04` (queue persists across restarts), `JOB-05` (cancel queued or running), `JOB-06` (per-job progress stage/percent/ETA). Traceability table lines 135–139.
- `.planning/ROADMAP.md` — Phase 4 goal, mode (mvp), success criteria SC-1..SC-5, plans 04-01 / 04-02 / 04-03.
- `.planning/STATE.md` — "ready to plan Phase 04"; no Phase-4 blockers flagged (ROCm / yt-dlp / pyannote / LLM concerns are Phase 2/6/7/8).

### Prior phase context
- `.planning/phases/03-stt-adapter-audio-chunker-standalone-cli/03-CONTEXT.md` — `STTAdapter` Protocol + chunker + CLI; the orchestrator reuses the adapter as the `transcribing` stage. D-05 (CUDA laptop primary, desktop CPU fallback), D-06 (boundary check), D-08 (int8 verification).
- `.planning/phases/02-gpu-backend-detection-model-manager/02-CONTEXT.md` — D-02 (JIT load at stage start), D-03 (explicit-only unload), D-04 (409 refuse second model — forces worker=1), the `ModelManager.load` path, the `device_for` seam.
- `.planning/phases/01-back-end-skeleton-storage-data-layout/01-CONTEXT.md` — D-04 atomic writes, D-05 rich manifest, D-11/D-12 file-as-truth + resume walker, D-13 cancel/failure/stale lifecycle, D-15 lax output models.

### Existing code (the seams Phase 4 plugs into)
- `app/jobs/service.py` — `create_job` / `list_jobs` / `get_job` (the orchestrator's submit path extends `create_job` with idempotency, D-07).
- `app/jobs/manifest.py` — `update_stage` (write-manifest-first / commit-DB-last), `stage_to_status`, `empty_manifest`, `read_manifest`. The orchestrator's stage transitions go through `update_stage` (NOT a raw HTTP call).
- `app/jobs/resume.py` — `infer_resume_point`, `is_stage_complete`, `STAGE_ORDER`, `parse_stage_file`. Reused as-is (D-02); the `ingested` branch is refined per D-04 (check `manifest.source_path`).
- `app/jobs/reconcile.py` — `reconcile_all` (boot DB/FS heal). The new "mark interrupted in-flight jobs failed" boot step (D-03) runs **after** this.
- `app/jobs/cleanup.py` — `cancel_job`, `mark_failed`, `is_stale`, `mark_stale`, `_TERMINAL_STATUSES`. Reused for cancel + stale-sweep.
- `app/api/routes_jobs.py` — existing `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel|stage|stale-check`. The docstring explicitly says "Phase 4 replaces these with authenticated, worker-bound endpoints." The orchestrator drives stages via the service layer (not HTTP); the `/stage` and `/stale-check` HTTP routes become admin-only or are removed (planner decides — single-user no-auth, "authenticated" is loose).
- `app/main.py` `lifespan` — the single boot path; Phase 4 adds the interrupted-job sweep (D-03) after `reconcile_all`, and starts the orchestrator worker + stale watchdog.
- `app/models/job.py` — `JobStatus` / `JobResponse` / `CreateJobRequest` / `StageUpdateRequest`. Extended for idempotency + WS event models.
- `app/models/manifest.py` — `JobManifest` (the on-disk snapshot the orchestrator reads/writes via `update_stage`).
- `app/storage/fs.py` — path helpers + `validate_source_ext`; D-04 generalizes the `ingested` check (no `source.<ext>` required for local-reference jobs).
- `app/storage/db.py` — `make_engine` (WAL per-connection), `apply_migrations`. Phase 4 adds a new migration (idempotency_keys table; any queue columns).
- `app/models/stt/protocol.py` + `adapter.py` + `chunker.py` — the `transcribing` stage calls `STTAdapter.transcribe(...)` and reports per-chunk progress to the event bus (D-09).
- `app/models/manager.py` — `get_manager().load(ModelCategory.STT)` (JIT at stage start, D-02 carried) + `unload`/`unload_all`.
- `migrations/0001_initial.sql` … `0007_add_stage_timestamps_json.sql` — the migration pattern (one column/table per file, `NNNN_description.sql`, duplicate-column guard). Phase 4's idempotency_keys migration follows this.
- `tests/conftest.py` — `tmp_data_dir` + `app_under_test` + `httpx.AsyncClient` + mocked-seams pattern; Phase 4 orchestrator tests mock `STTAdapter` (no real GPU / no real model load) and use `httpx`'s WebSocket support or a WS test client.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/jobs/manifest.py::update_stage` — the orchestrator's every stage transition goes through this (write-manifest-first, commit-DB-last, `stage_to_status`, full projection). No new stage-mutation code needed; the orchestrator just *calls* it in sequence.
- `app/jobs/resume.py::infer_resume_point` — the resume walker. D-02 reuses it; no mid-chunk checkpointing is added.
- `app/jobs/cleanup.py` — `cancel_job` (DB-first + retried rmtree), `mark_failed`, `mark_stale` (status-aware). Cancel + stale-sweep are thin calls on these.
- `app/jobs/reconcile.py::reconcile_all` — boot DB/FS heal; D-03's interrupted-sweep runs right after it.
- `app/storage/atomic.py::atomic_write_json` — every manifest / event-snapshot write.
- `app/models/stt/` — the `transcribing` stage is a thin caller of `STTAdapter`; the chunker already runs chunk-by-chunk so per-chunk progress (D-09) and cooperative cancel (D-06) plug in at the chunk boundary.

### Established Patterns
- **File-as-truth** (Phase 1 D-11/D-12) — the orchestrator never trusts the DB alone for "what stage is this job in"; it reads the files via `is_stage_complete`.
- **Write-manifest-first / commit-DB-last** (Phase 1) — every orchestrator stage transition; a crash between the two is healed by `reconcile_all` on boot.
- **Strict input / lax output** at the API boundary (Phase 1 D-15) — new request models (`Idempotency-Key` handling, WS event payloads) are strict-in; `JobResponse` and event models stay lax-out.
- **Lazy in-body imports + package boundary check** (Phase 2/3) — the orchestrator imports `STTAdapter` (the Protocol), never `faster_whisper`/`ctranslate2`. `grep -rE 'from faster_whisper|import ctranslate2' app/` must still match only `app/models/stt`.
- **Migration-per-concern** (Phase 1 D-07/D-08/D-09) — one new `NNNN_*.sql` file for the `idempotency_keys` table (+ any queue column), hand-rolled, idempotent.
- **Atomic settings + restart-only `data_dir`** (Phase 1 H1) — unaffected; Phase 4 adds no settings fields (the queue config is constants for MVP).

### Integration Points
- New modules Phase 4 CREATES: `app/jobs/orchestrator.py` (the worker loop + state-machine driver + cancel flag), `app/jobs/queue.py` (SQLite-backed FIFO + restart re-join), `app/jobs/progress.py` (the in-process event bus + percent/ETA), `app/api/routes_ws.py` (or a WS handler in `routes_jobs.py`) for `GET /ws/jobs/{id}/events`, a new `migrations/0008_idempotency_keys.sql` (and `0009_*` if queue columns are added), `app/jobs/interrupt.py` (or a function in `reconcile.py`) for the boot interrupted-sweep (D-03).
- `app/main.py` `lifespan` gains: run the interrupted-sweep after `reconcile_all` (D-03), then start the orchestrator worker + stale watchdog; teardown stops them before `engine.dispose()`.
- `app/api/routes_jobs.py` `POST /jobs` gains `Idempotency-Key` header handling (D-07); the `/stage` and `/stale-check` routes are either kept admin-only or removed (planner).
- Downstream: Phase 5 local-file upload writes `source.<ext>` into the job dir (the in-job-dir half of the generalized `ingested` check, D-04) and renders progress from the WS events; Phase 6 fills the `source_type=youtube` ingest branch + playlist queue + deletes audio after transcription (D-05); Phase 7/8 add `diarizing`/`summarizing` stages as "just another stage" driven by the same orchestrator.

</code_context>

<specifics>
## Specific Ideas

- **"As simple as possible" is the user's load-bearing steer this session.** Where two implementations satisfy a success criterion, pick the simpler one; defer the cleverer one (e.g. content-hash idempotency, prefetch-at-submit, mid-chunk resume, a global WS stream, restart button). The user wants the spine working and minimal, not feature-rich.
- **Do not mix the two ingest paths** (user explicit) — local file and YouTube stay separate code paths sharing only the `source_type` dispatch + the file-as-truth `ingested` check. No unified "ingest abstraction" that merges them.
- **Space management is a stated principle** (user explicit) — drives D-04 (reference in place, no copy) and D-05 (delete YouTube audio after transcription). "Keep after transcription" is a future settings option, not MVP.
- **No mid-transcription resume** (user explicit) — the chunker does not checkpoint; a crashed/interrupted transcribe restarts the whole transcribe call. This is the user's explicit simplification and overrides any "resume from last chunk" cleverness.
- **Interrupted jobs are findable, not auto-resumed** (user explicit) — on restart, mark failed with the source name preserved; the user finds it in history and re-submits. No restart button for MVP.
- **Playlist behavior is Phase 6, not Phase 4** (user forward-guidance): on playlist cancel, remember which child video stopped; resume the playlist from that child, but **restart that child video from the beginning** (no mid-transcription resume, consistent with D-02). Phase 4's queue/cancel design stays playlist-compatible (a playlist = a sequence of jobs; cancel/resume at the playlist level, each child restarts whole) but does not implement it.

</specifics>

<deferred>
## Deferred Ideas

- **Browser drag-and-drop / streaming upload UI + endpoint** — Phase 5 (writes `source.<ext>` into the job dir; the other half of D-04's generalized `ingested` check).
- **YouTube ingest / yt-dlp / playlist fan-out / pause-resume / timestamp link-out** — Phase 6. Includes D-05 (delete audio after transcription) and the playlist resume behavior above.
- **"Restart from beginning" button in the UI** — future; MVP uses manual re-submit (D-03).
- **Mid-chunk transcription checkpointing / resume from last chunk** — explicitly rejected for MVP (D-02); a future optimization only if re-transcribing long videos becomes a real pain point.
- **Content-hash idempotency (same source file → reuse existing job)** — future option; MVP uses a client `Idempotency-Key` header (D-07).
- **Global WebSocket stream (`/ws/events` for all jobs)** — future; MVP is per-job (D-08).
- **Prefetch the STT model at job-submit** (overlap download/load with ingest) — carried from Phase 2 D-02; deferred again for Phase 4 ("as simple as possible"). JIT load at stage start stays.
- **"Keep YouTube audio after transcription" toggle** — future settings option (Phase 10); default is delete (D-05).
- **`source_sha256` for local-reference ingest** — optional / best-effort for MVP (D-04); may be computed lazily if idempotency or dedupe ever needs it.
- **Overlap ingest of job N+1 with transcription of job N** — only if low-complexity (D-10 latitude); default is fully serial one-job-at-a-time.

</deferred>

---

*Phase: 4-Job Orchestrator + Persistent Queue + WebSocket Progress*
*Context gathered: 2026-06-22 via /gsd-discuss-phase (interactive, default mode; product gray areas resolved by explicit user guidance — simple-as-possible, reference-in-place, no mid-transcription resume, interrupted jobs findable not auto-resumed; technical areas Claude's Discretion + cross-AI review per D-09/D-12)*