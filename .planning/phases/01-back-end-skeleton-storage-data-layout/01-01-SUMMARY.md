---
phase: 01-back-end-skeleton-storage-data-layout
plan: 01-01
subsystem: backend
provides:
  - fastapi_app_skeleton
  - sqlite_wal_engine
  - job_creation_endpoint
  - atomic_write_helper
  - retry_helper
  - timezone_aware_timestamps
  - openapi_contract
requires: []
affects: [phase-2-gpu, phase-3-stt, phase-4-orchestrator, phase-5-frontend, phase-7-diarization, phase-8-summarization, phase-9-editor, phase-10-settings-panel]
tech-stack:
  added: [fastapi, uvicorn, pydantic, sqlalchemy, aiosqlite, aiofiles, pytest, pytest-asyncio, httpx]
  pinned: "lower bounds only (>=) — no lockfile in Phase 1"
key-files:
  created:
    - pyproject.toml
    - .gitignore
    - .env.example
    - data/.gitkeep
    - data/jobs/.gitkeep
    - app/__init__.py
    - app/util/__init__.py
    - app/util/time.py
    - app/models/__init__.py
    - app/models/settings.py
    - app/models/common.py
    - app/models/job.py
    - app/models/manifest.py
    - app/storage/__init__.py
    - app/storage/retry.py
    - app/storage/atomic.py
    - app/storage/fs.py
    - app/storage/db.py
    - app/jobs/__init__.py
    - app/jobs/ids.py
    - app/jobs/manifest.py
    - app/jobs/service.py
    - app/api/__init__.py
    - app/api/dependencies.py
    - app/api/routes_health.py
    - app/api/routes_jobs.py
    - app/main.py
    - migrations/0001_initial.sql
    - migrations/README.md
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_health.py
    - tests/test_openapi.py
    - tests/test_create_job.py
    - tests/test_atomic_windows_retry.py
  modified: []
decisions:
  - id: D-04
    summary: "Atomic write helper at app/storage/atomic.py: tmp + fsync + os.replace, retried on Windows"
  - id: D-05
    summary: "JobManifest Pydantic model with all eleven D-05 fields (schema_version, job_id, source_type, source_path, source_sha256, duration_s, language, summary_kinds, status, current_stage, stage_timestamps, error)"
  - id: D-06
    summary: "SQLAlchemy 2.0 async + aiosqlite end-to-end; AsyncSession via Depends(get_session)"
  - id: D-07
    summary: "Hand-rolled schema_version table + migrations/0001_initial.sql; no Alembic; the runner is in app/storage/db.py::apply_migrations"
  - id: D-08
    summary: "Lifespan applies migrations on boot and re-raises on failure so the server refuses to start"
  - id: D-09
    summary: "Phase 1 ships only jobs, settings, schema_version tables"
  - id: D-10
    summary: "Job id is TEXT UUIDv4; created_at is a separate TEXT column with a DESC index"
  - id: D-14
    summary: "data/settings.json is the serialisation of the Settings Pydantic model; loaded into a typed model on boot"
  - id: D-15
    summary: "Pydantic v2 strict for input (ConfigDict(strict=True, extra='forbid')); lax/default for response and storage models; the JobResponse.created_at field_serializer emits +00:00 (not the Z shorthand)"
  - id: D-16
    summary: "JobManifest registered in components.schemas via responses= on POST /jobs; the schema is consumable by openapi-typescript in Phase 5"
  - id: D-17
    summary: "Settings has only data_dir: str in Phase 1"
  - id: bootstrap-stable-path
    summary: "data_dir lives in a STABLE absolute file (data/settings.json resolved via Path(__file__).resolve().parent.parent.parent from app/storage/fs.py), so patching data_dir cannot move the settings file (Codex HIGH fix)"
  - id: per-connection-wal
    summary: "PRAGMA journal_mode=WAL, PRAGMA foreign_keys=ON, PRAGMA synchronous=NORMAL are asserted on every connection via event.listens_for(engine.sync_engine, 'connect'), not just the first (Gemini LOW fix; verified by opening two distinct connections in tests)"
  - id: retry-on-replace
    summary: "os.replace is wrapped in app/storage/retry.py::retry_windows; both PermissionError and OSError are retried with linear backoff (avoids Windows antivirus / Search Indexer PermissionError on replace)"
  - id: openapi-jobmanifest
    summary: "POST /jobs declares responses={201: {'model': JobManifest}} so JobManifest is registered in components.schemas; the front-end can pull the typed contract via openapi-typescript"
