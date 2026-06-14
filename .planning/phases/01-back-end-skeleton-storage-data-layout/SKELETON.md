# Walking Skeleton — TranscriptionAndNotes Back-End

**Phase:** 1 (Plans 01-01, 01-02, 01-03)
**Generated:** 2026-06-11

## Capability Proven End-to-End

A back-end service boots locally, applies versioned SQLite migrations in WAL mode, and serves an OpenAPI schema over HTTP. `POST /jobs` creates a real job end-to-end: a UUIDv4 row is inserted, `data/jobs/<id>/` is created on disk, and `manifest.json` is written atomically. `GET /jobs` lists jobs newest-first, `GET /jobs/{id}` returns one, `GET /settings` exposes the validated Pydantic settings, `PATCH /settings` updates them atomically, `POST /jobs/{id}/cancel` deletes the folder, `POST /jobs/{id}/stage` is the single helper every later stage adapter uses to update `current_stage` + `stage_timestamps` in both the manifest and the DB row, and `POST /jobs/{id}/stale-check` runs the 10-minute staleness rule from D-13. The OpenAPI schema is consumable by `openapi-typescript` in the front-end repo (Phase 5).

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Web framework | FastAPI 0.110+ on Uvicorn (ASGI) | Async-native, free OpenAPI schema, WebSocket-ready for Phase 4, the de-facto Python web framework for ML back-ends |
| ORM | SQLAlchemy 2.0 async + aiosqlite | Pinned in D-06; async session per request, no sync paths in app code |
| Migrations | Hand-rolled `schema_version` table + numbered `migrations/*.sql` (no Alembic) | Pinned in D-07, D-08; the project does not need autogenerate; the schema is small and the rule "each file is one transaction" is enforced manually |
| Settings | `data/settings.json` loaded into a Pydantic v2 model on boot; the Pydantic model is the source of truth | Pinned in D-14, D-17; the file is a serialization, not the schema |
| Request validation | Pydantic v2 strict input (`ConfigDict(strict=True, extra="forbid")`) on all request models; lax/default config for response and storage models | Pinned in D-15; catches front-end bugs at the API boundary without making internal model-to-model conversion tedious |
| Atomic writes | `tmp + fsync + os.replace` via a single `app.storage.atomic.atomic_write_*` helper used for every stage output, every manifest rewrite, and every settings change | Pinned in D-04; pitfall 9 mitigation |
| File-as-truth | The per-job folder's files are the source of truth; the DB row is the index. Stage transitions are atomic against file existence. `infer_resume_point` walks the standard order | Pinned in D-11, D-12; pitfall 9 mitigation |
| Front-end codegen | `openapi-typescript` types only; front-end writes fetch calls by hand | Pinned in D-16; pitfall 7 mitigation |
| Per-job folder shape | `data/jobs/<id>/{source.ext, transcript.json, diarization.json, summary-<kind>.json, edits.json, manifest.json}` — flat, no per-stage subfolders | Pinned in D-03 |
| Module boundary | `app.api`, `app.jobs`, `app.storage`, `app.models`, plus the new `app.settings` — no other code may import a storage atomic helper or a DB session directly except through these | Required by Phase 1 success criterion 5; pitfall 7 mitigation |
| Job IDs | UUIDv4 strings, stored as TEXT; sort via a separate `created_at` column with a DESC index | Pinned in D-10 |
| Stage staleness | 10 minutes (hardcoded constant, not yet a setting) | Pinned in D-13; Phase 10 may promote it to a setting |
| Front-end (this project) | None in Phase 1 | Pinned in D-01: back-end and front-end are two repos. The OpenAPI contract is the bridge. |
| Deployment target (Phase 1) | `uvicorn app.main:app` against a local SQLite file in `data/app.db` (WAL mode); `data/` lives next to the backend executable, overridable via `data/settings.json → data_dir` | Pinned in D-02; no Dockerfile yet — Phase 0 will add Docker if/when needed |

## Stack Touched in Phase 1

- [x] Project scaffold (`pyproject.toml`, `.gitignore`, `data/`, `migrations/`, `app/`, `tests/`)
- [x] Routing — `GET /health`, `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/stage`, `POST /jobs/{id}/stale-check`, `GET /settings`, `PATCH /settings`, plus FastAPI's `GET /openapi.json` and `GET /docs`
- [x] Database — `data/app.db` (WAL) with `schema_version`, `jobs`, `settings`; migrations `0001_initial.sql` and `0002_add_source_sha256.sql` through `0007_add_stage_timestamps_json.sql` (one ALTER per file); idempotent per-statement migration runner
- [x] API — at least one real DB read (`GET /jobs/{id}`) AND one real DB write (`POST /jobs`) AND one real filesystem write (`manifest.json` via atomic helper)
- [x] Deployment — documented local full-stack run command: `pip install -e .[dev] && uvicorn app.main:app`

## Out of Scope (Deferred to Later Slices)

This is the explicit list of what is NOT in the skeleton. Future phases will not re-litigate these.

