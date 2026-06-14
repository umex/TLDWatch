---
phase: 1
reviewers: [codex, gemini]
reviewed_at: 2026-06-14T16:18:00Z
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 1

## Codex Review

## Summary

The plans provide a sensible phased skeleton and cover most Phase 1 deliverables, but several core consistency and lifecycle problems remain unresolved. The largest are the impossible claim of atomicity across SQLite and filesystem writes, circular handling of `data_dir`, incomplete stage/resume semantics, fragile migrations, and exposing internal mutation routes without sufficient validation. The dependency order is broadly correct, but Wave 1 establishes settings, database, and routing patterns that Wave 2 immediately replaces or may invalidate. The plans are implementable after tightening these contracts, but as written they carry a **HIGH** risk of inconsistent persisted state and difficult migrations.

## Strengths

- Clear wave ordering: bootstrap, model/read surface, then lifecycle and filesystem helpers.
- The four primary boundaries are explicit and generally keep API, orchestration, storage, and models separate.
- SQLite WAL, foreign keys, startup migrations, and persistent jobs are appropriate for a local single-user service.
- Atomic single-file writes using temporary files, `fsync`, and `os.replace` are a strong baseline.
- Per-job filesystem paths are centralized instead of being reconstructed throughout the application.
- UUIDv4 identifiers and a dedicated `created_at` index are appropriate.
- The plans avoid premature relational tables for transcripts, summaries, and events.
- Typed models and OpenAPI-based TypeScript generation support the frontend/backend contract.
- Failure retention and cancellation deletion are clearly distinguished.
- Tests are planned for each wave and cover the main happy-path contracts.
- Async SQLAlchemy and aiosqlite are used consistently rather than mixing sync and async database access.
- Startup refusal on migration failure avoids running against a partially understood schema.

## Concerns

### HIGH

- **Filesystem and database updates cannot be atomic together.** `update_stage` cannot atomically commit both `manifest.json` and a SQLite row. A crash between operations will leave them inconsistent. The plan needs an explicit ordering, recovery rule, and authoritative source.
- **`data_dir` has a circular bootstrap definition.** The settings file is said to live inside `data_dir`, while `data_dir` is obtained from that settings file. After changing it, the next startup may continue reading the old settings location or fail to discover the new one.
- **Runtime `data_dir` changes invalidate initialized resources.** `PATCH /settings` can change `data_dir`, but the database engine, session factory, current paths, settings-file location, and migrations were initialized against the prior directory. Merely updating in-memory settings would split data across locations.
- **Resume semantics do not match optional stages.** Diarization and summaries are optional, but `STAGE_ORDER` always requires `diarized` and `summarized`. Completion cannot be inferred solely from fixed files without knowing which stages were requested.
- **The `done` stage has no corresponding completion file.** D-11 says one file per done check, but the proposed layout has no `done` output. It is unclear how `is_stage_complete("done")` can return true without trusting mutable manifest state.
- **Migration idempotency is underspecified and fragile.** A guard mapping per migration file does not safely handle partial application of a migration containing several `ALTER TABLE` statements. If one column exists and others do not, skipping the entire migration or rerunning it both produce incorrect outcomes.
- **Arbitrary manifest patching weakens all invariants.** `manifest_patch: dict[str, Any]` allows clients to overwrite identifiers, timestamps, paths, stage state, or schema fields unless explicitly filtered. It also bypasses the intended typed model boundary.
- **Cancellation ordering can lose recoverable data.** If the folder is deleted before the DB update and the DB update fails, the job remains active with its data gone. Reversing the order introduces a different recoverable inconsistency, so an explicit recovery protocol is needed.

### MEDIUM

- Router registration during lifespan is risky; routers should be included during app construction.
- CORS is missing despite separate frontend and backend repositories.
- OpenAPI generation is tested, but TypeScript generation is not delivered.
- Stale detection will produce false positives for long-running stages (no heartbeat).
- Stale marking appears insufficiently status-aware (completed/cancelled jobs may be re-marked).
- Job creation has an unhandled partial-failure matrix (DB insert, dir creation, manifest write can each fail).
- Source extension and summary kind can become path-injection inputs (no allowlist).
- Job IDs should be parsed as UUIDs before path construction.
- `shutil.rmtree` is synchronous inside an async request.
- `aiofiles` does not make filesystem operations fully nonblocking or durable.
- The database URL construction is brittle on Windows (drive letters, spaces, `#`, `%`, UNC).
- Settings persistence ownership is inconsistent (Wave 1 vs Wave 2 churn).
- The claimed import boundary is ambiguous.
- Timestamp fields are strings instead of typed datetimes (DST, timezone bugs).
- SQL JSON columns need a canonical serialization contract.
- List pagination is incomplete (silent cap of 200).
- Internal control endpoints are exposed as public API.

### LOW

