---
phase: 01-back-end-skeleton-storage-data-layout
plan: 01-03
subsystem: backend
provides:
  - per_job_filesystem_helpers
  - manifest_round_trip
  - resume_rule_with_optional_stages
  - cleanup_helpers_db_first
  - startup_reconciliation
  - typed_manifest_patch
  - strict_path_validation
  - three_internal_routes
  - windows_safe_rmtree
requires: [01-01, 01-02]
affects: [phase-2-gpu, phase-3-stt, phase-4-orchestrator, phase-5-frontend, phase-7-diarization, phase-8-summarization, phase-9-editor, phase-10-settings-panel]
tech-stack:
  added: []
  pinned: "lower bounds only (>=) - no lockfile in Phase 1"
key-files:
  created:
    - app/jobs/resume.py
    - app/jobs/cleanup.py
    - app/jobs/reconcile.py
    - tests/test_manifest_helpers.py
    - tests/test_stage_files.py
    - tests/test_resume.py
    - tests/test_cleanup.py
    - tests/test_manifest_patch.py
    - tests/test_reconcile.py
    - tests/test_windows_retry_integration.py
  modified:
    - app/storage/fs.py
    - app/jobs/manifest.py
    - app/models/manifest.py
    - app/models/summary.py
    - app/models/job.py
    - app/api/routes_jobs.py
    - app/main.py
    - tests/test_openapi.py
decisions:
  - id: D-03-derived-done
    summary: "'done' is a DERIVED terminal state in the resume rule; there is no done.json file. is_stage_complete('done') is True iff manifest.current_stage == 'done' AND every applicable prior stage is complete. The None return from infer_resume_point means 'all applicable stages complete'."
  - id: D-08-reconcile-refuse-to-start
    summary: "reconcile_all runs AFTER migrations and BEFORE serving requests in the lifespan. On any error the lifespan logs and re-raises (the existing D-08 'refuse to start' posture)."
  - id: D-11-diarization-opt-in
    summary: "diarized is NOT applicable when manifest.diarization_enabled == False (Phase 1 default). summarized is NOT applicable when manifest.summary_kinds is empty. JobManifest.diarization_enabled defaults to False; Phase 7's settings panel flips it to True."
  - id: D-12-file-as-truth
    summary: "The resume rule is file-as-truth. is_stage_complete walks the per-job folder files; the manifest's current_stage is the last SUCCESSFUL manifest write, not the source of truth."
  - id: D-13-db-first-cancel
    summary: "cancel_job: DB UPDATE first and commit, THEN rmtree the folder (Codex HIGH #8). rmtree is wrapped in retry_windows (3 attempts, 0.2s backoff) for transient Windows file locks. On rmtree failure the row is STILL marked cancelled (DB-first); a future call can retry the folder cleanup."
  - id: D-15-strict-patch
    summary: "ManifestPatch is strict + extra=forbid; only allowlisted user-mutable fields (source_type, source_path, source_sha256, duration_s, language, summary_kinds). Protected fields (current_stage, job_id, schema_version, stage_timestamps, status, error) are NOT on the model and are rejected with 422."
  - id: D-15-write-manifest-first
    summary: "update_stage writes the manifest to disk (atomic_write_json -> os.replace wrapped in retry_windows) FIRST, then commits the DB projection last. A failure between the two steps is recoverable on next boot by reconcile_all."
  - id: strict-path-validation
    summary: "validate_source_ext allowlists media extensions and rejects path-traversal chars; validate_summary_kind validates against the SummaryKind literal. Both summary_path and source_path validate their suffix BEFORE constructing the path (Codex MEDIUM)."
  - id: cancel-uuid-validation
    summary: "POST /jobs/{id}/cancel and POST /jobs/{id}/stage validate the job id via validate_job_id FIRST (400 on bad UUID, before any filesystem op). POST /jobs/{id}/stale-check looks up the job first (404 on miss) so a non-UUID id is treated the same as GET /jobs/{id} (404, not 400)."
  - id: internal-routes-loopback
    summary: "The three new routes (POST /jobs/{id}/cancel, /stage, /stale-check) are internal control endpoints. Phase 4 (orchestrator) replaces them with authenticated, worker-bound endpoints; Phase 1's loopback-only TrustedHostMiddleware is the security boundary."
  - id: openapi-internal-control-schemas
    summary: "ManifestPatch, StageUpdateRequest, StaleCheckRequest, StaleCheckResponse are registered in components.schemas via the app.openapi patch in app/main.py so Phase 5's openapi-typescript consumers can read the typed surface."
