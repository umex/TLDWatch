# Phase 1: Back-end Skeleton + Storage + Data Layout - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 1-Back-end Skeleton + Storage + Data Layout
**Areas discussed:** Project layout & data directory, Database access & migrations, Job IDs & file-as-truth, Settings/Pydantic/codegen

---

## Project layout & data directory

| Option | Description | Selected |
|--------|-------------|----------|
| Monorepo (backend + frontend siblings) | One repo, one clone, easier cross-cutting | |
| Two separate repos + Dockerize later | Frontend in a new repo, both Dockerized, settings-driven data dir | ✓ |

**User's choice:** "two seperate repos and later on we will dockerize both parts of the application. First we can store trancriptions on the same path where root of application lives, and we can put in settings the default location for saves."

### Q2: Data dir default

| Option | Description | Selected |
|--------|-------------|----------|
| `%LOCALAPPDATA%\TranscriptionAndNotes\` | Windows standard, no spaces | |
| Next to the backend executable (relative to running app) | Matches "store on the same path where root of application lives" | ✓ |
| `Documents\TranscriptionAndNotes\` | Visible but OneDrive conflicts | |

**User's choice:** Option 2

### Q3: Per-job folder layout

| Option | Description | Selected |
|--------|-------------|----------|
| Flat per-job folder (`source.ext`, `transcript.json`, etc. at top level) | Every stage writes one file, no nesting | ✓ |
| Per-stage subfolders (`00-source/`, `10-stt/`, etc.) | Stage-order numbering | |

**User's choice:** Option 1

### Q4: Atomic writes + manifest content

| Option | Description | Selected |
|--------|-------------|----------|
| Atomic writes: `.tmp` + fsync + `os.replace` | Crash-safe, single helper | ✓ |
| Direct write | Half-files on power loss | |
| Manifest: minimal (`schema_version`, `job_id`, `source_type`, `created_at`, `status`) | Small, fast | |
| Manifest: rich (full schema incl. `source_sha256`, `duration_s`, `language`, `summary_kinds`, `current_stage`, `stage_timestamps`, `error`) | One read = full picture | ✓ |

**User's choice:** "1,3:whatever you think best" — locked atomic write as option 1, and Claude chose rich manifest as the better tradeoff for orchestrator + UI access.

**Notes:** User added meta-instruction at end of this area: "any commits that you do from now on author must come from global." Pinned local `user.name`/`user.email` to match global (`dobrez <dejan.obrez@gmail.com>`) as a safety net. Saved to memory.

---

## Database access & migrations

### Q1: Async vs sync DB access

| Option | Description | Selected |
|--------|-------------|----------|
| SQLAlchemy 2.0 async + aiosqlite end-to-end | Async routes, AsyncSession | ✓ |
| Sync SQLAlchemy 2.0 + run_in_threadpool | Plain `def` routes, sync sessions | |
| Raw aiosqlite, hand-rolled queries | Zero ORM weight | |

**User's choice:** Initially "2", then "explain 2 const more in detail" — after a detailed explanation of sync + threadpool semantics (including the aiosqlite-under-the-hood serialization point and the realistic <10 RPS load), user chose option 1.

**Notes:** User cares about understanding the tradeoffs before locking — they asked for elaboration rather than picking on a one-liner description. Worth knowing for future discussion: present technical depth, not just bullet labels, when the topic has subtle traps.

### Q2: Migration tool

| Option | Description | Selected |
|--------|-------------|----------|
| Alembic | Standard, autogenerate, async fiddly | |
| Hand-rolled `schema_version` table + numbered SQL files | Zero magic, plain .sql, fits "file-as-truth" ethos | ✓ |
| yoyo-migrations / dbmate | SQL-first, extra binary | |

**User's choice:** Option 2

### Q3: Migration runner

| Option | Description | Selected |
|--------|-------------|----------|
| One-shot startup check, single transaction per migration, fail loud | Schema always up-to-date on boot | ✓ |
| Explicit `python -m app.storage.migrate` CLI | User-driven, contradicts silent-first-run | |
| Lazy apply on first DB connection | Equivalent to (1), more code | |

**User's choice:** Option 1

### Q4: Phase 1 schema table set

| Option | Description | Selected |
|--------|-------------|----------|
| Just `jobs` + `settings` (YAGNI) | Minimal Phase 1, schema grows with real requirements | ✓ |
| Full skeleton schema (jobs, job_events, settings, speaker_aliases, model_overrides, summary_outputs, transcript_segments) | Complete front-end type surface upfront | |

**User's choice:** Option 1

---

## Job IDs & file-as-truth

### Q1: Job ID format

| Option | Description | Selected |
|--------|-------------|----------|
| UUIDv4 (random) | 36 chars, no clock coupling, simple | ✓ |
| UUIDv7 (time-ordered) | Sort by id = sort by time, less library maturity | |
| ULID (26 chars) | Shortest sortable, extra dep | |

**User's choice:** Option 1

### Q2: Stage ↔ file mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Minimum: source + transcript + summary files only | One file per "done" check, `manifest.json` carries stage timestamps | ✓ (Claude's discretion) |
| Per-stage file always written (intermediate files kept) | More visible files, redundant data | |

**User's choice:** "you decide" — Claude chose option 1 as the better fit for the orchestrator's "one exists() check per stage" resume rule. Manifest (D-05) carries stage_timestamps, language, summary_kinds so the file set stays minimal.

### Q3: Resume rule

| Option | Description | Selected |
|--------|-------------|----------|
| Walk files in standard order, pick the first incomplete stage | FS is truth, single pass, no DB consultation | ✓ |
| Trust manifest.json's `current_stage`, verify file exists | Faster, extra reconciliation logic | |

**User's choice:** Option 1

### Q4: Cleanup & staleness

| Option | Description | Selected |
|--------|-------------|----------|
| Cancel = delete folder + DB cancelled; Failure = keep folder + DB failed; Stale (10 min no write) = failed (stalled) | Clean cancel, inspectable failures, bounded stalls | ✓ |
| Cancel = keep folder (resumable) | Nothing ever deleted, UI scope for resume | |

**User's choice:** Option 1

---

## Settings, Pydantic, codegen

### Q1: Settings storage

| Option | Description | Selected |
|--------|-------------|----------|
| `settings.json` in `data_dir`, Pydantic model on boot, atomic write | Human-readable, survives DB corruption, Pydantic-typed | ✓ |
| SQLite settings table (key/value JSON) | One source of truth | |
| Both: settings.json + SQLite mirror | Two sources, no real use case | |

**User's choice:** Option 1

### Q2: Pydantic v2 strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Lax everywhere (default) | Friendly, hides front-end bugs | |
| Strict for input, lax for output | Catches front-end bugs at API boundary, output stays flexible | ✓ (Claude's discretion) |
| Strict everywhere | Maximally safe, internal conversions fail loud | |

**User's choice:** "you decide" — Claude chose option 2 as the best fit for the PITFALLS.md pitfall 7 mitigation: catches front-end bugs at the API boundary while keeping internal `transcript.json` / `summary-*.json` deserialization painless.

### Q3: OpenAPI → TypeScript codegen

| Option | Description | Selected |
|--------|-------------|----------|
| `openapi-typescript` (types only) | Simplest, types only, hand-written fetch | ✓ |
| orval (types + TanStack Query hooks) | Typed hooks, ties front-end to specific style | |
| Hand-roll shared types in `shared/` package | Drift waiting to happen | |

**User's choice:** Option 1

### Q4: Phase 1 settings field set

| Option | Description | Selected |
|--------|-------------|----------|
| Just `data_dir` (YAGNI) | Minimal Phase 1, matches the schema YAGNI principle | ✓ |
| All known future fields as Optional/None defaults | Complete settings surface visible upfront | |

**User's choice:** Option 1

---

## Claude's Discretion

Three areas assigned to Claude with recorded rationale:
- **D-04 / D-05 (atomic write + rich manifest):** Rich manifest chosen as the better fit for the orchestrator's single-read pattern. Source URL: https://www.pydantic.dev.
- **D-11 (stage ↔ file minimum set):** Minimum file set chosen because `manifest.json` already carries stage_timestamps, language, summary_kinds.
- **D-15 (Pydantic strict input, lax output):** Direct mitigation of PITFALLS.md pitfall 7 without making internal model-to-model conversion tedious.

## Deferred Ideas

None — discussion stayed within phase scope. No new capabilities were proposed that need to land in a future phase.
