---
phase: 01-back-end-skeleton-storage-data-layout
plan: 4
subsystem: backend
tags: [pydantic-v2, fastapi, sqlalchemy-async, sqlite-wal, manifest-first, restart-only-settings]

# Dependency graph
requires:
  - phase: 01-back-end-skeleton-storage-data-layout
    provides: Phase 1 plans 01-01..01-03 baseline (FastAPI app, settings, storage, jobs, manifest, reconcile, resume)
provides:
  - Restart-only PATCH /settings with pending slot + apply_pending on boot
  - POST /jobs 201 OpenAPI response fixed (JobResponse, not JobManifest)
  - Stage-to-status projection via stage_to_status() helper; status + full metadata projected to DB on every update_stage
  - reconcile_all projects full state (status + language + duration_s + summary_kinds + source_*) on boot
  - create_job orphan-row compensation (DELETE FROM jobs on folder/manifest failure)
  - Pydantic-validated stage files (Transcript, Diarization, Summary) in parse_stage_file
  - Zero-byte source.* rejection
  - mark_stale status-aware gate (skip done / failed / cancelled)
  - UpdateSettingsRequest.data_dir strict path validation (non-optional + path validator)
  - Migration runner records version on the all-duplicate-column path
affects: [all Phase 2+ plans; openapi-typescript consumer in Phase 5; any consumer of /settings or /jobs/{id}]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; pydantic v2, fastapi, sqlalchemy 2.0 async, aiosqlite all existing
  patterns:
    - "Restart-only settings via pending-slot in on-disk JSON, applied in lifespan on next boot"
    - "stage_to_status() as the single source of truth for stage->status mapping"
    - "write-manifest-first / commit-DB-last ordering with full projection in one UPDATE"
    - "Pydantic model_cls keyword arg in parse_stage_file for typed file-as-truth validation"

key-files:
  created:
    - app/models/diarization.py
    - tests/test_wal.py
    - tests/test_migration_idempotency.py
    - tests/test_data_dir_validation.py
    - tests/test_post_jobs_201_response.py
    - tests/test_stage_to_status.py
  modified:
    - app/main.py
    - app/api/routes_jobs.py
    - app/api/routes_settings.py
    - app/settings/service.py
    - app/jobs/service.py
    - app/jobs/manifest.py
    - app/jobs/reconcile.py
    - app/jobs/resume.py
    - app/jobs/cleanup.py
    - app/models/settings.py
    - app/storage/db.py
    - tests/test_cleanup.py
    - tests/test_resume.py
    - tests/test_reconcile.py
    - tests/test_settings.py
    - tests/test_settings_restart_required_header.py
    - tests/test_manifest_patch.py
    - tests/test_create_job.py
    - tests/test_openapi.py
    - tests/test_manifest_helpers.py

key-decisions:
  - "PATCH /settings persists data_dir change under a `pending` key; the in-memory state is not swapped until the next boot (or apply_pending()). The X-Restart-Required: true header remains the explicit signal."
  - "stage_to_status() handles only 'active processing' statuses (queued/ingesting/transcribing/diarizing/summarizing/done); terminal statuses (failed/cancelled) are set by mark_failed / cancel_job and never re-derived from current_stage."
  - "UpdateSettingsRequest.data_dir is now required (not Optional); an empty body returns 422. The legacy test_empty_patch_omits_header was renamed to test_empty_patch_returns_422 to match."
  - "parse_stage_file takes a model_cls= keyword; missing or unknown keyword falls back to the legacy json.loads check. The zero-byte size check sits at the top so source.* and JSON branches both reject empty files."
  - "apply_migrations counts duplicate-column errors per file; if every statement in a file is a duplicate-column error, the version row is recorded (recovery from a partial prior run). Partial duplicates raise RuntimeError so a half-applied state is loud."
  - "JobManifest import in app/api/routes_jobs.py is retained (deviation): the plan said to remove it but the file still references it in post_stage(response_model=JobManifest). Removing would break the file."

patterns-established:
  - "Restart-only config: pending slot in on-disk JSON, apply_pending() in lifespan, X-Restart-Required header as the API signal"
  - "Manifest-first projection: update_stage writes the full metadata set (status + language + duration_s + source_* + summary_kinds_json) in a single UPDATE; reconcile_all heals any drift using the same set"
  - "Typed file-as-truth: stage files are validated against the typed model (Transcript / Diarization / Summary); unparseable files are treated as 'stage not complete' so the resume rule re-runs the stage"