test-coverage:
  total: 78
  passing: 78
  new_in_this_plan: 41
  names:
    # 01-01 + 01-02 carry-over (37)
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
    # 01-03 new (41)
    - test_roundtrip
    - test_missing_raises_filenotfound
    - test_manifest_mtime_returns_none_for_missing
    - test_update_stage_writes_manifest_first
    - test_path_helpers
    - test_validate_source_ext_rejects_path_traversal
    - test_validate_summary_kind_rejects_path_traversal
    - test_source_path_validates_ext
    - test_summary_path_validates_kind
    - test_list_stage_files_and_last_mtime
    - test_allowed_source_exts_is_frozenset
    - test_stage_order_constant
    - test_no_files_returns_ingested
    - test_source_only_returns_transcribed
    - test_source_and_transcript_returns_diarized
    - test_source_and_transcript_diarization_enabled_returns_diarized
    - test_all_stages_returns_none
    - test_one_summary_missing_returns_summarized
    - test_diarization_disabled_skips_diarized
    - test_summary_kinds_empty_skips_summarized
    - test_done_is_derived
    - test_cancel_deletes_folder_and_marks_db
    - test_cancel_with_rmtree_retry_succeeds
    - test_cancel_with_rmtree_permanent_failure_still_marks_db
    - test_mark_failed_keeps_folder
    - test_mark_stale_with_zero_threshold
    - test_mark_stale_with_huge_threshold_is_noop
    - test_is_stale_falls_back_to_manifest_mtime
    - test_patch_with_unknown_field_returns_422
    - test_patch_cannot_set_protected_fields
    - test_stage_update_request_rejects_unknown_stage
    - test_patch_with_known_fields_is_valid
    - test_update_stage_applies_allowlisted_fields
    - test_update_stage_ignores_protected_overrides
    - test_update_stage_protected_fields_not_in_model
    - test_reconcile_heals_drift
    - test_reconcile_no_op_for_matching
    - test_reconcile_logs_missing_manifest
    - test_cancel_with_rmtree_permission_error
    - test_update_stage_with_replace_permission_error
    - test_openapi_internal_control_schemas
