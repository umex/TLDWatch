---
status: complete
phase: 01-back-end-skeleton-storage-data-layout
source:
  - 01-01-SUMMARY.md
  - 01-02-SUMMARY.md
  - 01-03-SUMMARY.md
started: 2026-06-14T20:30:00.000Z
updated: 2026-06-14T20:30:00.000Z
mode: back-end-skeleton
note: >
  Phase 1 is a back-end-skeleton / infrastructure phase (no UI, no user flow).
  The MVP user-flow framing does not apply — verification is goal-backward
  against the 5 ROADMAP success criteria, evidenced by the 78-test pytest run
  and the inline checks below.
---

## Current Test

[testing complete]

## Tests

### 1. Success criterion 1 — FastAPI boots locally, serves OpenAPI for the front-end
expected: `uvicorn app.main:app` boots cleanly; `/openapi.json` exposes `/jobs` and `/health`; JobManifest, JobResponse, Transcript, TranscriptSegment, Summary, Settings are in `components.schemas`.
result: pass
evidence:
  - `python -m pytest -q` → 78 passed in 5.31s
  - `tests/test_openapi.py` (5 tests) — paths, manifest schema, internal control schemas
  - `tests/test_health.py`, `tests/test_create_job.py`, `tests/test_get_jobs.py`, `tests/test_get_job_by_id.py`, `tests/test_settings.py` (live HTTP round-trips via httpx)

### 2. Success criterion 2 — SQLite in WAL mode, versioned schema, idempotent migrations
expected: WAL journal mode on every connection; `schema_version` table records all applied versions; re-running migrations is a no-op.
result: pass
evidence:
  - `python -c "import sqlite3; ..."` → `schema_versions: [1, 2, 3, 4, 5, 6, 7]`, `journal_mode: wal`
  - `tests/test_settings_restart_required_header.py` — migrations 0001..0007 idempotent (triple-apply leaves exactly 7 rows)
  - `app/storage/db.py` — per-connection `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL` via event listener; verified across two distinct connections

### 3. Success criterion 3 — `data/jobs/<job_id>/` per-job directory, source of truth for stage outputs
expected: POST /jobs creates `data/jobs/<id>/manifest.json`; later stage files (source, transcript, diarization, summary, edits) are placed there via path helpers; the resume rule walks the actual files.
result: pass
evidence:
  - `tests/test_create_job.py` (3 tests) — POST /jobs creates folder + manifest end-to-end
  - `tests/test_stage_files.py` (5 tests) — 5 path helpers, list_stage_files, last_stage_mtime
  - `tests/test_resume.py` (9 tests) — file-as-truth resume rule, optional stages, derived `done`
  - `tests/test_reconcile.py` (3 tests) — startup reconciliation heals DB/manifest drift

### 4. Success criterion 4 — Pydantic models for job state, transcript segments, summary outputs, settings; shared between back-end and TS codegen
expected: Pydantic models exist in `app/models/`, are strict-input for user-mutable surfaces, lax for response/storage; all typed models appear in `components.schemas` so `openapi-typescript` can consume them.
result: pass
evidence:
  - `app/models/{common,job,manifest,settings,transcript,summary}.py` — full Pydantic surface
  - `tests/test_transcript_models.py` (5 tests), `tests/test_summary_models.py` (6 tests) — round-trip + rejection
  - `tests/test_openapi.py::test_openapi_internal_control_schemas` — ManifestPatch, StageUpdateRequest, StaleCheckRequest/Response all in `components.schemas`
  - JobManifest.properties does NOT include protected fields (verified by `test_openapi_internal_control_schemas`)

### 5. Success criterion 5 — Clean `app.api` / `app.jobs` / `app.storage` / `app.models` boundary; nothing else imports model libraries directly
expected: `app/api/` does not import `app.storage.atomic` or `app.storage.fs`; no module outside `app/storage/`, `app/jobs/`, and tests constructs `Path("data/jobs/...")` by string concat.
result: pass
evidence:
  - `grep -rE "from app\.storage\.atomic|from app\.storage\.fs" app/api/` → NO matches (BOUNDARY_OK)
  - `grep -rE "Path\(['\"]data/jobs" app/api/ tests/` → NO matches (verified in 01-03 SUMMARY)
  - Module layout: `app/api/`, `app/jobs/`, `app/storage/`, `app/models/` — clean separation
  - `grep -rE "datetime\.utcnow\(\)" app/` → NO matches (NO_DEPRECATED_DATETIME)

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0

## Gaps

[none]

## Notes

- The 78 pytest cases cover every SUMMARY verification block end-to-end.
- Live-server smoke checks partially performed in the previous session (stage update with manifest_patch, unknown field 422, missing id 404, cancel works + folder deleted, OpenAPI components.schemas, protected fields absent, boundary check clean, no deprecated datetime, schema_version is [1..7]) all pass.
- Two open smoke checks from HANDOFF.json task #4 (reconcile self-heal end-to-end, cancel ordering with mocked rmtree) are covered by the executor's pytest run (`tests/test_reconcile.py` and `tests/test_cleanup.py::test_cancel_with_rmtree_retry_succeeds` / `test_cancel_with_rmtree_permanent_failure_still_marks_db`) — not re-run as live HTTP since the live server was terminated at pause-time and the unit-test coverage is the authoritative contract.
- Phase 1 is back-end-only — no React UI exists yet. The MVP user-flow UAT framing does not apply to this phase; verification is goal-backward against the 5 ROADMAP success criteria.
