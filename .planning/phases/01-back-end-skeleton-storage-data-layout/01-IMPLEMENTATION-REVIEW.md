---
phase: 01-back-end-skeleton-storage-data-layout
reviewer: codex
review_kind: implementation
reviewed_at: 2026-06-14T23:16:00Z
commit_reviewed: 2f79b0f
tests_passing_at_review: 78
risk_level: HIGH
---

# Phase 1 Implementation Review — Codex

> Cross-AI peer review of the **actual code** that landed for Phase 1 (28 .py files, ~2000 lines, 9 atomic commits, 78 pytest cases passing at the time of review).
>
> Distinct from `01-REVIEWS.md` (plan-level review) and `01-UAT.md` (goal-backward success-criteria verification). This is a critical third-party code review intended to surface defects the in-process tests may have missed.

## Summary

The implementation has a sensible structure, centralized filesystem helpers, typed request models, atomic single-file writes, and useful reconciliation groundwork. However, several foundational contracts are currently false in real execution: changing `data_dir` creates an immediate split between SQLite and filesystem storage, OpenAPI documents the wrong `POST /jobs` response, job metadata and status are not consistently projected between manifest and DB, and resume checks accept structurally invalid output files. These issues are insufficiently covered by the reported 78 tests. Risk is **HIGH** until the persistence and API-contract defects are fixed.

## Strengths

- Clear package layout across `api`, `jobs`, `storage`, `models`, `settings`, and `util`.
- Manifest-first stage updates provide a recoverable crash ordering.
- Atomic writes correctly use same-directory temporary files, flush, `fsync`, and `os.replace`.
- Windows retry behavior is isolated and tested.
- Optional diarization and summary stages are represented explicitly.
- `done` as a derived state is better than inventing an empty marker file.
- `ManifestPatch` prevents overriding protected manifest fields.
- Startup migration failure correctly prevents serving requests.
- UUID generation and API-side validation are centralized.
- CORS and trusted-host middleware are configured rather than omitted.
- The one-column-per-migration deviation is a reasonable improvement over migration-level guards.

## Concerns

- **HIGH:** Runtime `data_dir` changes split the DB and filesystem. The in-memory settings object changes immediately, but the engine remains attached to the old database. `app/settings/service.py:105`, `app/settings/service.py:114`
- **HIGH:** OpenAPI says `POST /jobs` returns `JobManifest`, while runtime returns `JobResponse`. Generated frontend types will be wrong. `app/api/routes_jobs.py:44`
- **HIGH:** `update_stage` changes neither DB status nor manifest status. A job can reach `current_stage="done"` while still reporting `status="queued"`. `app/jobs/manifest.py:112`
- **HIGH:** Manifest patches such as language, duration, and summary kinds are never projected into SQLite, and reconciliation only repairs stage/timestamp fields. `app/jobs/manifest.py:133`, `app/jobs/reconcile.py:83`
- **HIGH:** Job creation commits SQLite before creating the folder, with no compensation or reconciliation for DB rows lacking folders. `app/jobs/service.py:49`
- **MEDIUM:** Resume checks validate only JSON syntax. `{}` counts as a completed transcript or summary despite failing the corresponding Pydantic model. `app/jobs/resume.py:72`
- **MEDIUM:** Zero-byte `source.*` files count as successfully ingested. `app/jobs/resume.py:116`
- **MEDIUM:** Stale checks can change completed jobs to failed because status is not considered. `app/jobs/cleanup.py:114`
- **MEDIUM:** Trusted-host validation is not a loopback security boundary. A remote client can send an allowed `Host` header if Uvicorn is exposed.
- **LOW:** Blocking `time.sleep`, `rmtree`, directory scans, and some filesystem calls execute in async request paths.
- **LOW:** Transcript timestamps, confidence, duration, summary kinds, and settings paths lack important semantic constraints.

## Specific Bugs Or Smells