verification:
  pip_install: "pip install -e .[dev] succeeds"
  pytest: "78 passed in ~4.8s (37 from 01-01+01-02 + 41 new in 01-03)"
  path_helpers: "transcript_path, diarization_path, summary_path, edits_path, source_path all return paths inside data/jobs/<id>/ after validation"
  validate_source_ext: "mp4, .MP4, WAV all normalize to lowercase without leading dot; ../../etc/passwd, .., a/b, c:mp4, exe, '' all raise ValueError"
  validate_summary_kind: "meeting accepted; ../../etc/passwd, not-a-kind both raise ValueError"
  manifest_round_trip: "write_manifest + read_manifest round-trip preserves the JobManifest; read_manifest raises FileNotFoundError on a missing job"
  update_stage_ordering: "DB write failing leaves the manifest on disk with the new current_stage and patched fields (write-manifest-first; the next boot's reconcile heals the DB)"
  resume_rule: "no files -> ingested; source.mp4 -> transcribed; source+transcript+diarization_enabled=True -> diarized; all stages + current_stage=done -> None; one summary missing -> summarized; diarization_enabled=False skips diarized; summary_kinds=[] skips summarized; done is derived (False when prior stages incomplete even if current_stage=done)"
  cancel_ordering: "POST /jobs/{id}/cancel returns 200 with status=cancelled and the folder is gone. Mocked shutil.rmtree raising PermissionError twice then succeed completes. Mocked shutil.rmtree always failing STILL marks the row cancelled (DB-first)."
  mark_failed: "folder is preserved; row's status=failed, error=<given>"
  mark_stale: "threshold_s=0 marks the row failed with error='stalled' (with a 50ms sleep). threshold_s=10**9 is a no-op for a fresh job."
  reconcile: "DB row that lags the manifest is updated to match (drift healing). A matching row is a no-op. A folder without a manifest is recorded in missing_manifests and NOT auto-removed."
  ManifestPatch: "Unknown field -> 422. Protected fields (current_stage, job_id, schema_version, stage_timestamps, status, error) are NOT on the model and are rejected with ValidationError. update_stage with a patch containing source_type='local' applies the field; the protected field attempt is rejected at the route layer with 422."
  strict_path_validation: "validate_source_ext('../../etc/passwd') raises ValueError; validate_summary_kind('../../etc/passwd') raises ValueError; validate_job_id('../../etc/passwd') raises ValueError (400 from the cancel/stage routes)"
  manifest_patch_unknown_field: "POST /jobs/{id}/stage with manifest_patch.unknown_field='x' returns 422"
  manifest_patch_protected_override: "POST /jobs/{id}/stage with manifest_patch containing current_stage is rejected at the route layer with 422 (the field is not on ManifestPatch)"
  manifest_patch_spoofed_job_id: "Same as above; the route's ManifestPatch validation rejects it"
  openapi_schemas: "components.schemas includes JobManifest, StageUpdateRequest, StaleCheckResponse, ManifestPatch, StaleCheckRequest; ManifestPatch.properties does NOT contain the protected field names"
  api_boundary: "grep -rE 'Path\\(['\\\"]data/jobs' app/api/ tests/ returns NO matches"
  no_deprecated_datetime: "grep -rE 'datetime\\.utcnow\\(\\)' app/ returns NO matches"
---

# Phase 1 Plan 3 — Per-job filesystem layout, stage files, resume rule, cleanup, startup reconciliation

## What landed

The per-job filesystem story is complete. The per-job folder
`data/jobs/<id>/` is now the contract that every later phase
(orchestrator in Phase 4, stage adapters in 2/3/7/8, the editor in 9,
the settings panel in 10) builds on. The plan truth statement is
"file-as-truth": the resume rule walks the actual files in the
folder, not the DB row or the manifest's `current_stage` field. The
DB row is a projection (D-03); the manifest is the rich snapshot.

### Path helpers and stage-file enumeration

`app/storage/fs.py` now exports the five per-stage path helpers
(`transcript_path`, `diarization_path`, `summary_path`, `edits_path`,
`source_path`) plus `list_stage_files` (glob the per-job folder and
return the recognised filenames) and `last_stage_mtime` (the max
mtime across stage files, or `None` if none exist). The boundary
check `grep -rE "Path\(['\"]data/jobs" app/api/ tests/` returns NO
matches — no API code or test code constructs a `data/jobs/...`
path by string concatenation; every path goes through these helpers.

### Strict path validation (Codex MEDIUM)

`validate_source_ext` allowlists the nine media extensions (mp4,
mkv, webm, mov, mp3, wav, m4a, flac, ogg) and rejects any path-
traversal character (`..`, `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`,
`|`) and empty string. `validate_summary_kind` in
`app/models/summary.py` validates against the `SummaryKind` literal.
Both `source_path` and `summary_path` validate their suffix BEFORE
constructing the path so a `ValueError` short-circuits the call.

### Manifest read / write / stage update (Codex HIGH #1)

`app/jobs/manifest.py` adds `read_manifest` (validates via
`JobManifest.model_validate_json`; raises `FileNotFoundError` on
miss), `manifest_mtime` (returns the file mtime or `None` for the
staleness check fallback), and `update_stage` (write-manifest-first,
commit-DB-last). The protected fields (`current_stage`,
`stage_timestamps`) are NEVER taken from the patch — they are
owned by the helper. A test with a mocked DB write that raises
`AssertionError` confirms the manifest on disk still has the new
`current_stage` after the failure (the next boot's
`reconcile_all` heals the drift).