requirements-completed: [HW-01]

# Metrics
duration: ~50min
completed: 2026-06-15
---

# Phase 1 Plan 4: Gap closure (5 HIGH + 3 MEDIUM Codex follow-ups) Summary

**Restart-only settings + status/metadata projection + typed file validation: closes every Codex review finding and turns Phase 1 contracts into truthful execution.**

## Performance

- **Duration:** ~50 min (continuation agent; tasks T8/T9/T10 + verification + summary)
- **Completed:** 2026-06-15
- **Tasks:** 10/10 (T1 through T10)
- **Files modified:** 22 (11 source + 11 test)

## Accomplishments

- **H1 (restart-only settings)** — `PATCH /settings` no longer mutates the in-memory state when `data_dir` changes. The new value is persisted to a `pending` slot in the on-disk JSON; the lifespan calls `apply_pending()` after the engine builds, and a follow-up `apply_pending()` clears the slot. `X-Restart-Required: true` remains the signal. Chained restarts work: each PATCH writes a fresh `pending` slot; the next boot applies it and drops the slot.
- **H2 (OpenAPI 201)** — `POST /jobs` 201 now correctly references `JobResponse` (via FastAPI's automatic `response_model`); the misleading `responses={201: {"model": JobManifest}}` block was dropped. `JobManifest` is still in `components.schemas` (via `_EXTRA_OPENAPI_MODELS`) for the openapi-typescript consumer in Phase 5.
- **H3 + H4 (status + metadata projection)** — `update_stage` writes `status` AND the full metadata set (`language`, `duration_s`, `source_*`, `summary_kinds_json`) in the same SQL UPDATE. `stage_to_status(stage, manifest)` is the single source of truth for the stage-to-status mapping. `reconcile_all` projects the same columns on boot, so any drift between manifest and DB is healed.
- **H5 (orphan compensation)** — `create_job` wraps `ensure_job_dir` + `write_manifest` in `try/except`; on failure the DB row is DELETED before the exception propagates. A partial orphan (DB row, no folder or no manifest) is now impossible.
- **M1 + M2 (typed file validation + zero-byte rejection)** — `parse_stage_file(path, *, model_cls=...)` validates `transcript.json` against `Transcript`, `diarization.json` against `Diarization`, and `summary-<kind>.json` against `Summary`. Zero-byte `source.*` is rejected. Unparseable / schema-invalid files count as "stage not complete" so the resume rule re-runs them.
- **M3 (status-aware stale check)** — `mark_stale` first `SELECT status FROM jobs WHERE id = :id`; if the row is missing or status is terminal (`done` / `failed` / `cancelled`), it returns `(False, False)` without touching the DB or filesystem.
- **T8 (path validation)** — `UpdateSettingsRequest.data_dir` is now non-optional with a `@model_validator(mode="after")` that rejects empty string, relative paths, and existing file paths. Empty PATCH body returns 422.
- **T9 (migration idempotency)** — `apply_migrations` counts duplicate-column errors per file; if every statement in a file is a duplicate-column error, the version row is recorded (recovery from a partial prior run). Partial duplicates raise `RuntimeError`.
- **T10 (tests)** — 34 new tests across 5 new files (`test_wal.py`, `test_migration_idempotency.py`, `test_data_dir_validation.py`, `test_post_jobs_201_response.py`, `test_stage_to_status.py`) and additions to 9 existing test files. Full suite: 113/113 pass.

## Task Commits

Each task was committed atomically with the format `fix(01-04): <task-id> <one-line summary>`:

1. **Task 1: H2 — POST /jobs 201 OpenAPI response** — `608b784`
2. **Task 2: H1 — restart-only settings semantics** — `500066c`
3. **Task 3: H5 — create_job orphan-row compensation** — `f14bcab`
4. **Task 4: H3+H4 — project status + metadata to DB on every stage transition** — `8929941`
5. **Task 5: H4 part 2 — reconcile projects full state on boot** — `211a3bc`
6. **Task 6: M1+M2 — Pydantic-validate stage files; reject zero-byte source** — `390a070`
7. **Task 7: M3 — status-aware stale check, skip terminal rows** — `ebd2668`
8. **Task 8 — strengthen UpdateSettingsRequest.data_dir validation** — `c00599b`
9. **Task 9 — migration runner records version on duplicate-column path** — `14e85cb`
10. **Task 10 — new tests + test modifications (34 new tests)** — `d778e49`

## Files Created/Modified

- `app/main.py` — Added `JobManifest` to `_EXTRA_OPENAPI_MODELS`; lifespan calls `apply_pending()` after the engine builds.
- `app/api/routes_jobs.py` — Dropped the `responses={201: {"model": JobManifest}}` block. (Note: `JobManifest` import retained — see Deviations.)
- `app/api/routes_settings.py` — `patch_settings` returns the value returned by `apply_update` (boot value when restart-required, new value otherwise).
- `app/settings/service.py` — Added `_PENDING_KEY`, `_State.pending`, `_read_disk_dict`, `_write_disk_dict`, `apply_pending()`. `load_settings_from_disk` now returns `(active, pending)`. `apply_update` persists to `pending` slot when restart-required and leaves `_State.settings` unchanged.
- `app/jobs/service.py` — `create_job` wraps folder/manifest step in try/except; on failure, DELETEs the DB row and re-raises.
- `app/jobs/manifest.py` — Added `stage_to_status()`, `_latest_ts()`. `update_stage` UPDATE now writes 9 columns (status + current_stage + stage_timestamps_json + updated_at + source_type + source_path + source_sha256 + duration_s + language + summary_kinds_json).
- `app/jobs/reconcile.py` — `reconcile_all` SELECT reads 9 columns, UPDATE writes 9 + `updated_at`; uses `stage_to_status` and `_latest_ts`.
- `app/jobs/resume.py` — `parse_stage_file(path, *, model_cls=None)` validates against typed model; zero-byte rejected at the top.
- `app/jobs/cleanup.py` — `_TERMINAL_STATUSES = frozenset({"done","failed","cancelled"})`; `mark_stale` does a SELECT-status gate before the mtime check.
- `app/models/diarization.py` — NEW: `Diarization(BaseModel)` for typed `diarization.json` validation.
- `app/models/settings.py` — `UpdateSettingsRequest.data_dir: str` (required); `model_validator(mode="after")` rejects empty / relative / file paths.
- `app/storage/db.py` — `apply_migrations` tracks `stmt_total` and `stmt_errors`; all-duplicate path records the version row; partial duplicates re-raise.
- Tests: created 5 new files; added 34 new tests across 9 modified files.

## Verification (6 steps from the plan, all green)

1. `pytest -q` — **113 passed in 6.11s**
2. `uvicorn app.main:app --port 8770` boots; `GET /health` returns `{"status":"ok"}`. Live round-trip:
   - `POST /jobs` (empty body) returns 201 with `id` and `status="queued"`. SELECT from `data/app.db` shows `status=queued`. **H3 initial-status sanity confirmed.**
   - `POST /jobs/{id}/stage` with `{"stage":"ingested","manifest_patch":{"source_type":"local","language":"en","duration_s":42.5,"summary_kinds":["meeting"]}}` returns 200. SELECT shows `('ingesting', 'ingested', 'en', 42.5, '["meeting"]')`. **H3 + H4 confirmed.**
   - `GET /jobs/{id}` returns a `JobResponse` with `language="en"`, `duration_s=42.5`, `summary_kinds=["meeting"]`. **H4 GET path confirmed.**
   - `PATCH /settings` with `{"data_dir":"C:/tmp/foo"}` returns 200 with `X-Restart-Required: true`. `GET /settings` immediately after returns the BOOT data_dir (not `C:/tmp/foo`). **H1 in-memory not swapped confirmed.**
3. OpenAPI check: `GET /openapi.json` shows `paths["/jobs"].post.responses["201"].content["application/json"].schema` references `JobResponse`; `JobManifest` is in `components.schemas`. **H2 confirmed.**
4. Settings validation: `PATCH /settings` with `{"data_dir":""}`, `{"data_dir":null}`, `{"data_dir":"relative/path"}`, and `{"data_dir":"<existing-file>"}` all return 422. **T8 confirmed.**
5. `pytest -q` — **113 passed in 6.11s**
6. Final commit recorded below.

## Decisions Made

- **T1 deviation:** `JobManifest` import in `app/api/routes_jobs.py` was retained even though the plan said to remove it. The file still uses it in `post_stage(response_model=JobManifest)`. Removing the import would break the file. Documented as a deviation.
- **T8 contract change:** `UpdateSettingsRequest.data_dir` is now required, not optional. The existing `test_empty_patch_omits_header` was renamed to `test_empty_patch_returns_422` to match the new contract. A new `test_same_data_dir_omits_header` covers the "PATCH with same value, no restart header" case.
- **T6 test updates:** 6 sites in `tests/test_resume.py` were updated from `json.dumps({})` to valid `Transcript` / `Summary` payloads to match the stricter Pydantic validation. This was anticipated by the plan ("Existing test updates required for compatibility (W1 + W8)").
- **T10 `test_create_job_compensates_*`:** The plan's acceptance script calls `create_job` directly (not through HTTP). The tests use the same direct-call pattern, since `ASGITransport` re-raises the `OSError` and a 500 from the route would not prove the compensation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] T1: kept `JobManifest` import in `routes_jobs.py`**
- **Found during:** Task 1 (H2 — POST /jobs 201 OpenAPI response)
- **Issue:** The plan said to remove the `from app.models.manifest import JobManifest` import at the top of `app/api/routes_jobs.py`, but the file still uses it as `post_stage(response_model=JobManifest)`. Removing the import would break the route (NameError).
- **Fix:** Kept the import. The OpenAPI fix was just to drop the `responses={201: {"model": JobManifest}}` block, not the import. Documented in the T1 commit message.
- **Files modified:** `app/api/routes_jobs.py`
- **Committed in:** `608b784`

**2. [Rule 1 - Bug] T8: renamed `test_empty_patch_omits_header` to `test_empty_patch_returns_422`**
- **Found during:** Task 8 (strengthen `UpdateSettingsRequest.data_dir` validation)
- **Issue:** The existing test PATCHes an empty body and asserts 200 with no X-Restart-Required header. After making `data_dir` non-optional, empty body returns 422 (was 200). The test's intent was "an empty PATCH is not restart-required", but the new contract is "an empty PATCH is rejected outright".
- **Fix:** Renamed to `test_empty_patch_returns_422` and asserts 422. Added `test_same_data_dir_omits_header` to cover the "no restart required" case (PATCH with the same data_dir as the boot value).
- **Files modified:** `tests/test_settings_restart_required_header.py`
- **Committed in:** `c00599b`

**3. [Rule 1 - Bug] T6: 6 sites in `test_resume.py` updated to write valid `Transcript` / `Summary` payloads**
- **Found during:** Task 6 (Pydantic-validate stage files)
- **Issue:** The plan anticipated this — `parse_stage_file` now validates against the typed model, so `json.dumps({})` no longer counts as a complete `transcript.json` / `summary-meeting.json`.
- **Fix:** Updated 6 sites to write valid payloads (e.g., `{"job_id": j, "segments": []}` for `Transcript`, `{"job_id": j, "kind": "meeting", "created_at": "2026-06-15T00:00:00+00:00", "sections": {}}` for `Summary`).
- **Files modified:** `tests/test_resume.py`
- **Committed in:** `390a070`

**4. [Rule 1 - Bug] T10: `test_create_job_compensates_*` call `create_job` directly, not through HTTP**
- **Found during:** Task 10 (new tests)
- **Issue:** The original test design was `await client.post("/jobs", json={})` and assert the DB row count. But `ASGITransport` re-raises the `OSError` from the route, so the call never returns — pytest sees the `OSError` and the assertion runs only if the route catches it.
- **Fix:** Call `jobs_service.create_job(session, settings)` directly and `pytest.raises(OSError)`. This matches the plan's T3 acceptance script, which also calls `create_job` directly.
- **Files modified:** `tests/test_create_job.py`
- **Committed in:** `d778e49`

**5. [Rule 1 - Bug] T10: `Settings(data_dir=td)` -> `Settings(data_dir=str(td))`**
- **Found during:** Task 10 (`test_apply_migrations_recovers_missing_version_row`)
- **Issue:** `Settings` is strict (Pydantic v2 strict mode); a `Path` object is rejected.
- **Fix:** Coerce to `str` before constructing `Settings`.
- **Files modified:** `tests/test_migration_idempotency.py`
- **Committed in:** `d778e49`

**6. [Rule 1 - Bug] T10: `test_mark_stale_missing_job_returns_false_false` now uses the `client` fixture**
- **Found during:** Task 10
- **Issue:** The test was originally written without the `client` fixture, so the lifespan never ran and the session factory was never configured. The assertion `sf is not None` failed.
- **Fix:** Added the `client: httpx.AsyncClient` parameter so the `app_under_test` fixture drives the lifespan.
- **Files modified:** `tests/test_cleanup.py`
- **Committed in:** `d778e49`

---

**Total deviations:** 6 auto-fixed (5 Rule 1 bugs, 1 Rule 3 blocking)
**Impact on plan:** All auto-fixes were necessary for the plan's acceptance criteria. No scope creep — T1 deviation is the only one that touched a non-T8 contract, and it was the minimum change required to keep the file importing.

## Issues Encountered

- The 79-test pre-plan baseline (Phase 1 plans 01-01..01-03) is now 113 tests. No regressions — every pre-plan test still passes.
- The continuation agent picked up the conversation at the end of T8 (T1-T7 + T8 commit pending) and completed T8's test fix, T9, T10, verification, and this summary. The git log shows T1-T10 as 10 atomic commits on `master`:
  ```
  d778e49 fix(01-04): T10 add 34 new tests covering all gap-closure truths
  14e85cb fix(01-04): T9 migration runner records version on duplicate-column path
  c00599b fix(01-04): T8 strengthen UpdateSettingsRequest.data_dir validation
  ebd2668 fix(01-04): T7 M3 status-aware stale check - skip terminal rows
  390a070 fix(01-04): T6 M1+M2 Pydantic-validate stage files; reject zero-byte source
  211a3bc fix(01-04): T5 H4 part 2 - reconcile projects full state on boot
  8929941 fix(01-04): T4 H3+H4 project status + metadata to DB on every stage transition
  f14bcab fix(01-04): T3 H5 compensate create_job orphan rows on folder/manifest failure
  500066c fix(01-04): T2 H1 defer data_dir change to restart via pending slot
  608b784 fix(01-04): T1 H2 fix POST /jobs 201 response to JobResponse
  ```

## Self-Check: PASSED

- All 10 task commits (`608b784`, `500066c`, `f14bcab`, `8929941`, `211a3bc`, `390a070`, `ebd2668`, `c00599b`, `14e85cb`, `d778e49`) are in the git log.
- All 6 newly created files (`app/models/diarization.py`, `tests/test_wal.py`, `tests/test_migration_idempotency.py`, `tests/test_data_dir_validation.py`, `tests/test_post_jobs_201_response.py`, `tests/test_stage_to_status.py`) are present on disk.
- 113/113 pytest cases pass.
- 6-step Verification section from the plan is green (live server, curl, OpenAPI, settings validation, final pytest).

## User Setup Required

None - no external service configuration required. The data_dir is configured via the `data/settings.json` file (the test fixture already exercises this end-to-end).

## Next Phase Readiness

- All Codex review findings (5 HIGH + 3 MEDIUM) are closed.
- Phase 1 contracts are truthful in real execution:
  - `PATCH /settings` with `data_dir` change: pending slot + header signal + in-memory unchanged.
  - `POST /jobs` 201: returns `JobResponse` (id, not job_id).
  - `update_stage` projects status + full metadata to DB; reconcile_all heals drift.
  - `create_job` cannot leave an orphan row.
  - Stage files are typed; unparseable files are re-run, not silently accepted.
  - `mark_stale` is a no-op on terminal rows.
  - Migration runner is idempotent across triple-apply and recovers from a missing version row.
- Phase 2+ plans can build on the same models (`JobManifest`, `ManifestPatch`, `Diarization`, `Transcript`, `Summary`, `JobResponse`, `Settings`, `UpdateSettingsRequest`) and the same helpers (`stage_to_status`, `update_stage`, `reconcile_all`, `infer_resume_point`, `parse_stage_file`).
- The 6-step Verification section from the plan is green; the plan is complete and Phase 1 is ready for verification by the user / reviewer.

---
*Phase: 01-back-end-skeleton-storage-data-layout*
*Completed: 2026-06-15*
