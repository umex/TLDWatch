# Phase 1: Back-end Skeleton + Storage + Data Layout - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the back-end service skeleton, persistent storage, and per-job filesystem layout that every later component imports.

- FastAPI app boots locally and serves an OpenAPI schema the React front-end can consume
- SQLite database in WAL mode with a versioned schema and idempotent migrations
- `data/jobs/<job_id>/` directory per job, created on demand, used as source-of-truth for stage outputs
- Pydantic models for job state, transcript segments, summary outputs, settings — shared with generated TypeScript types
- Clean `app.api`, `app.jobs`, `app.storage`, `app.models` boundary — nothing else imports a model library

The phase ships the **foundation**. No model adapters, no GPU detection, no jobs running yet — just the typed surfaces, the storage primitives, and the OpenAPI contract that downstream phases build on.

</domain>

<decisions>
## Implementation Decisions

### Project layout & data directory
- **D-01:** Two separate repos — backend lives in this repo, frontend will live in a new repo. Both Dockerized later. Cross-cutting changes land as two coordinated PRs.
- **D-02:** `data/` lives next to the backend executable (relative to the running app). Default overridable via `settings.json → data_dir`.
- **D-03:** Per-job folder is flat: `data/jobs/<id>/{source.ext, transcript.json, diarization.json, summary-<kind>.json, edits.json, manifest.json}`. No per-stage subfolders.
- **D-04:** Atomic writes via a single `storage.atomic_write_*` helper: write to `<name>.tmp` → `fsync` → `os.replace()` to `<name>`. Used by every stage output, every settings change, every manifest rewrite.
- **D-05:** `manifest.json` is rich (one read = full picture for the orchestrator and UI). Schema: `schema_version`, `job_id`, `source_type`, `source_path`, `source_sha256`, `duration_s`, `language`, `summary_kinds`, `status`, `current_stage`, `stage_timestamps`, `error`. Rewritten by every stage mutator after writing its stage file, kept consistent with FS.

### Database access & migrations
- **D-06:** SQLAlchemy 2.0 async + aiosqlite end-to-end. All FastAPI routes are `async def` and use `AsyncSession`. No sync SQLAlchemy paths in app code.
- **D-07:** Hand-rolled `schema_version` table + numbered SQL files in `migrations/`. Each file is plain SQL, applied in a single transaction. No Alembic, no autogenerate.
- **D-08:** One-shot startup migration check. On backend boot, connect to DB, read `schema_version` table (create if missing), compare to `migrations/*.sql` filenames, apply any not yet recorded. On failure: loud log + refuse to start. Schema is always up-to-date on boot.
- **D-09:** Phase 1 ships only `jobs` and `settings` tables. Everything else (queue positions, `job_events`, speaker aliases, model overrides, summary outputs, transcript_segments) gets added by the phase that needs it via a new migration. YAGNI, no placeholder columns.

### Job IDs & file-as-truth
- **D-10:** UUIDv4 for job IDs. URL-safe, Windows-path-safe, no clock coupling, no extra dependency. Sort via `created_at` index (separate column, not derived from id).
- **D-11:** Stage ↔ file mapping (one file per "done" check):
  - `current_stage='ingested'` → `source.ext` exists
  - `current_stage='transcribed'` → `transcript.json` exists
  - `current_stage='diarized'` → `diarization.json` exists (optional stage, only when diarization was enabled)
  - `current_stage='summarized'` → one `summary-<kind>.json` per selected kind exists
  - `manifest.json` always tracks `current_stage` + `stage_timestamps` + language + summary_kinds
- **D-12:** Resume rule: walk files in the standard order, pick the first incomplete stage. The filesystem is the truth, the DB is the index. Unparseable file = log + re-run that stage. No DB consultation needed to infer the resume point.
- **D-13:** Job lifecycle cleanup:
  - **Cancel** = delete the per-job folder + mark DB row `cancelled`. Clean, no half-files.
  - **Failure** = keep the folder, mark DB row `failed`, surface error in UI. User can inspect via `ls`.
  - **Stale** = no stage-output write in 10 minutes → orchestrator marks the job `failed (stalled)`.
  - **Retry failed** = explicit UI action that re-runs from the incomplete stage using the resume rule.

### Settings, Pydantic, codegen
- **D-14:** `settings.json` in `data_dir`, loaded into a Pydantic model on boot, atomic write on change. Pydantic model is the single source of truth; the file is a serialization of the model.
- **D-15:** Pydantic v2 **strict for input** (`model_config = ConfigDict(strict=True)` on all request models), **lax for output** (response models and internal storage models like `transcript.json` deserialization stay default). Catches front-end bugs at the API boundary (PITFALLS.md pitfall 7) without making internal model-to-model conversion tedious.
- **D-16:** `openapi-typescript` for codegen — types only, no client fetch helpers. Front-end writes fetch calls by hand using the generated `types.d.ts`. Types regenerate from the live OpenAPI schema on every backend build.
- **D-17:** Phase 1 settings model has just `data_dir: str`. Every other field (`gpu_backend`, `hf_token`, `quality_preset`, `per_category_overrides`) gets added by the phase that needs it. Same YAGNI principle as the schema decision.