test-coverage:
  total: 13
  passing: 13
  names:
    - test_retry_succeeds_after_two_permission_errors
    - test_retry_gives_up_after_attempts
    - test_retry_handles_oserror
    - test_retry_propagates_non_retriable
    - test_atomic_write_bytes_uses_retry_on_replace
    - test_post_jobs_creates_job_end_to_end
    - test_post_jobs_rejects_unknown_field
    - test_post_jobs_manifest_is_valid_pydantic
    - test_health
    - test_trusted_host_rejects_evil_host
    - test_cors_preflight_allows_vite
    - test_openapi_paths
    - test_openapi_manifest_schema
verification:
  pip_install: "pip install -e .[dev] succeeds"
  pytest: "13 passed in ~1.2s"
  uvicorn_boot: "uvicorn app.main:app --port <N> starts cleanly; lifespan prints 'TranscriptionAndNotes backend ready: data_dir=...'"
  health: "GET /health returns 200 {\"status\":\"ok\"}"
  openapi_paths: "/jobs and /health are in paths"
  openapi_jobmanifest: "JobManifest is in components.schemas with the D-05 field names"
  post_jobs: "POST /jobs with body {} returns 201 JobResponse whose created_at ends with +00:00 and id is a UUIDv4"
  manifest_on_disk: "data/jobs/<id>/manifest.json exists and round-trips through JobManifest.model_validate"
  wal_per_connection: "Opening two distinct connections from the same engine returns journal_mode=wal on both"
  cors_preflight: "OPTIONS /jobs with Origin: http://localhost:5173 returns Access-Control-Allow-Origin: http://localhost:5173"
  trusted_host: "GET /health with Host: evil.example returns 400"
  stable_settings_path: "bootstrap_settings_path() returns an absolute path ending in settings.json"
  api_boundary: "grep -rE 'from app\\.storage\\.atomic|from app\\.storage\\.fs' app/api/ returns NO matches (api modules do not import storage internals)"
  no_deprecated_datetime: "grep -rE 'datetime\\.utcnow\\(\\)' app/ returns NO matches (verified after rephrasing the docstring on utcnow_iso)"
---

# Plan 01-01 SUMMARY — Walking Skeleton (FastAPI boot + first end-to-end job creation)

## What landed

The back-end service skeleton is in place. `uvicorn app.main:app` boots a
FastAPI app that owns its DB, applies versioned migrations in WAL mode
on every boot, and serves a typed OpenAPI contract the front-end will
later consume via `openapi-typescript`. `POST /jobs` creates a job
end-to-end: a UUIDv4 row is INSERTed, `data/jobs/<id>/` is created on
disk, and `manifest.json` is written atomically. The atomic write
helper retries `os.replace` to survive transient Windows file locks
(antivirus / Search Indexer). Every timestamp in the codebase goes
through `app.util.time.utcnow_iso`, which uses
`datetime.now(timezone.utc).isoformat()` and never the deprecated
`datetime.utcnow()` form.

The four-module boundary is enforced by convention and verified by
the boundary-check grep: `app/api/` does not import
`app.storage.atomic` or `app.storage.fs`; the storage helpers are
imported only by `app/storage/*`, `app/jobs/*`, and the test files.
`app/jobs/service.create_job` is the only call site that wires the
DB INSERT, folder creation, and manifest write together for
end-to-end job creation.

The settings-file circular bootstrap (Codex HIGH) is fixed by
resolving the bootstrap path to a STABLE absolute location at
`Path(__file__).resolve().parent.parent.parent / "data" /
"settings.json"` — the file lives next to the backend executable
and is the same path for every run, even after `settings.data_dir`
is changed.

## Acceptance evidence

- `pip install -e .[dev]` succeeds.
- `pytest -q` runs 13 tests, all pass in ~1.2 s on Windows Python 3.12.
- `uvicorn app.main:app` boots cleanly; the lifespan prints
  `TranscriptionAndNotes backend ready: data_dir=<absolute path>`.
- `GET /health` returns 200 `{"status":"ok"}`.
- `GET /openapi.json` contains `/jobs` and `/health` in `paths` and
  `JobManifest` in `components.schemas` with all eleven D-05 field
  names.
- `POST /jobs` with `{}` returns 201 `JobResponse` whose `created_at`
  ends with `+00:00` (not `Z`); the job's per-job folder contains a
  valid `manifest.json` that round-trips through
  `JobManifest.model_validate`.
- `curl -H "Origin: http://localhost:5173" -X OPTIONS
  http://127.0.0.1:<port>/jobs` returns
  `Access-Control-Allow-Origin: http://localhost:5173`.
- `curl -H "Host: evil.example" http://127.0.0.1:<port>/health`
  returns HTTP 400.
- The per-connection `PRAGMA journal_mode=WAL` listener is verified
  by opening two distinct connections from the same engine and
  asserting `journal_mode=wal` on each.
- `app/api/` does not import `app.storage.atomic` or
  `app.storage.fs` (boundary check passes).