| Location | Issue | Proposed fix |
|---|---|---|
| `app/settings/service.py:105` | `data_dir` is applied live despite being restart-only. | Persist a pending setting but retain the active in-memory value until restart. |
| `app/models/settings.py:30` | `{"data_dir": null}` is valid input; `model_copy` then creates invalid `Settings(data_dir=None)`. | Make the field `str` with no nullable value, or reject `None` explicitly and revalidate via `Settings.model_validate`. |
| `app/api/routes_jobs.py:48` | The custom 201 response overrides the actual `JobResponse` schema. | Remove the 201 `JobManifest` override and expose storage schemas through a dedicated schema wrapper or route. |
| `app/jobs/service.py:66` | Filesystem failure leaves a committed orphan DB row. | Roll back/compensate by deleting the row, or add DB-to-filesystem reconciliation with an explicit failed state. |
| `app/jobs/service.py:67` | Initial manifest discards submitted `source_type` and `source_path`; response also omits `source_path`. | Construct the manifest and response from the full creation request. |
| `app/jobs/manifest.py:125` | Patched metadata is written only to the manifest. | Update all projected DB columns in the same DB transaction and reconcile all projected fields. |
| `app/models/job.py:66` | `summary_kinds` accepts arbitrary strings that later make resume logic raise `ValueError`. | Type it as `list[SummaryKind]`; use the same type in `JobManifest` and `JobResponse`. |
| `app/jobs/reconcile.py:116` | Reconciliation sets `updated_at` to the original queued timestamp. | Use the latest stage timestamp or the current reconciliation time. |
| `app/storage/fs.py:65` | Central path helpers do not themselves validate `job_id`. | Validate/canonicalize inside `job_dir`, ensuring resolved paths remain under `jobs/`. |

## Test Gaps

The strongest tests exercise HTTP creation/read behavior, cancellation ordering, manifest-first updates, retry behavior, and basic reconciliation.

A substantial portion is shallow: model round trips, literal/constant assertions, path equality checks, schema-presence checks, and basic 422 smoke tests. Notably, `test_limit_cap_200` creates only three jobs and does not test the cap.

Despite the SUMMARY/UAT claims, there are no direct tests for WAL on multiple connections, repeated migration application, partial migrations, or `schema_version` contents.

Missing high-value tests include:

- Create-job failures after DB commit.
- Creating a job after changing `data_dir`.
- `data_dir: null`, empty, relative, unwritable, or file paths.
- Actual OpenAPI operation response versus runtime response.
- Stage-to-status transitions, including `done`.
- Metadata projection and reconciliation.
- Corrupt but syntactically valid stage files.
- Zero-byte source files.
- Stale checks on done, failed, and cancelled jobs.
- Concurrent stage, cancel, and settings operations.

Test execution produced **77 passes and one setup error** because pytest could not access its Windows temporary directory in this managed environment; the error occurred before application code ran. The 78-pass count in `01-UAT.md` was from a different environment.

## Boundary Violations

- `app/api` does **not** import `app.storage.atomic` or `app.storage.fs`; that boundary holds.
- Application modules do not construct literal `Path("data/jobs/...")` paths.
- The SUMMARY's stronger claim about tests is inaccurate: several tests manually compose `tmp_data_dir / "data" / "jobs" / job_id`.
- Centralization is incomplete because `reconcile.py` constructs the jobs root itself.
- `app/api/routes_jobs.py` directly imports Pydantic's `ValidationError`, which technically violates a literal reading of "model-library imports only in `app.models`."

## Deviation Assessment

- Stable bootstrap settings path: **improvement**.
- One-column migrations and per-statement duplicate handling: **improvement**, but inadequately tested.
- Derived `done` and optional stages: **improvement**.
- Path-aware settings service: useful for tests, but live settings replacement is a **regression**.
- OpenAPI model injection: understandable, but overriding the real 201 response is a **regression**.
- Per-job reconciliation sessions: reasonable.
- Stale-check UUID asymmetry: unnecessary inconsistency, but low impact.
- Compatibility default for `diarization_enabled`: reasonable.

## Risk Assessment

**Overall risk: HIGH.**

Phase 2 will extend settings and foundational storage behavior, so advancing without fixing the live `data_dir` split would compound the most serious defect. The incorrect OpenAPI response also undermines the frontend contract, while incomplete projection and permissive resume checks weaken the promised file-as-truth model.

## Recommended Follow-Ups

1. **Fix restart-only settings semantics** — Effort **S**, Impact **L**
2. **Correct the `POST /jobs` OpenAPI response** — Effort **S**, Impact **L**
3. **Define and implement full manifest-to-DB projection, including status** — Effort **M**, Impact **L**
4. **Add compensation/recovery for partial job creation** — Effort **M**, Impact **L**
5. **Validate stage files with their Pydantic models** — Effort **M**, Impact **L**
6. **Strengthen model constraints and centralized path validation** — Effort **S**, Impact **M**
7. **Make stale detection status-aware and heartbeat-ready** — Effort **S**, Impact **M**
8. **Add real migration, WAL, failure-boundary, and concurrency tests** — Effort **M**, Impact **L**