### Claude's Discretion
None — every area was either explicitly chosen or assigned to Claude with a recorded rationale.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — hardware constraints (8 GB laptop VRAM budget, dual-machine target), no-telemetry rule, single-user no-auth, separation of concerns (front-end and back-end as two codebases), silent-first-run promise
- `.planning/REQUIREMENTS.md` — `HW-01` is the only v1 requirement owned by Phase 1 (front-end and back-end are separated and communicate via a job API)
- `.planning/STATE.md` — project state, accumulated context, blocked-concerns list (ROCm on Windows is the highest-risk Phase 2 unknown — Phase 1 should not pre-commit to either backend)

### Research
- `.planning/research/SUMMARY.md` §"Recommended Stack" — Python 3.11 + FastAPI + Uvicorn for the back-end
- `.planning/research/SUMMARY.md` §"Architecture Approach" — two-process system, back-end as system of record, FastAPI + in-process job orchestrator + persistent SQLite queue + per-job working directory on disk
- `.planning/research/SUMMARY.md` §"Phase 1 / 4 rationale" — Phase 1 is dependency-foundational, every other component imports it
- `.planning/research/PITFALLS.md` pitfall 7 — front-end / back-end schema disagreement. The strict-input + `openapi-typescript` codegen decisions in D-15, D-16 are direct mitigations
- `.planning/research/PITFALLS.md` pitfall 9 — job-queue state on disk is the source of truth but the schema evolves. The D-04, D-05, D-11, D-12 decisions are direct mitigations
- `.planning/research/PITFALLS.md` pitfall 4 — paths with spaces in HF model downloads. The D-02 default (relative to the executable, which the user controls) avoids the hardcoded `Program Files` trap

### Roadmap
- `.planning/ROADMAP.md` — Phase 1 goal, mode (mvp), plans list (01-01, 01-02, 01-03), and downstream phases that import what Phase 1 ships (Phase 2 onward)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
None — greenfield project. No existing Python source, no existing schemas, no existing patterns to inherit. Phase 1 *creates* the assets every later phase imports.

### Established Patterns
- **Two-process system** (locked in PROJECT.md) — front-end and back-end are separate codebases. Phase 1 ships the back-end half; the front-end repo will be created separately later.
- **File-as-truth** (locked in PITFALLS.md pitfall 9) — stage transitions are atomic against files on disk. D-11 + D-12 codify the rules.
- **Pydantic as schema source of truth** (locked in D-15) — every model that crosses the API boundary is a Pydantic v2 request model with strict input. The same Pydantic models are exposed via OpenAPI and consumed by the front-end via `openapi-typescript`.

### Integration Points
- **Phase 2 (GPU detection + model manager)** — reads/writes `settings.json` (`gpu_backend` field, added in Phase 2), calls into `app.storage` for any persistent model paths
- **Phase 3 (STT + chunker)** — writes `transcript.json` per D-11 atomic-write rule, updates `manifest.json` per D-05
- **Phase 4 (orchestrator + queue + WebSocket)** — uses D-12 resume rule, owns the `job_events` and queue tables (added via migration in Phase 4, not Phase 1), broadcasts progress over WebSocket
- **Phase 5+ (UI)** — consumes OpenAPI schema generated from Pydantic models; front-end codegen runs from the same schema
- **Phase 7 (diarization)** — writes `diarization.json` per D-11
- **Phase 8 (summarization)** — writes `summary-<kind>.json` per D-11
- **Phase 9 (editor)** — reads/writes `edits.json` per D-11
- **Phase 10 (settings panel)** — adds `gpu_backend`, `hf_token`, `quality_preset`, `per_category_overrides` to the `settings.json` Pydantic model per D-17

</code_context>

<specifics>
## Specific Ideas

- User wants two separate repos with Dockerization on the roadmap — Phase 1 keeps the structure Docker-friendly (the data dir is configurable and lives outside the source tree, not embedded in the Python package) but does not add a Dockerfile.
- User specified that `data/` defaults to the same path as the backend executable root, overridable via settings. This is a deliberate choice over the more conventional `%LOCALAPPDATA%` Windows convention.
- The `openapi-typescript` codegen decision (D-16) was made over `orval` (which generates a typed client + TanStack Query hooks) — user accepted the "types only, hand-written fetch calls" tradeoff in exchange for keeping the front-end fetch layer explicit.
- The 10-minute staleness threshold (D-13) is a starting default; should be exposed as a setting or constant later but is hardcoded for Phase 1.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No new capabilities were proposed that need to land in a future phase.

</deferred>

---

*Phase: 1-Back-end Skeleton + Storage + Data Layout*
*Context gathered: 2026-06-11*