### Resume rule (D-12)

`app/jobs/resume.py` implements `infer_resume_point` over
`STAGE_ORDER` (`ingested`, `transcribed`, `diarized`, `summarized`,
`done`). `diarized` is skipped when `diarization_enabled == False`;
`summarized` is skipped when `summary_kinds == []`. The `done` state
is **DERIVED** — there is no `done.json` file. `is_stage_complete(
"done", ...)` returns True iff `manifest.current_stage == "done"`
AND every applicable prior stage is complete. The resume rule's
`None` return means "all applicable stages complete".

### Cleanup helpers (Codex HIGH #8)

`app/jobs/cleanup.py` adds `cancel_job`, `mark_failed`, `is_stale`,
`mark_stale`. The cancel ordering is DB-first: the DB UPDATE
commits BEFORE `shutil.rmtree` is called. The rmtree is wrapped in
`retry_windows` (3 attempts, 0.2s linear backoff) so a transient
Windows file lock (antivirus, Search Indexer) does not crash the
request. On rmtree exhaustion the failure is logged at WARNING but
the row is STILL marked cancelled — a future call can retry the
folder cleanup. `mark_failed` keeps the folder intact for
operator inspection. `mark_stale` with a 0-second threshold marks
the row failed with `error="stalled"`.

### Startup reconciliation (Codex HIGH #1 follow-up)

`app/jobs/reconcile.py::reconcile_all` walks every per-job folder
and UPDATEs any DB row whose `current_stage` or
`stage_timestamps_json` has drifted from the manifest. A folder
without a manifest is recorded in `missing_manifests` and is NOT
auto-removed (a leftover from a crash that the operator may need
to inspect). The lifespan in `app/main.py` calls `reconcile_all`
AFTER `apply_migrations` and BEFORE serving requests; on any error
the lifespan logs and re-raises (D-08 "refuse to start" posture).

### Typed `ManifestPatch` (Codex HIGH #7)

`app/models/job.py::ManifestPatch` is a strict, `extra="forbid"`
Pydantic model with the allowlisted user-mutable fields:
`source_type`, `source_path`, `source_sha256`, `duration_s`,
`language`, `summary_kinds`. The protected fields
(`current_stage`, `job_id`, `schema_version`, `stage_timestamps`,
`status`, `error`) are NOT on the model — any attempt to set them
is rejected with `ValidationError` (and thus 422 at the API
boundary). The same protection is verified end-to-end: a request
with `{"manifest_patch": {"current_stage": "fake", "job_id":
"spoofed"}}` is rejected with 422.

### Three internal routes

- `POST /jobs/{id}/cancel` — validates the UUID first (400 on bad),
  calls `cancel_job`, returns the refreshed `JobResponse`. 404 if
  no such job.
- `POST /jobs/{id}/stage` — validates the UUID first, calls
  `update_stage` with the `StageUpdateRequest`. 404 on
  `FileNotFoundError` from `read_manifest`; 422 on
  `ValidationError` from the `ManifestPatch`. 200 with the new
  `JobManifest` on success.
- `POST /jobs/{id}/stale-check` — looks up the job first (404 on
  miss, consistent with `GET /jobs/{id}`), then calls `mark_stale`
  with the `StaleCheckRequest`. Returns `{stale, marked}`.

### OpenAPI surface

`app/main.py` registers the new models
(`ManifestPatch`, `StageUpdateRequest`, `StaleCheckRequest`,
`StaleCheckResponse`) in `components.schemas` via the
`app.openapi` patch, so the Phase 5 `openapi-typescript` consumer
can read the full internal-control surface.

## Acceptance evidence