- Version constraints use broad lower bounds rather than a reproducible lockfile.
- The settings SQL table appears unused because settings are stored in JSON.
- `source_path` may expose absolute local paths to the frontend unnecessarily.
- `last_stage_mtime` scanning every file should use a fixed allowlist.
- Confidence and transcript times lack basic constraints (nonnegativity, `end_s >= start_s`).
- Summary sections as `dict[str, str]` may be too restrictive later.

## Suggestions

- Define a consistency protocol for DB and manifest updates (write output → write manifest → commit DB projection; reconcile from manifest at startup).
- Explicitly declare either the manifest or database as authoritative. D-03 says the job directory is the source of truth, so DB rows should be a rebuildable index.
- Store bootstrap configuration at a stable path outside relocatable `data_dir`, or make the configured data directory a startup/CLI environment option.
- Make `data_dir` restart-required; validate and persist it during PATCH but continue using the existing engine and paths until restart.
- Replace migration-level guards with operation-level Python migrations or one SQL file per column.
- Define stages from the job's requested pipeline (`requested_stages` / `summary_kinds`) rather than assuming every optional stage exists.
- Define completion artifacts precisely; make `done` a derived terminal state, not a file-backed stage.
- Replace arbitrary `manifest_patch` with a typed, allowlisted request model.
- Keep internal mutators out of public routes unless needed by a separate process; if retained, bind to loopback and enforce allowed origins/hosts.
- Add tests for crash boundaries: DB-insert-succeeds-but-folder-fails, manifest-write-succeeds-but-DB-commit-fails, partial migration, corrupted manifest, missing folder with DB row, existing folder with no DB row, concurrent cancel + stage.
- Use typed timezone-aware UTC `datetime` fields consistently.
- Construct SQLite URLs with `sqlalchemy.engine.URL.create(...)` or a documented path-safe helper.
- Add strict path validation: parse job IDs as `UUID`, use `SummaryKind` not raw strings, map source formats to known extensions, verify resolved paths remain under the job directory.
- Add heartbeat/progress timestamps independent of completed stage files for stale detection.
- Register routers during app construction; use lifespan only for resource init/teardown.
- Add a reproducible OpenAPI type-generation command and CI/test check.
- Add localhost CORS and trusted-host configuration.

## Risk Assessment

**Overall risk: HIGH**

The architecture is directionally sound, and the wave ordering is mostly reasonable. However, the plans currently make strong durability and atomicity claims that the proposed implementation cannot satisfy. The relocatable settings design, optional-stage resume logic, and partial-migration behavior also affect foundational contracts that every later phase will depend on. Resolving these issues before implementing Wave 2 and Wave 3 should reduce the project to a medium-to-low implementation risk.

---

## Gemini Review

## Summary

A comprehensive and well-structured implementation plan for the **TranscriptionAndNotes** back-end phase. The architectural boundaries (`api`, `jobs`, `storage`, `models`) are clean, and the decision to use a local-first, job-centric filesystem layout is robust for the intended use case. The three-wave plan effectively transitions from a walking skeleton to a feature-complete storage and lifecycle management system. It prioritizes data integrity through atomic file operations and a dual-source-of-truth strategy (DB + Manifest). The use of SQLAlchemy 2.0 async and Pydantic v2 aligns with modern best practices, and the custom idempotent migration path is a pragmatic choice for a single-user local application where Alembic might be overkill.

## Strengths

- Clear Architectural Boundaries: strict separation of concerns (atomic-write logic isolated) prevents spaghetti code as new modules are added.
- Atomic Write Strategy: `tmp + fsync + os.replace` prevents corruption during power loss or crashes — critical for local-first apps.
- Idempotent Migrations: the `_guards.py` approach is safe without Alembic complexity.
- Resume Logic (D-12): filesystem-as-state enables graceful recovery.
- Pydantic v2 Strict/Lax usage: distinguishes input validation from output serialization.

## Concerns

- **Windows File Locking (HIGH)**: `os.replace` and `shutil.rmtree` often fail with `PermissionError` when a file is indexed by Windows Search, held by antivirus, or when the FastAPI app hasn't fully closed a file handle. Job cancellation (Plan 01-03) or manifest updates could crash the request handler.
- **DB/Filesystem Desync (MEDIUM)**: `update_stage` (Plan 01-03) updates both the DB and the manifest. While called "atomic," there is no cross-resource transaction. If the process dies between the manifest write and the DB commit, the sources of truth will drift. The UI (via DB) might show "Transcribing" while the FS says "Diarizing."
- **SQLite WAL on Network Shares (LOW/MEDIUM)**: SQLite WAL is notoriously unreliable over SMB/NFS if `data_dir` is on a NAS or Dropbox.
- **Settings Path Bootstrap (LOW)**: Plan 01-01 creates `data/settings.json` on boot. If the user wants to provide a custom `data_dir` via env vars *before* the first boot, the logic needs to ensure the settings.json is created in the correct location immediately.
- **Aiosqlite + WAL (LOW)**: `aiosqlite` sometimes requires the `PRAGMA journal_mode=WAL` to be set on every connection, not just once. The plan mentions setting it "on connect," which is correct, but needs careful implementation in the `session_factory`.