- **Model adapters** (faster-whisper, pyannote, llama-cpp-python) — Phase 2 onward
- **GPU backend detection** (CUDA / ROCm / CPU) — Phase 2
- **Model manager / download / VRAM discipline** — Phase 2
- **STT pipeline + audio chunker + CLI** — Phase 3
- **Job orchestrator + persistent queue + WebSocket progress** — Phase 4 (the `POST /jobs/{id}/stage` route built here is the single helper Phase 4 calls for every transition)
- **Local file ingest (streaming upload)** — Phase 5
- **YouTube ingest + playlist fan-out** — Phase 6
- **Diarization adapter + speaker rename** — Phase 7
- **LLM adapter + four summary templates** — Phase 8
- **Transcript editor + Markdown export** — Phase 9
- **Settings panel (GPU backend indicator, quality preset, per-category override, HF token, diagnostics, first-run card)** — Phase 10 (the `Settings` Pydantic model here is the single field from D-17; the rest is added by the phase that needs it)
- **Tables that later phases own** — `transcript_segments`, `job_events`, `queue_positions`, `summary_outputs`, `speaker_aliases` (D-09: not in Phase 1)
- **Dockerfile + containerization** — not in Phase 1 (D-01: dockerization is on the roadmap but the Docker story is project-wide, not phase-1-specific)
- **Front-end (React + Vite SPA)** — separate repo, ships in Phase 5
- **WebSocket progress broadcast** — Phase 4
- **Authentication / multi-user** — out of scope (PROJECT.md: single user, no auth)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: GPU backend detection (CUDA/ROCm/CPU) on first run, writes `settings.gpu_backend`; model manager downloads + lazy-loads + idle-unloads; first-run settings.json write
- Phase 3: STT adapter (faster-whisper int8) + audio chunker + standalone CLI that writes `transcript.json` per the D-11 rule; CLI uses `update_stage` from this skeleton
- Phase 4: In-process job orchestrator + SQLite-backed queue (new `job_events` table via a new migration) + WebSocket progress; orchestrator calls `update_stage` for every transition; periodic `mark_stale` loop replaces the admin endpoint from this skeleton
- Phase 5: React front-end repo, codegen via `openapi-typescript`, 3-pane layout, drag-and-drop upload that calls `POST /jobs` and listens on the WebSocket
- Phase 6: YouTube ingest via yt-dlp; new `source_type` value; timestamp link-out
- Phase 7: Diarization adapter (pyannote, HF-token-gated); writes `diarization.json`; adds `speaker` field to `TranscriptSegment`; renames stay in `edits.json`
- Phase 8: LLM adapter (llama-cpp-python) + four typed summary schemas; writes `summary-<kind>.json`; the `sections` field of the `Summary` Pydantic model is replaced by per-kind typed schemas
- Phase 9: Transcript editor + find-and-replace + Markdown export; PATCH on `TranscriptSegment.text` writes to `edits.json`
- Phase 10: Settings panel exposes every `Settings` field; the `Settings` Pydantic model is extended with `gpu_backend`, `hf_token`, `quality_preset`, `per_category_overrides`; the file-on-disk shape is still `{key: value, ...}` so backward compat is maintained

## Locked Decision Coverage (D-01..D-17)

| ID | Plan | Coverage |
|---|---|---|
| D-01 | All | Back-end lives in this repo; OpenAPI is the contract for the future front-end repo |
| D-02 | 01-01, 01-02 | `data/` next to the executable; overridable via `data/settings.json → data_dir` |
| D-03 | 01-03 | Flat per-job folder with the six named files |
| D-04 | 01-01, 01-02, 01-03 | `app.storage.atomic.atomic_write_*` used by every stage output, every settings change, every manifest rewrite |
| D-05 | 01-01, 01-02, 01-03 | `JobManifest` Pydantic model with all eleven fields from D-05; `read_manifest` and `write_manifest` round-trip; `update_stage` keeps it consistent with the DB row |
| D-06 | 01-01, 01-02 | SQLAlchemy 2.0 async + aiosqlite end-to-end; all FastAPI routes are `async def` and use `AsyncSession` via `Depends(get_session)` |
| D-07 | 01-01, 01-02 | Hand-rolled `schema_version` table + `migrations/0001_initial.sql` and `migrations/0002_remaining_jobs_columns.sql`; no Alembic |
| D-08 | 01-01, 01-02 | `apply_migrations` runs on lifespan startup; on failure the server refuses to start (lifespan re-raises) |
| D-09 | 01-01, 01-02 | Only `jobs`, `settings`, `schema_version` tables in Phase 1; no `transcript_segments`, `job_events`, etc. |
| D-10 | 01-01, 01-02 | `id` is TEXT UUIDv4; `created_at` is a separate TEXT column with a DESC index |
| D-11 | 01-01, 01-03 | `is_stage_complete` checks the right file for each stage; the path helpers in `app.storage.fs` name the locked files |
| D-12 | 01-03 | `infer_resume_point` walks the standard order; the filesystem is the truth, the DB is the index |
| D-13 | 01-03 | `cancel_job`, `mark_failed`, `mark_stale` with the 10-minute threshold implemented; admin/test route in Phase 1, real loop in Phase 4 |
| D-14 | 01-01, 01-02 | `data/settings.json` loaded into the `Settings` Pydantic model on boot; atomic write on `PATCH /settings` |
| D-15 | 01-01, 01-02 | Strict `ConfigDict(strict=True, extra="forbid")` on every request model; lax/default on every response and storage model |
| D-16 | 01-01, 01-02, 01-03 | OpenAPI schema generated from the live Pydantic models; front-end codegen runs in Phase 5 from this exact schema |
| D-17 | 01-01, 01-02 | `Settings` has only `data_dir: str` in Phase 1 |
