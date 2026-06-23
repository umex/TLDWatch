---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: Completed 04-05-PLAN.md (CR-01 + CR-02 gap closure)
last_updated: "2026-06-23T08:39:06.983Z"
last_activity: 2026-06-23 -- Phase 04 gap-closure wave 2 (04-05)
progress:
  total_phases: 10
  completed_phases: 4
  total_plans: 18
  completed_plans: 18
  percent: 40
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-22)

**Core value:** The user can drop in any video and get back a clean, speaker-aware transcript plus summaries shaped for the content type — without it ever leaving the machine.
**Current focus:** Phase 04 — job-orchestrator-persistent-queue-websocket-progress

## Current Position

Phase: 04 (job-orchestrator-persistent-queue-websocket-progress) — EXECUTING
Plan: 6 of 6
Status: 04-05 complete (CR-01 + CR-02 closed); 04-06 (WR-04) next
Last activity: 2026-06-23 -- Phase 04 gap-closure wave 2 (04-05)

Progress: [███░░░░░░░] 31%

## Performance Metrics

**Velocity:**

- Total plans completed: 17
- Average duration: — min
- Total execution time: ~4 hours (Phase 01 plans 01..04 + Phase 02 plans 01..02)

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | 4 | — |
| 02 | 5 | - | - |
| 03 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: 01-03, 01-04, 02-01, 02-02, 02-04 (185 tests green after 02-04)
- Trend: stable