## Suggestions

- **Resilient File Deletion**: In `app/jobs/cleanup.py`, implement a retry loop for `shutil.rmtree` with a small backoff (e.g., 3 retries over 500ms) to mitigate transient Windows `PermissionError` locks.
- **Consistency Check on Boot**: Add a small utility that runs during the Plan 01-01 startup sequence to verify that the `jobs` table matches the `data/jobs/` directory structure, or at least logs discrepancies.
- **Absolute Paths for `data_dir`**: When `data_dir` is loaded from `settings.json`, immediately convert to an absolute path using `.resolve()` to prevent ambiguity when the app is launched from different working directories.
- **Atomic Write Helper naming**: Explicitly name temporary files with a prefix (e.g., `.tmp_manifest.json`) and ensure they are ignored in `.gitignore`.
- **`update_stage` Ordering**: In `update_stage`, always write the **manifest first**, then update the **DB**. It is safer for the DB to be slightly "behind" the reality of the disk, as the resume logic (Plan 01-03) uses the disk as the ultimate source of truth.

## Risk Assessment

**Risk Level: LOW**

The plans are technically sound and address the core requirements of the phase. The use of Python 3.11 and the specified stack is stable. The most significant risks are environment-specific (Windows file behavior), which are easily managed with defensive coding (retries and path resolution). The dependency ordering between waves is logical and prevents scope bloat in the early stages.

---

## Consensus Summary

### Agreed Strengths

- Clean four-boundary architecture (`api`, `jobs`, `storage`, `models`); atomic-write helper isolation
- Atomic write pattern (`tmp + fsync + os.replace`) is correct and necessary
- File-as-truth resume rule (D-12) enables crash recovery without state machines
- Pydantic v2 strict-for-input / lax-for-output is a sophisticated choice
- YAGNI table set (`jobs` + `settings` + `schema_version` only) is appropriate
- Wave ordering (skeleton → read surface → lifecycle + filesystem) is logical
- Tests are scoped per wave and cover happy paths

### Agreed Concerns (HIGH PRIORITY — surfaced by 2+ reviewers)

- **Windows file locking**: `shutil.rmtree` and `os.replace` will fail with `PermissionError` under antivirus / Windows Search / open file handles. Cancel and update_stage need a retry-with-backoff wrapper. (Codex MEDIUM, Gemini HIGH)
- **DB/Manifest desync is not actually atomic**: `update_stage` is described as atomic but cannot be — there is no cross-resource transaction. The plan needs a stated ordering rule (write manifest first, then DB) and a startup-time reconciliation pass. (Codex HIGH, Gemini MEDIUM)
- **Resume semantics for optional stages**: Diarization and summary are conditional, but `STAGE_ORDER` treats them as required. Plan must derive stages from `manifest.summary_kinds` and a `diarization_enabled` flag. (Codex HIGH)
- **`done` has no completion file**: `is_stage_complete("done")` cannot be a file check; it must be a derived terminal state. (Codex HIGH)
- **Migration guards don't handle partial application**: the per-file `(table, column)` list skips the whole migration if any column exists, leaving the rest unapplied. Use operation-level guards (one column per migration, or Python-level). (Codex HIGH)
- **Arbitrary `manifest_patch: dict[str, Any]`** in `StageUpdateRequest` lets clients overwrite protected fields. Should be a typed, allowlisted model. (Codex HIGH)
- **`data_dir` runtime change doesn't reinitialize the engine / settings-file path / migrations**: PATCH should persist the new value but the change must take effect on restart. (Codex HIGH)
- **Settings-file bootstrap lives inside the directory it points to** — circular. Bootstrap should be a stable, fixed path (or env var). (Codex HIGH)

### Divergent Views

- **Overall risk rating**: Codex rates overall risk **HIGH** (driven by atomicity, settings-circularity, and migration-partial-application issues), Gemini rates **LOW** (driven by confidence in the stack and the wave ordering, with environment-specific concerns as the main risk). The divergent views are not contradictory — Codex weights the durability/correctness claims more heavily, while Gemini weights the stack maturity and incremental wave delivery. Both are essentially right from different angles: the *plans as written* carry HIGH risk on durability/invariants; once the high-priority concerns above are resolved in re-planning, residual risk falls to LOW.
- **Strictness of `update_stage` API exposure**: Codex (HIGH) flags `POST /jobs/{id}/stage` and `/stale-check` as internal-control routes that shouldn't be public without auth/host binding; Gemini does not raise this, treating them as acceptable test/admin surfaces for Phase 1.
- **Migration guards**: Codex argues the `migrations/_guards.py` per-file approach is fragile for multi-statement files; Gemini views it as appropriate for the controlled local environment. The disagreement is about whether single-file multi-statement migrations are an actual Phase-1 risk — they are (0002 has six ALTERs), so the Codex concern wins.