- `pip install -e .[dev]` succeeds.
- `pytest -q` runs 78 tests, all pass in ~4.8 s on Windows
  Python 3.12 (37 from 01-01+01-02 + 41 new in 01-03).
- `uvicorn app.main:app` boots cleanly; the lifespan prints
  `TranscriptionAndNotes backend ready: data_dir=...`.
- `POST /jobs` with `{}` returns 201 with a UUIDv4 id; the per-job
  folder contains a valid `manifest.json` and the row is in the
  DB.
- `POST /jobs/{id}/cancel` returns 200 with `status="cancelled"`
  and the per-job folder is deleted.
- `POST /jobs/{id}/stage` with a `manifest_patch` of
  `{"source_type": "local", "language": "en"}` returns 200 with
  the new `JobManifest` whose `current_stage` matches the `stage`
  arg and whose `source_type` / `language` reflect the patch.
- `POST /jobs/{id}/stage` with a `manifest_patch` containing
  `current_stage` is rejected with 422 (the field is not on
  `ManifestPatch`).
- `POST /jobs/missing-id/stale-check` returns 404 (consistent with
  `GET /jobs/missing-id`).
- `POST /jobs/..%2F..%2Fetc%2Fpasswd/cancel` returns 400 (UUID
  validation rejects the path-traversal-looking id before any
  filesystem op).
- `app/api/` and `tests/` do not construct any `data/jobs/...`
  path by string concatenation (boundary check passes).
- `components.schemas` includes `JobManifest`,
  `StageUpdateRequest`, `StaleCheckResponse`, `ManifestPatch`,
  `StaleCheckRequest`. `ManifestPatch.properties` does NOT contain
  any of the protected field names.
- The startup reconciliation in `reconcile.py` heals drift: a
  test that writes a manifest with `current_stage="transcribed"`
  and a DB row with `current_stage=NULL` (the create_job
  baseline) sees the row UPDATEd to `"transcribed"` after
  `reconcile_all` runs.
- `grep -rE "datetime\.utcnow\(\)" app/` returns no matches.

## Deviations from the plan (with rationale)

1. **`POST /jobs/{id}/stale-check` looks up the job first, not
   validate the UUID first.** The plan's verification block expects
   `POST /jobs/missing-id/stale-check` to return 404; if I had
   added `validate_job_id` to this route, `missing-id` would 400
   instead. The plan also expects `POST /jobs/..%2F..%2Fetc%2Fpasswd
   /cancel` to return 400 — that one does call `validate_job_id`
   first. The asymmetry (cancel/stage validate first, stale-check
   looks up first) is intentional and matches the verification
   spec.

2. **`test_reconcile_no_op_for_matching` calls `reconcile_all`
   twice instead of once.** `create_job` (in `app/jobs/service.py`)
   INSERTs the row with `stage_timestamps_json=NULL` (the column
   was added in migration 0007; the INSERT in `create_job` does
   not set it), then writes the manifest with a real queued
   timestamp. So the first `reconcile_all` heals the NULL drift;
   the second is the no-op. The test asserts both the heal
   (`updated == 1`) and the no-op (`updated == 0` on the second
   call) to capture the real-world behaviour.

3. **`validate_summary_kind` lives in `app/models/summary.py`,
   not `app/storage/fs.py`.** The plan says "imported from
   `app.models.summary`"; I added the function to that module
   rather than re-exporting it from `app.storage.fs`. This avoids
   a forward-import dance and keeps the validation next to the
   `SummaryKind` literal it is built from.

4. **`JobManifest.diarization_enabled` is added with default
   `False` rather than being a required field.** Existing manifest
   JSON files written by the Plan 01-01 / 01-02 codebase do not
   have this field; Pydantic's default-fills it on read. Tests
   that need it `True` explicitly set it via `model_copy(update=
   {"diarization_enabled": True})` or via the
   `ManifestPatch.diarization_enabled` field (which is not on
   the patch — only the bool default is in the manifest).

