---
phase: 01-back-end-skeleton-storage-data-layout
plan: 01-02
subsystem: backend
provides:
  - full_pydantic_surface
  - read_endpoints_jobs
  - settings_service_with_restart_header
  - per_statement_migration_guard
  - seven_column_jobs_schema
  - openapi_components_schemas
requires: [01-01]
affects: [phase-2-gpu, phase-3-stt, phase-4-orchestrator, phase-5-frontend, phase-7-diarization, phase-8-summarization, phase-9-editor, phase-10-settings-panel]
tech-stack:
  added: []
  pinned: "lower bounds only (>=) - no lockfile in Phase 1"
key-files:
  created:
    - app/models/transcript.py
    - app/models/summary.py
    - app/settings/__init__.py
    - app/settings/service.py
    - app/api/routes_settings.py
    - migrations/0002_add_source_sha256.sql
    - migrations/0003_add_duration_s.sql
    - migrations/0004_add_language.sql
    - migrations/0005_add_summary_kinds_json.sql
    - migrations/0006_add_updated_at.sql
    - migrations/0007_add_stage_timestamps_json.sql
    - tests/test_transcript_models.py
    - tests/test_summary_models.py
    - tests/test_get_jobs.py
    - tests/test_get_job_by_id.py
    - tests/test_settings.py
    - tests/test_settings_restart_required_header.py
  modified:
    - app/models/settings.py
    - app/models/job.py
    - app/api/routes_jobs.py
    - app/api/dependencies.py
    - app/jobs/service.py
    - app/storage/db.py
    - app/main.py
    - migrations/README.md
decisions:
  - id: D-15-strict-input
    summary: "UpdateSettingsRequest is strict (ConfigDict(strict=True, extra='forbid')); int and unknown fields are 422 (D-15 PITFALLS pitfall 7)"
  - id: D-17-only-data-dir
    summary: "Settings stays at data_dir: str only (D-17); future phases add gpu_backend, hf_token, quality_preset"
  - id: per-statement-guard
    summary: "Migration runner catches SQLite 'duplicate column' OperationalError on ALTER TABLE ADD COLUMN and treats it as a no-op (continues to the next statement, records the version). Replaces the per-file _guards.py approach that was rejected for partial-application fragility (Codex HIGH)."
  - id: restart-required-header
    summary: "PATCH /settings emits X-Restart-Required: true on the response when data_dir actually changed. The change is persisted at PATCH time; engine, session factory, and settings-file path are NOT hot-swapped (Codex HIGH item 9, item 11)."
  - id: settings-state-tracks-path
    summary: "app.settings.service._State tracks the path settings were loaded from, so apply_update writes back to the same file (matters for tests that load from a temp path; production always loads from the bootstrap path)."
  - id: in-memory-after-disk
    summary: "apply_update writes the new Settings to disk first, then updates the in-memory state. A disk-write failure leaves the in-memory state untouched and re-raises (Codex HIGH item 16)."
  - id: openapi-components-schemas
    summary: "Patch app.openapi in main.py to inject TranscriptSegment, Transcript, Summary into components.schemas; Pydantic only registers models reachable from a route handler, but the Phase 5 openapi-typescript codegen needs these storage models available now."
  - id: list-pagination-cap
    summary: "list_jobs silently caps limit at 200 and clamps offset to >= 0 (Codex MEDIUM). LIST_LIMIT_CAP=200, LIST_LIMIT_DEFAULT=50 exported from app.jobs.service."
test-coverage:
  total: 37
  passing: 37
  new_in_this_plan: 24
  names:
    # 01-01 carry-over (13)
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
    # 01-02 new (24)
    - test_roundtrip_transcript_segment
    - test_transcript_segment_with_speaker_and_confidence
    - test_transcript_default_segments_is_empty
    - test_transcript_roundtrip
    - test_transcript_segment_rejects_bad_types
    - test_roundtrip_meeting[meeting]
    - test_roundtrip_meeting[investment]
    - test_roundtrip_meeting[concept]
    - test_roundtrip_meeting[quick_recap]
    - test_summary_unknown_kind_rejected
    - test_summary_kind_literal_args
    - test_summary_default_sections_is_empty_dict
    - test_list_orders_newest_first
    - test_status_filter_returns_matching
    - test_limit_query
    - test_limit_cap_200
    - test_get_returns_job
    - test_get_missing_returns_404
    - test_get_settings
    - test_patch_settings_persists
    - test_patch_settings_rejects_int
    - test_patch_settings_rejects_unknown_field
    - test_data_dir_change_sets_header
    - test_empty_patch_omits_header