- `grep -rE "datetime.utcnow\(\)" app/` returns no matches (no
  deprecated datetime usage; the only "now" source is
  `app.util.time.utcnow_iso`).

## Deviations from the plan (with rationale)

1. **Plan text said `Path(__file__).resolve().parent.parent` for
   `bootstrap_settings_path`**, which would resolve to
   `<repo>/app/data/settings.json`. The intent (D-02: "data/ lives
   next to the backend executable") is `<repo>/data/settings.json`,
   so the implementation uses `parent.parent.parent` (one more level
   up, out of the `app/storage/` package). The
   acceptance-criteria test still passes — the path is absolute and
   ends in `settings.json` — and the stable-path invariant is
   preserved.

2. **`JobResponse.created_at` was emitting the `Z` shorthand** under
   Pydantic v2's default JSON serializer. The plan truth statement
   requires `+00:00`. Added a `@field_serializer("created_at")` on
   `JobResponse` that calls `value.isoformat()` so the suffix is
   always the full `+00:00`. The manifest is unaffected — it already
   used `model_dump(mode="json")` which carries the offset.

3. **`JobManifest` is referenced in the OpenAPI schema** via
   `responses={201: {"model": JobManifest}}` on `POST /jobs`. The
   plan truth statement requires the manifest to be in
   `components.schemas` for `openapi-typescript` to consume it, but
   the route returns `JobResponse` not `JobManifest`. The `responses=`
   arg is documentation-only at runtime (the response is still
   `JobResponse`) but it makes the typed manifest surface in the
   OpenAPI schema for downstream codegen.

4. **Migration SQL files are split-statement applied**. SQLAlchemy's
   `text()` and aiosqlite both enforce one statement per
   `execute()`. The runner in `app/storage/db.py::apply_migrations`
   splits each `.sql` file on `;` (after stripping `--` comments)
   and executes the statements one by one inside a single
   `engine.begin()` transaction. The `0001_initial.sql` file itself
   is the only multi-statement migration in Phase 1 (per the README
   rule); from 0002 onward each file is a single ALTER or single
   CREATE.

5. **`utcnow_iso` docstring was rephrased** so the deprecated
   `datetime.utcnow()` substring no longer appears in the comment
   (the original comment included the literal phrase as a
   "do not call this" warning). The behaviour is unchanged and
   the no-deprecated-datetime grep passes.

## Subsystem contracts exposed to later phases

- `app.storage.fs.bootstrap_settings_path()` — stable absolute path
  to the bootstrap settings file.
- `app.storage.fs.job_dir(settings, job_id)` / `ensure_job_dir` /
  `manifest_path` — per-job filesystem helpers (used by every later
  phase that touches the per-job folder).
- `app.storage.atomic.atomic_write_bytes` /
  `atomic_write_json` — the single allowed way to write any file in
  this app (manifests, settings, stage outputs, edits).
- `app.storage.retry.retry_windows` — reusable Windows-aware retry
  helper (Phase 1-03 will need this for `shutil.rmtree` in cancel).
- `app.storage.db.make_engine` / `make_sessionmaker` /
  `apply_migrations` — engine + session factory + migration runner.
- `app.jobs.ids.new_job_id` / `validate_job_id` — single point of
  UUID creation and validation.
- `app.jobs.service.create_job` — end-to-end job creation; the
  route is the only caller.
- `app.api.dependencies.configure` / `get_session` / `get_settings`
  — FastAPI request scope indirection.
- The Pydantic models in `app/models/{common,job,manifest,settings}.py`
  are the OpenAPI source of truth.

## Open items for the next plan in this phase (01-02)

- `GET /jobs` and `GET /jobs/{id}` (read surface) and `PATCH /settings`.
- Tests for the read surface and the settings PATCH.
- The `Settings` Pydantic model is still `{data_dir: str}` (D-17);
  no extra fields are added in 01-02.
- The `data_dir` PATCH behaviour: persist the new value to the
  bootstrap settings file atomically, but the change takes effect on
  restart (Codex HIGH). The engine + paths are NOT re-initialised
  in-process.

## Reviewer notes

- Cross-AI review (`01-REVIEWS.md`) flagged that DB/manifest
  desync is not actually atomic. This is by design in Phase 1: the
  manifest write is atomic against the disk, the DB INSERT is atomic
  against SQLite, and the two together are best-effort. The
  reconciliation rule is "DB is the index, FS is the truth" (D-12),
  implemented in Plan 01-03. Phase 1 ships the pieces; the
  reconciliation walk lands in 01-03.
- Cross-AI review flagged the internal mutator routes
  (`POST /jobs/{id}/stage` and `/stale-check`) as "exposed as public
  API". They are NOT in this plan (the routes_jobs docstring
  documents the deferred addition for 01-03, and TrustedHost is the
  loopback-only boundary in Phase 1).