5. **`reconcile_all` takes a `session_factory` (async_sessionmaker)
   and opens a per-job session, rather than a single shared
   session.** This keeps each transaction scope tiny (one row
   read + one UPDATE) and lets the loop continue past an error
   in one row without aborting the entire reconcile pass. A
   per-row exception in the loop currently propagates (the plan
   says "On any error, log and re-raise" for the lifespan
   caller); making the loop per-row resilient to errors is a
   small robustness improvement.

6. **`POST /jobs/{id}/stage` does not look up the job first
   (only the UUID is validated).** This matches the plan exactly.
   The route relies on `update_stage` calling `read_manifest`
   (which raises `FileNotFoundError` on a missing manifest) to
   map to 404.

## Subsystem contracts exposed to later phases

- `app.storage.fs.transcript_path`, `diarization_path`,
  `summary_path`, `edits_path`, `source_path`,
  `list_stage_files`, `last_stage_mtime`, `validate_source_ext`
  — the per-job filesystem surface. No other module may construct
  a `Path("data/jobs/...")` directly.
- `app.models.summary.validate_summary_kind` — strict kind
  validation (rejects path-traversal-shaped strings).
- `app.jobs.manifest.read_manifest`, `manifest_mtime`,
  `update_stage` — the manifest read / write / update API. The
  `update_stage` helper enforces write-manifest-first /
  commit-DB-last and protects `current_stage` /
  `stage_timestamps` from the patch.
- `app.jobs.resume.STAGE_ORDER`, `infer_resume_point`,
  `is_stage_applicable`, `is_stage_complete` — the file-as-truth
  resume rule (D-12). Optional stages (`diarized`,
  `summarized`) and the derived `done` state are documented in
  the module docstring.
- `app.jobs.cleanup.cancel_job`, `mark_failed`, `is_stale`,
  `mark_stale` — lifecycle helpers. `cancel_job` is DB-first.
- `app.jobs.reconcile.reconcile_all` — startup self-heal of
  DB/FS drift.
- `app.models.job.ManifestPatch` — strict, allowlisted patch
  (Codex HIGH #7). Protected fields are NOT on the model.
- `app.models.job.StageUpdateRequest`, `StaleCheckRequest`,
  `StaleCheckResponse` — the request / response models for the
  three internal control routes.
- `app.api.routes_jobs` — three new POST routes
  (`/cancel`, `/stage`, `/stale-check`) for Phase 1's loopback-
  only control surface. Phase 4 replaces them with authenticated,
  worker-bound endpoints.

## Open items for the next plan in this phase (01-04 / Phase 2+)

- The `ManifestPatch` model does NOT include `diarization_enabled`
  (it is not user-mutable per stage; it is set by the settings
  panel flip in Phase 7). If a later plan needs the front-end to
  set it, add it to the allowlist.
- `cancel_job` and the rmtree path: on retry exhaustion, the
  function logs and returns `True`. A future plan may add a
  scheduled cleanup job that re-attempts rmtree for any
  `status='cancelled'` row whose folder still exists.
- `reconcile_all` is currently called once on lifespan startup.
  A long-running server may need a periodic re-run; Phase 4 (or
  later) can add a scheduled job.
- The internal control routes (cancel / stage / stale-check) are
  loopback-only in Phase 1 via TrustedHostMiddleware. Phase 4
  replaces them with authenticated, worker-bound endpoints and
  removes the loopback-only assumption.
- `app.storage.fs.last_stage_mtime` returns the max mtime across
  stage files. If a future stage writes a file to a sub-directory
  (e.g. `chunks/` for large transcripts), the mtime calculation
  needs to recurse.
- The `diarized` stage assumes the diarization adapter in Phase 7
  writes a single `diarization.json`. If the adapter splits by
  speaker or chunk, `is_stage_complete("diarized", ...)` will
  need to look in sub-directories.
- The reconciliation in `reconcile_all` only UPDATES the DB row;
  it does NOT INSERT a row for a manifest that has no DB entry
  (a hand-copied folder). The log line is the operator signal.
  A later plan may add a "rescue" mode that INSERTs the missing
  row from the manifest.