*Updated after each plan completion*
| Phase 02 P05 | 12 | 2 tasks | 2 files |
| Phase 03 P01 | 6m | 2 tasks | 8 files |
| Phase 03 P02 | 20m | 2 tasks | 6 files |
| Phase 03 P03 | 25m | 3 tasks | 4 files |
| Phase 04 P01 | 23m | 4 tasks | 13 files |
| Phase 04 P02 | 23m | 4 tasks | 7 files |
| Phase 04 P03 | 67m | 3 tasks | 11 files |
| Phase 04 P04 | 6m | 2 tasks | 2 files |
| Phase 04 P05 | 10m | 2 tasks | 3 files |
| Phase 04 P06 | 8m | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap uses 10 phases, mvp mode, standard granularity — derived from research/SUMMARY.md build-order rationale.
- Project skill guidance loaded; project skills directory was absent in this run, so no per-skill rules were applied.
- **Plan 01-04 (gap-closure):** `PATCH /settings` is restart-only via a `pending` slot in the on-disk JSON; the in-memory state is not swapped until the next boot (`apply_pending()` in the lifespan). `stage_to_status(stage, manifest)` is the single source of truth for the stage-to-status mapping; `update_stage` writes status + full metadata in a single UPDATE; `reconcile_all` projects the same columns on boot. `create_job` compensates the DB row on folder/manifest failure. `parse_stage_file` validates stage files against typed Pydantic models. `mark_stale` is a no-op on terminal rows. Migration runner records the version on the all-duplicate-column path.
- **Plan 02-01 (GPU detect + settings wire-in):** `Settings` extended with 7 Phase 2 fields (D-08 declare-now); `backend: GpuBackend` is REQUIRED (no default) so a Phase 1 settings file triggers the first-boot detect path in the lifespan (`try/except` around `load_settings_from_disk` -> `await backend_module.detect()` + `burn_test()` -> atomic write). `hf_token` base64 on disk via `field_serializer` + `field_validator(mode="before")` (D-05); never returned in `GET /settings` (route nulls the body). `UpdateSettingsRequest` is all-optional with `extra="forbid"` (D-08 — backend/backend_probe NOT declared); a `model_validator` rejects empty PATCH and explicit-null data_dir; per-field `strict=False` on enum/nested-model fields so JSON coerces. `apply_update` rewritten to write the FULL `new.model_dump()` to disk (was only updating data_dir) so Phase 2 hot-swap fields persist. `probe_vram` implements the two-pool fix (Pitfall 2). `validate_token` four-state shim (D-05, Pitfall 3); `_head` extracted as module-level async seam for tests. `POST /diagnostics/gpu-burn` hot-swaps backend + backend_probe atomically (no X-Restart-Required; H1). 134 tests green (113 existing + 21 new).
- **Plan 02-02 (model manager + model API):** `ModelManager` owns the lifecycle: `ensure_downloaded` lazy-imports `huggingface_hub.hf_hub_download` (boundary check — only `manager.py` + `hf_token.py` import `huggingface_hub`), size fast-path, SHA verify with bounded 1-retry (Pitfall 4), `GatedRepoError` -> `ModelGatedError` (Pitfall 3). `load` re-reads settings via a factory (H1 hot-swap), enforces D-04 (`concurrent_models=False` -> `ConcurrentModelRefused` 409), probes VRAM via `probe_vram` (Pitfall 2 two-pool fix), enforces the 85% budget gate (SC-4 -> `VramBudgetExceeded` 507), records the reservation in `ManagerState.live_vram_bytes` + `loaded_meta`, emits a structured JSON INFO log line (SC-2). `unload` idempotent (D-03, no timer); `unload_all` on lifespan teardown. 5 typed errors map to 507/409/403/500 in `routes_models`. `REGISTRY` (9 entries: 3 categories x 3 presets) + `PRESETS` (`active_model_set` resolver: override > preset, HW-06) + `app.storage.models_dir` (`repo_id` sandboxes `/` -> `--` per Pitfall 4). Six `/models` routes (GET, POST download 202, GET status, GET SSE, POST load, POST unload 204). `ManagerState.loaded_meta` typed as `dict[ModelCategory, Any]` to avoid a circular import with `app.models.manager`. HW-02 lifecycle delivered (actual GPU inference is Phase 3/7/8). 151 tests green (134 existing + 17 new). HW-04, HW-07, HW-09 marked complete; HW-02 pending actual inference in Phase 3/7/8.
- **Plan 02-04 (gap-closure, SC-3 download):** `ensure_downloaded` now awaits `asyncio.to_thread(hf_hub_download, ...)` for the primary download AND the bounded retry — unfreezing the FastAPI event loop so WR-01 (409 duplicate-in-flight), WR-02 (live SSE `event:progress` + `:ping` heartbeat + byte-level progress WHILE downloading), and HW-09 (resume-after-crash) hold live. The classic non-Xet HF download path is forced via `hf_xet=False` (version-gated through `inspect.signature`, huggingface_hub>=0.26) with an `HF_HUB_DISABLE_XET=1` env-var fallback for older versions, so the `.incomplete` + HTTP Range resume the `_poll_bytes` scanner assumes actually applies. New `slow_mock_hf_hub_download` conftest fixture (thread-blocking incremental-write side_effect on a `threading.Event`) makes async concurrency observable — the synchronous `mock_hf_hub_download` could never catch the freeze. 5 live-behavior tests in `tests/test_download_routes.py`. 185 tests green. The 409 dedupe logic in `download_model` was correct but unreachable while the loop was frozen; the thread offload alone makes it fire.
- [Phase 02]: 02-05 SC-4 vram fix: probe_vram CPU error-fallbacks return loaded=_loaded_list(manager_state) (not loaded=[]); psutil stays a lazy in-body import; inline no_psutil+cpu_manager fixtures in test_diagnostics_api.py; pip install -e . once for psutil (declared >=5.9 but missing from runtime env - the live SC-4 trigger); 188 tests green (185 + 3 new).
- [Phase ?]: 03-01: SttSegment mirrors TranscriptSegment shape but is a separate type (D-06 layering)
- [Phase ?]: 03-01: [project.scripts] transcribe deferred to 03-03; nvidia-cu12 libs deferred to SC-5 (Codex HIGH)
- [Phase ?]: 03-01: D-08 _ACCEPTED table accepts CUDA int8->int8_float16, rejects float32 fallback; FasterWhisperAdapter is the ONLY fw/ct2 import site (SC-4)
- [Phase ?]: 03-02: Overlap-dedupe drops later-chunk segments whose abs start_s < prev_chunk_end; NO timestamp mutation (Codex HIGH stitch fix)
- [Phase ?]: 03-02: OOM split-both-halves recursive retry transcribes BOTH halves (Codex HIGH full-coverage fix); FLOOR_SECONDS=60 bounds depth at ~4 (T-03-04)
- [Phase ?]: 03-02: STTAdapter Protocol gained decode_audio so the chunker decodes without importing faster_whisper (SC-4 preserved)
- [Phase ?]: 03-02: condition_on_previous_text=False per chunk (chunked), True (<=30 min fast path) -- Pitfall 8 planner decision
- [Phase ?]: 03-03: Standalone transcribe CLI + [project.scripts] entry declared HERE (Codex HIGH); --device auto resolves CUDA/CPU from settings via device_for (SC-5); _bootstrap_settings + _get_or_configure_manager close the PATTERNS CLI gap; finally-block adapter.unload(); raw RuntimeError preserved to stderr; SC-5 desktop CPU half VERIFIED (3.09GB snapshot, 20 segs, en), laptop CUDA half DEFERRED; cross-phase manager fix 051b0302 (file=None repos -> snapshot_download) surfaced by SC-5
- [Phase 04]: Plan 04-01: JobCancelled in neutral app/jobs/errors.py (Fix 5); cancel_flag is threading.Event (NOT asyncio.Event); run_job re-raises non-cancel exceptions after mark_failed but swallows JobCancelled; heartbeat via progress.json mtime + _STAGE_FILE_NAMES inclusion (no os.utime on job_dir).
- [Phase 04]: Plan 04-02: pull_next uses conditional UPDATE WHERE status='queued' + rowcount check (Fix 6 atomic claim); run_worker uses hybrid Event+poll wakeup asyncio.wait_for(_work_signal.wait(), timeout=2.0) (Fix 1); boot sweep mark_interrupted_failed writes manifest via atomic_write_json (update_stage maps 'failed'->'queued' incorrectly so the documented fallback is used); cancel running path sets _running flag only (no double cancel_job, T-04-06); watchdog excludes queued (Codex MEDIUM); 'starting' added to JobStatus Literal (transient claim state); lifespan teardown cancels worker+watchdog before engine.dispose; app.state.bus/settings/session_factory established (Fix 7-partial).
- [Phase 04]: CR-03 closed (plan 04-04): additive resume_stage == 'done' branch in run_job advances crash-window jobs (transcript.json on disk, current_stage != 'done') to done on re-entry; happy path and no-op path unchanged; full 39-test phase suite green
- [Phase 04]: CR-01 + CR-02 closed (plan 04-05): boot-sweep (mark_interrupted_failed) + watchdog (run_watchdog) SELECT widened to `status IN ('starting','ingesting','transcribing')` so a crashed-in-claim `starting` job is recovered on the next boot (CR-01); mark_interrupted_failed consults infer_resume_point per swept job and advances to done via update_stage('done') when resume_point is None or 'done' (transcript.json on disk, current_stage='transcribed', DB status='transcribing'), preserving the user's completed transcription (CR-02); a `starting` job is correctly FAILED (infer_resume_point returns 'ingested', not None/'done'); filter-widening approach chosen over zero-width 'starting' window to avoid changing 04-01's orchestrator wiring; full 41-test phase suite green (39 prior + 2 new)
- [Phase 04]: Plan 04-06 (WR-04): post_cancel rewired to queue.cancel (cooperative path) instead of cleanup.cancel_job; {} -> 404, terminal-no-op 200 (D-06 idempotent), running sets _running flag (orchestrator's JobCancelled path does cancel_job + rmtree); full 44-test phase suite green

### Pending Todos

None yet.

None yet.

### Blockers/Concerns

Research-flagged unknowns that affect upcoming phases:

- Phase 2: ROCm on Windows for the 6800 XT in mid-2026 — cannot be verified at research time; first-run GPU-burn test must be the ground truth.
- Phase 6: yt-dlp state for age-gated / region-locked videos in mid-2026.
- Phase 7: pyannote "expected N speakers" mode exact knob and reliability.
- Phase 8: Qwen2.5 vs Llama-3 vs Mistral benchmark on laptop + GBNF grammar expressibility for the four templates.

## Deferred Items

Items acknowledged and carried forward from project initialization:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Export | SRT / VTT / JSON / ASS subtitle export | v2 | 2026-06-11 |
| Summarization | User-defined custom summary templates | v2 | 2026-06-11 |
| Summarization | Per-segment confidence score with review view | v2 | 2026-06-11 |
| Discovery | AI chat with the transcript (RAG) | v2 | 2026-06-11 |
| Discovery | Auto-generated chapter markers / key moments | v2 | 2026-06-11 |

## Session Continuity

Last session: 2026-06-23T08:38:40.397Z
Stopped at: Completed 04-05-PLAN.md (CR-01 + CR-02 gap closure)
Resume file: None

### Gap-closure wave (01-04) — closed

All 5 HIGH + 3 MEDIUM findings from the Codex implementation review are fixed in the code and covered by tests:

- H1: Restart-only settings semantics — `pending` slot + `apply_pending()` in lifespan. **Done.**
- H2: OpenAPI 201 references `JobResponse` (not `JobManifest`). **Done.**
- H3: `status` projected to DB on every stage transition via `stage_to_status()`. **Done.**
- H4: Manifest patches (language, duration, summary_kinds, source_*) projected to DB on every stage transition + on boot via `reconcile_all`. **Done.**
- H5: `create_job` orphan-row compensation (DELETE on folder/manifest failure). **Done.**
- M1: Pydantic-validated stage files (Transcript / Diarization / Summary) in `parse_stage_file`. **Done.**
- M2: Zero-byte `source.*` rejection. **Done.**
- M3: Status-aware stale check (skip `done` / `failed` / `cancelled`). **Done.**

### Test additions (all done)

- Direct WAL test (open 2 connections, assert journal_mode=wal on both) — `tests/test_wal.py`
- Migration triple-apply idempotency + partial-apply recovery — `tests/test_migration_idempotency.py`
- `data_dir` PATCH restart-only — `tests/test_settings.py` + `tests/test_settings_restart_required_header.py`
- `data_dir: null` / empty / relative / file-path rejection — `tests/test_data_dir_validation.py` + `tests/test_settings.py`
- OpenAPI: assert the 201 operation response schema is `JobResponse`, not `JobManifest` — `tests/test_post_jobs_201_response.py` + `tests/test_openapi.py`
- Stage-to-status transitions: enumerated matrix — `tests/test_stage_to_status.py`
- Manifest patch projection: PATCH `language="en"`, then `GET /jobs/{id}` returns `language="en"` — `tests/test_manifest_patch.py` + `tests/test_manifest_helpers.py`
- Resume on `{}` / corrupt / zero-byte files — `tests/test_resume.py`
- Stale check on `done` / `failed` / `cancelled` rows is a no-op — `tests/test_cleanup.py`

### Next command when resuming

```
/gsd-verify-phase 1
```

Then plan Phase 2 (transcription pipeline) once Phase 1 verification passes.