verification:
  pip_install: "pip install -e .[dev] succeeds"
  pytest: "37 passed in ~1.8s"
  uvicorn_boot: "uvicorn app.main:app boots; lifespan prints 'TranscriptionAndNotes backend ready: data_dir=data'"
  settings_get: "GET /settings returns {'data_dir':'data'}"
  settings_patch_data_dir: "PATCH /settings with {data_dir: 'C:/tmp/foo'} returns 200 with X-Restart-Required: true; on-disk settings.json contains the new value"
  settings_patch_empty: "PATCH /settings with {} returns 200 WITHOUT X-Restart-Required"
  settings_patch_int: "PATCH /settings with {data_dir: 123} returns 422"
  settings_patch_unknown: "PATCH /settings with {unknown_field: 'x'} returns 422"
  post_jobs: "POST /jobs with {} returns 201 JobResponse with the new fields (source_path, source_sha256, duration_s, language, summary_kinds, updated_at, error) all null/empty by default"
  get_jobs: "GET /jobs returns a list of JobResponse, newest-first"
  get_jobs_status: "GET /jobs?status=queued returns only queued jobs"
  get_jobs_pagination: "GET /jobs?limit=1 returns one job; GET /jobs?limit=500 returns all (silent cap at 200)"
  get_job_by_id: "GET /jobs/{id} returns the matching JobResponse; GET /jobs/missing returns 404 with {detail: 'job not found'}"
  openapi_schemas: "components.schemas includes TranscriptSegment, Transcript, Summary, Settings, UpdateSettingsRequest, JobManifest, JobResponse"
  migrations_idempotency: "apply_migrations called 3x on a fresh DB leaves schema_version = [1,2,3,4,5,6,7]; triple-apply with second run on an existing DB still leaves exactly 7 rows"
  api_boundary: "grep -rE 'from app\\.storage\\.atomic|from app\\.storage\\.fs' app/api/ returns NO matches"
  no_deprecated_datetime: "grep -rE 'datetime\\.utcnow\\(\\)' app/ returns NO matches"
---

# Phase 1 Plan 2 — Full Pydantic surface + read endpoints + settings.json Pydantic model

## What landed

The full Phase 1 typed model surface is in place: `TranscriptSegment`,
`Transcript`, `Summary` (with `SummaryKind` literal of the four
template kinds), `JobResponse` (extended with the seven new
D-05-aligned read fields), `Settings` (unchanged — only `data_dir`
per D-17), and a new strict-input `UpdateSettingsRequest` for
`PATCH /settings`. All four Phase 1 endpoints are live:

- `GET /jobs` (newest-first, optional `?status=`, `?limit=`
  silently capped at 200, `?offset=`)
- `GET /jobs/{id}` (one `JobResponse`, 404 with `{"detail": "job not
  found"}` on miss)
- `GET /settings` (lax output)
- `PATCH /settings` (strict input, atomic disk write, in-memory
  state updated only after disk write succeeds, `X-Restart-Required:
  true` header on the response when `data_dir` actually changed)

The settings service lives in a new `app/settings/service.py`
module. The `app/api/dependencies.get_settings` shim delegates to
`app.settings.service.current()`; the duplicate `current_settings`
module variable is gone. The Pydantic `Settings` model remains the
source of truth (D-14) and the file is its atomic serialisation.

Migrations 0002 through 0007 each add a single column to `jobs`
(`source_sha256`, `duration_s`, `language`, `summary_kinds_json`,
`updated_at`, `stage_timestamps_json`). The runner in
`app/storage/db.py::apply_migrations` now catches the SQLite
"duplicate column" `OperationalError` on `ALTER TABLE ADD COLUMN`
and treats it as a no-op (continues to the next statement, does
NOT abort the migration), so partial application is safe. The
previous per-file `migrations/_guards.py` approach was rejected
for partial-application fragility (Codex HIGH) and is NOT
present in this repo.

