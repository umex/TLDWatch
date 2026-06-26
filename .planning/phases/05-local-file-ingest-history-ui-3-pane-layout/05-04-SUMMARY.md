---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 04
subsystem: api, database, ui
tags: [sqlite, pydantic, fastapi, react, openapi-typescript, gap-closure]

# Dependency graph
requires:
  - phase: 05-local-file-ingest-history-ui-3-pane-layout
    provides: POST /jobs/upload streaming route + X-Filename header + HistoryRow component
provides:
  - "Additive original_filename field on JobManifest, JobResponse, and the jobs DB row"
  - "POST /jobs/upload persists X-Filename as original_filename at upload time"
  - "HistoryRow renders original_filename with basename(source_path) fallback"
affects: [05-local-file-ingest-history-ui-3-pane-layout, verifier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive nullable TEXT column projected at upload time (mirror of source_sha256 pattern from 0002)"
    - "Display-only field persisted alongside server-generated source_path (D-04 preserved)"

key-files:
  created:
    - migrations/0009_add_original_filename.sql
    - tests/test_original_filename.py
    - web/src/components/HistoryRow.test.tsx
  modified:
    - app/models/manifest.py
    - app/models/job.py
    - app/jobs/manifest.py
    - app/jobs/service.py
    - app/api/routes_jobs.py
    - web/src/api/types.ts
    - web/src/components/HistoryRow.tsx
    - tests/test_migration_idempotency.py

key-decisions:
  - "original_filename is additive + nullable + display-only; source_path still points at data/jobs/<id>/source.<ext> (D-04 unchanged)"
  - "Upload route writes original_filename to the DB row BEFORE enqueue so an immediate GET /jobs/{id} returns it; the orchestrator's update_stage('ingested') re-projects the same value idempotently"
  - "update_stage UPDATE binds original_filename so the H3+H4 manifest->DB projection invariant holds for the new column on every stage transition"
  - "original_filename is NOT on ManifestPatch (user-mutable surface); only the upload route sets it"
  - "FE types.ts edited manually (gen-types could not run -- a stale process held port 8000); next gen-types run reconciles"

patterns-established:
  - "Additive display field: nullable TEXT column + Pydantic default-None + _row_to_response projection + service.py SELECT widening -- mirror the 0002 source_sha256 rollout"

requirements-completed: [UI-01, JOB-03]

# Metrics
duration: 12min
completed: 2026-06-26
---

# Phase 5 Plan 04: Persist + render original dropped filename Summary

**Additive original_filename field end-to-end (migration 0009 -> JobManifest/JobResponse -> upload-route persistence -> HistoryRow display with basename fallback) closes UAT test-4 gap A.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-26T09:55:06Z
- **Completed:** 2026-06-26T10:07:05Z
- **Tasks:** 2
- **Files modified:** 11 (8 modified/created in plan scope + 3 deviation fixes)

## Accomplishments
- Back-end: X-Filename header now persists as `original_filename` on both the on-disk manifest and the DB row at upload time; `GET /jobs/{id}` returns it immediately.
- DB: migration 0009 adds the additive nullable TEXT column; the runner auto-discovers it on boot.
- Projection invariant preserved: `update_stage` re-projects `original_filename` on every stage transition (H3+H4), and `list_jobs` / `get_job` SELECT the new column so `_row_to_response` can read it.
- Front-end: HistoryRow shows the dropped filename, falls back to `basename(source_path)` when `original_filename` is null, and "unknown" when neither is set.
- FE types regenerated manually (additive `original_filename?: string | null` on JobResponse + JobManifest).
- TDD: RED + GREEN commits for both tasks; full back-end suite 280 passed (278 + 2 new), vitest 22 passed (19 + 3 new), tsc clean, vite build ok.

## Task Commits

Each task was committed atomically (TDD: RED test -> GREEN implementation):

1. **Task 1: Persist original_filename across manifest + DB + JobResponse**
   - `2b99a17` (test) - add failing round-trip + null-case tests
   - `676b626` (feat) - migration 0009 + model/manifest/route/projection changes + migration-idempotency version bump
2. **Task 2: Render original_filename in HistoryRow with fallback + regenerate FE types**
   - `cf56645` (test) - add failing HistoryRow tests
   - `ca1d969` (feat) - HistoryRow display logic + types.ts additive field

**Plan metadata:** pending (final docs commit below)

## Files Created/Modified
- `migrations/0009_add_original_filename.sql` - ALTER TABLE jobs ADD COLUMN original_filename TEXT (idempotent one-column-per-file convention)
- `app/models/manifest.py` - JobManifest.original_filename additive field (default None)
- `app/models/job.py` - JobResponse.original_filename + _row_to_response projection
- `app/jobs/manifest.py` - update_stage UPDATE binds original_filename (H3+H4 invariant)
- `app/jobs/service.py` - list_jobs + get_job SELECTs widened to include original_filename (Rule 3 deviation)
- `app/api/routes_jobs.py` - upload route persists X-Filename into manifest + DB row before enqueue; added `from sqlalchemy import text`
- `web/src/api/types.ts` - JobResponse + JobManifest schemas gain original_filename?: string | null (manual additive edit)
- `web/src/components/HistoryRow.tsx` - filename = original_filename ?? basename(source_path) ?? "unknown"
- `tests/test_original_filename.py` - round-trip + null-case integration tests
- `web/src/components/HistoryRow.test.tsx` - 3 vitest cases (present / null fallback / both absent)
- `tests/test_migration_idempotency.py` - _APPLIED_VERSIONS gains 9 (Rule 3 deviation)

## Decisions Made
- original_filename is display-only and additive; source_path and D-04 are untouched.
- The upload route writes the DB column at upload time (not just the manifest) so an immediate GET returns the value without waiting for the orchestrator's update_stage re-projection. This is the "original_filename gets it right from the start" approach the plan called out.
- ManifestPatch was deliberately NOT extended -- original_filename is set only by the upload route, not by user stage-patch calls.
- FE types.ts manual edit chosen over regen because a stale OS process held port 8000 and my fresh uvicorn instance could not bind; the plan explicitly sanctions this manual fallback for a single additive field.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Widened list_jobs + get_job SELECTs in app/jobs/service.py**
- **Found during:** Task 1 (implementation)
- **Issue:** `_row_to_response` was extended to read `row.original_filename`, but `list_jobs` and `get_job` build their SELECT column lists explicitly and did not include `original_filename`. SQLAlchemy rows from `sa.select(...).select_from(sa.table("jobs"))` only expose the selected columns as attributes, so `row.original_filename` would have raised `AttributeError` on every `GET /jobs` and `GET /jobs/{id}` call.
- **Fix:** Added `sa.column("original_filename")` to both SELECT queries in service.py.
- **Files modified:** app/jobs/service.py
- **Verification:** Full back-end suite green (278 pre-existing + 2 new tests); existing test_get_jobs / test_get_job_by_id / test_create_job all pass.
- **Committed in:** 676b626 (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Updated _APPLIED_VERSIONS in tests/test_migration_idempotency.py**
- **Found during:** Task 1 (full back-end suite verification)
- **Issue:** Migration 0009 is auto-discovered by the runner's glob, so `apply_migrations` now records version 9. The idempotency test's hardcoded `_APPLIED_VERSIONS = [1..8]` no longer matched the applied set, failing both `test_apply_migrations_three_times` and `test_apply_migrations_recovers_missing_version_row`.
- **Fix:** Appended `9` to `_APPLIED_VERSIONS` and updated the surrounding comment to cite plan 05-04.
- **Files modified:** tests/test_migration_idempotency.py
- **Verification:** `python -m pytest tests/test_migration_idempotency.py -x` -> 2 passed.
- **Committed in:** 676b626 (Task 1 GREEN commit)

**3. [Rule 1 - Bug] Dropped over-reaching DB source_path assertion from test_original_filename.py**
- **Found during:** Task 1 (GREEN run)
- **Issue:** The plan's test spec asserted "the DB source_path column still ends with source.mp4 via a direct SELECT". The upload route does NOT project source_path to the DB at upload time -- only the orchestrator's `update_stage("ingested")` does that, and the worker is off (`run_worker=False`) in the test, so the DB source_path column is NULL immediately after upload. The plan's own action section only adds an UPDATE for `original_filename`, not source_path, so the DB assertion was unreachable as specified.
- **Fix:** Replaced the DB source_path assertion with (a) a DB SELECT asserting `original_filename == "my great video.mp4"` (the new column the route actually writes) and (b) the on-disk `source.mp4` file existence check (the real D-04 invariant, mirroring test_upload_stream.py). The on-disk manifest `source_path` endswith check is retained. A comment explains why DB source_path is NULL at upload time.
- **Files modified:** tests/test_original_filename.py
- **Verification:** `python -m pytest tests/test_original_filename.py -x` -> 2 passed.
- **Committed in:** 676b626 (Task 1 GREEN commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 3 blocking, 1 Rule 1 bug)
**Impact on plan:** All three were required for the plan to function as specified. service.py widening is a direct consequence of the plan's `_row_to_response` change; the migration version bump is a direct consequence of adding migration 0009; the test assertion fix corrects an inconsistency between the plan's behavior section and its action section. No scope creep; files_modified list gained service.py and test_migration_idempotency.py as unavoidable in-scope consequences of the plan's own changes.

## Issues Encountered
- A stale OS process held port 8000, so a fresh `uvicorn app.main:app --port 8000` could not bind and `npm run gen-types` would have hit the pre-impl OpenAPI schema. Per the plan's sanctioned fallback, the single additive `original_filename?: string | null` field was added manually to JobResponse + JobManifest in web/src/api/types.ts. The next `gen-types` run (when port 8000 is free) will reconcile.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Gap A (history row naming) is closed end-to-end; a re-run of UAT test 4 should show the dropped filename on completed rows.
- Gap B (stalled feedback between upload completion and history appearance) is the scope of plan 05-05, which runs next sequentially -- no files outside this plan's scope were touched.
- Manual spot-check (post-execution, optional): drop a named file via the UI, complete a job, confirm the history row shows the dropped name (not source.mp4).

## Self-Check: PASSED

- Created files verified present on disk:
  - FOUND: migrations/0009_add_original_filename.sql
  - FOUND: tests/test_original_filename.py
  - FOUND: web/src/components/HistoryRow.test.tsx
  - FOUND: .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-04-SUMMARY.md
- Task commits verified in git log:
  - FOUND: 2b99a17 (test 05-04 Task 1 RED)
  - FOUND: 676b626 (feat 05-04 Task 1 GREEN)
  - FOUND: cf56645 (test 05-04 Task 2 RED)
  - FOUND: ca1d969 (feat 05-04 Task 2 GREEN)

---
*Phase: 05-local-file-ingest-history-ui-3-pane-layout*
*Completed: 2026-06-26*