A startup log WARNING is emitted by the lifespan if `data_dir`
from the on-disk file differs from the default (manual-override
signal), unchanged from 01-01.

A custom `app.openapi` hook in `app/main.py` injects the storage
models (`TranscriptSegment`, `Transcript`, `Summary`) into
`components.schemas` so downstream `openapi-typescript` consumers
in Phase 5 can pull their typed surface even before their
`/transcripts` and `/summaries` routes are added.

## Acceptance evidence

- `pip install -e .[dev]` succeeds.
- `pytest -q` runs 37 tests, all pass in ~1.8s on Windows
  Python 3.12 (13 from 01-01 + 24 from 01-02).
- `uvicorn app.main:app` boots cleanly; lifespan prints
  `TranscriptionAndNotes backend ready: data_dir=data`.
- `GET /settings` returns `{"data_dir":"data"}`.
- `POST /jobs` with `{}` returns 201 with the extended
  `JobResponse` (all new fields present, defaulting to `null` /
  `[]`).
- `GET /jobs` returns a list newest-first; `?status=queued`
  filters correctly; `?limit=1` and `?limit=500` both work
  (cap at 200 silently applied; with 2 jobs in the test
  database, the cap returns 2).
- `GET /jobs/{id}` returns the matching job; `GET /jobs/missing`
  returns 404 with `{"detail":"job not found"}`.
- `PATCH /settings` with `{"data_dir":"C:/tmp/foo"}` returns 200
  with the new value AND the header
  `x-restart-required: true`. The on-disk `data/settings.json`
  contains the new value. The in-memory `Settings` reflects the
  change for subsequent `GET /settings` calls.
- `PATCH /settings` with `{}` returns 200 WITHOUT the
  `x-restart-required` header (no fields set, no restart needed).
- `PATCH /settings` with `{"data_dir":123}` returns 422 (strict
  input rejected the int).
- `PATCH /settings` with `{"unknown_field":"x"}` returns 422
  (strict input rejected the extra key).
- `curl -sf http://127.0.0.1:8767/openapi.json` returns
  `components.schemas` containing `TranscriptSegment`,
  `Transcript`, `Summary`, `Settings`, `UpdateSettingsRequest`,
  `JobManifest`, `JobResponse`, `CreateJobRequest`,
  `StageTimestamps`, `HTTPValidationError`, `ValidationError`.
- Idempotency: `apply_migrations` called 3x on a fresh DB leaves
  exactly `schema_version = [1,2,3,4,5,6,7]` and the six new
  columns each appear exactly once. Restarting uvicorn on the
  same DB still leaves `schema_version = [1,2,3,4,5,6,7]`.
- `app/api/` does not import `app.storage.atomic` or
  `app.storage.fs` (boundary check passes).
- `grep -rE "datetime.utcnow\(\)" app/` returns no matches.
- `python -c "import sqlite3; c=sqlite3.connect('data/app.db');
  print([r[0] for r in c.execute('SELECT version FROM
  schema_version').fetchall()])"` after the live smoke test
  prints `[1, 2, 3, 4, 5, 6, 7]`.

## Deviations from the plan (with rationale)

1. **Plan said `save_settings_to_disk(None, new)` should default
   to `_default_settings_path()`** (the bootstrap path), but the
   acceptance-criteria test in the plan loads from an explicit
   `p` (a temp path) and then expects `p.read_text()` to show the
   new value. To make that test pass AND keep the production
   round-trip (lifespan loads from the bootstrap path, PATCH
   writes back to it), `app.settings.service._State` now tracks
   the path settings were loaded from. `apply_update` writes back
   to `_State.path` if set, else the bootstrap path. This is a
   net improvement: the service is now path-aware and the
   plan's stated acceptance test pattern works as written.

2. **Plan said the openapi-typescript codegen would consume
   `TranscriptSegment` and `Summary` "via openapi.json"** in
   Phase 5. Pydantic v2 only registers a model in
   `components.schemas` when it is reachable from a route
   handler. The `/transcripts` and `/summaries` routes are not
   in 01-02. To make the typed surface available now (and pass
   the success-criteria check that those schemas must appear in
   `components.schemas`), `app/main.py` patches `app.openapi` to
   inject the three storage models (`TranscriptSegment`,
   `Transcript`, `Summary`) into `components.schemas` after the
   default schema is generated. This is a small, well-scoped
   FastAPI extension; the route-reachable models
   (`Settings`, `UpdateSettingsRequest`, `JobManifest`,
   `JobResponse`, `CreateJobRequest`, `StageTimestamps`) are
   registered by FastAPI as usual.

3. **`JobResponse.updated_at` is a typed `datetime | None`**,
   not a string. The plan said `updated_at: datetime | None` so
   the type is correct, but Pydantic v2's default JSON
   serializer would emit the `Z` shorthand. Added a
   `@field_serializer("updated_at")` mirroring the existing
   `created_at` one so the offset is always the full `+00:00`
   (the `Z` shorthand would break strict ISO 8601 consumers, and
   the DB stores it as a string anyway so the round-trip is
   `datetime.fromisoformat(row.updated_at)`).

4. **The plan said `app/api/routes_settings.py` (Task 6) and
   `app/jobs/service.py` list/get (Task 5) ship in separate
   tasks.** I committed them in a single commit because the test
   suite (Task 7) requires the lifespan to import
   `app.api.routes_settings` — without it, `pytest -q` fails
   with `ModuleNotFoundError`. Combining two related tasks in
   one commit is consistent with the per-task-commit protocol
   because no test or verification step can run in between.

5. **The plan said the per-statement guard catches
   `"duplicate column"` (singular)** in the SQLite error
   message. Implemented as `if "duplicate column" in
   str(exc).lower()` so it matches both `"duplicate column
   name"` and any future wording variants. No effect on the
   acceptance test (the canonical message is "duplicate column
   name: <col>").

## Subsystem contracts exposed to later phases

- `app.models.transcript.TranscriptSegment` /
  `Transcript` — the on-disk `transcript.json` shape
  (D-05-aligned).
- `app.models.summary.Summary` /
  `app.models.summary.SummaryKind` — the on-disk
  `summary-<kind>.json` shape and the four-kind discriminator.
  Phase 8 swaps `sections: dict[str, str]` for per-kind typed
  schemas.
- `app.models.settings.UpdateSettingsRequest` — strict input
  for `PATCH /settings` (D-15).
- `app.models.job.JobResponse` (extended) — the read surface
  for jobs now carries all D-05 fields the UI needs.
- `app.jobs.service.list_jobs(status=None, limit=50, offset=0)`
  / `get_job(session, job_id)` — read paths with pagination
  cap at 200.
- `app.settings.service` — load / save / apply_update with
  in-memory state updated only after disk write succeeds.
  `apply_update` returns `(new, restart_required)` so the route
  layer can set the response header.
- `app.api.routes_settings` — `GET /settings` (lax) and
  `PATCH /settings` (strict, sets `X-Restart-Required: true`
  on `data_dir` change).
- `migrations/0002..0007_*.sql` — the seven new `jobs` columns.
  The runner's per-statement duplicate-column guard means
  re-applying any of them is a no-op.
- `app.storage.db.apply_migrations` — split-on-`;` runner that
  catches the "duplicate column" `OperationalError` and
  continues.

## Open items for the next plan in this phase (01-03)

- Internal control endpoints: `POST /jobs/{id}/stage` and
  `POST /jobs/{id}/stale-check` (Phase 1's loopback-only
  internal mutator surface; Phase 4 replaces them with
  authenticated, worker-bound routes).
- `shutil.rmtree` retry helper for cancel (Windows file locks).
- DB/manifest consistency protocol: write the manifest first,
  then update the DB (Codex HIGH + Gemini MEDIUM) — the
  rule is "DB slightly behind disk" so the resume rule
  (D-12) can rebuild the DB index from the manifest at
  startup.
- Boot-time reconciliation: scan `data/jobs/` and add missing
  DB rows (the inverse of cancel deleting the folder but
  leaving a stale row).
- `summary_kinds` is currently stored as `summary_kinds_json`
  on the row; the service layer does not yet write it. The
  field is populated by Phase 8 when summary kinds are
  chosen.
- The `Summary.sections` shape is a `dict[str, str]` placeholder
  for Phase 1; Phase 8 replaces it with per-kind typed schemas.
- `app.api.dependencies.configure(settings=None)` clears
  `app.settings.service._State.settings`; the test fixture
  relies on this. The clean-up is documented but a real
  `reset()` function would be a tidier API.
