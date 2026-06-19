---
phase: 02-gpu-backend-detection-model-manager
plan: 04
subsystem: model-manager
tags: [models, huggingface-hub, download, asyncio, sse, concurrency, fastapi, resume]

# Dependency graph
requires:
  - "02-02: ModelManager.ensure_downloaded (sync hf_hub_download), routes_models._run_download / download_model / download_progress_sse, _in_flight dedupe"
provides:
  - "app.models.manager.ensure_downloaded offloads hf_hub_download via asyncio.to_thread + forces the classic non-Xet resume path (hf_xet=False, HF_HUB_DISABLE_XET=1 fallback) so the event loop stays responsive and .incomplete + HTTP Range resume applies"
  - "app.api.routes_models: 409 duplicate-in-flight (WR-01), live SSE event:progress + :ping heartbeat + byte-level progress WHILE downloading (WR-02), resume-after-crash (HW-09) now hold live"
  - "tests.conftest.slow_mock_hf_hub_download: thread-blocking incremental-write side_effect controlled by a threading.Event so concurrency tests observe the in-flight state past the 5s heartbeat threshold"
  - "tests.test_download_routes: 5 live-behavior tests locking the SC-3 contract that the mocked 155-test suite missed"
affects:
  - "Phase 3/7/8: STT/diarize/LLM adapters call ensure_downloaded before inference; the thread offload keeps the API responsive during large model pulls"
  - "Phase 5: React UI consumes the live SSE download-progress stream (now emits real frames while downloading)"
tech-stack:
  added: []
  patterns:
    - "Offload blocking sync calls (hf_hub_download) via asyncio.to_thread so the FastAPI event loop stays responsive for dedupe + SSE + polling"
    - "Force the classic non-Xet HF download path (hf_xet=False on huggingface_hub>=0.26, else HF_HUB_DISABLE_XET=1 env var) so the .incomplete + HTTP Range resume mechanism the code assumes actually applies; version-gated via inspect.signature"
    - "Slow in-flight test mock (threading.Event + incremental byte writes every ~0.5s in a worker thread) to make async concurrency observable — the synchronous mock_hf_hub_download fixture could never catch the event-loop freeze"
key-files:
  created:
    - tests/test_download_routes.py
  modified:
    - app/models/manager.py
    - app/api/routes_models.py
    - tests/conftest.py
decisions:
  - "hf_xet=False is passed when the installed huggingface_hub supports it (detected via inspect.signature at call time, >=0.26); on older versions the HF_HUB_DISABLE_XET=1 env var is set around the call and restored after. This keeps the classic .incomplete + Range resume path on every supported version without a hard version bump."
  - "Kept the RED source-contract test (test_hf_hub_download_is_offloaded_to_thread, AST-based) as a permanent guard alongside the 4 live-behavior tests, so a future regression to a direct sync hf_hub_download call fails fast."
  - "Did NOT modify the 409 dedupe logic in download_model — it was correct but unreachable while the event loop was frozen; the thread offload alone makes it fire."
key-decisions:
  - "Offload hf_hub_download via asyncio.to_thread; force classic non-Xet resume path (hf_xet=False / HF_HUB_DISABLE_XET=1); keep RED AST source-contract test as a guard"
patterns-established:
  - "asyncio.to_thread offload for blocking HF downloads"
  - "Version-gated hf_xet=False with HF_HUB_DISABLE_XET=1 env fallback"
  - "Slow in-flight threading.Event mock for live async-concurrency tests"
requirements-completed: [HW-09]

# Metrics
duration: ~28min
completed: 2026-06-19
tasks: 2
files: 4
tests_added: 5
tests_total: 185
---

# Phase 02 Plan 04: SC-3 download defect fix -- thread-offloaded hf_hub_download + classic non-Xet resume Summary

`ensure_downloaded` now awaits `asyncio.to_thread(hf_hub_download, ...)` for both the primary download and the bounded retry, unfreezing the FastAPI event loop so WR-01 (409 duplicate-in-flight), WR-02 (live SSE heartbeat + byte-level progress WHILE downloading), and HW-09 (resume-after-crash) all hold live; the classic non-Xet HF download path is forced (`hf_xet=False` on >=0.26, `HF_HUB_DISABLE_XET=1` fallback) so the `.incomplete` + HTTP Range resume the scanner assumes actually applies.

## Performance

- **Duration:** ~28 min (08:32 -> 09:00 local)
- **Started:** 2026-06-19T06:32:00Z
- **Completed:** 2026-06-19T07:00:03Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Offloaded both `hf_hub_download` calls in `ensure_downloaded` (primary + bounded retry) to `asyncio.to_thread` so the event loop stays responsive during downloads (zero direct sync `hf_hub_download` Call nodes remain -- AST gate passes).
- Forced the classic non-Xet resume path via `hf_xet=False` (version-gated via `inspect.signature`, huggingface_hub>=0.26) with an `HF_HUB_DISABLE_XET=1` env-var fallback for older versions, so `.incomplete` + HTTP Range resume applies and the `_poll_bytes` scanner sees real staging files.
- Added 5 live-behavior tests (`tests/test_download_routes.py`) + a `slow_mock_hf_hub_download` conftest fixture (thread-blocking incremental-write side_effect controlled by a `threading.Event`) that lock the SC-3 contract the mocked 155-test suite missed: 409 duplicate-in-flight, live SSE `event: progress` + `: ping` heartbeat while in-flight, byte-level progress, and classic-path resume.

## Task Commits

Each task was committed atomically (TDD: RED -> GREEN -> live tests):

1. **Task 1 RED: failing source-contract test for hf_hub_download offload** - `243362b` (test)
2. **Task 1 GREEN: offload hf_hub_download to thread + force classic non-Xet path** - `7dc1dec` (feat)
3. **Task 2: live 409 + SSE + resume tests for SC-3 contract** - `eae3776` (test)

## Files Created/Modified
- `app/models/manager.py` - `ensure_downloaded` now awaits `asyncio.to_thread(hf_hub_download, ...)` for the primary download and the bounded retry; imports `asyncio`; version-gated `hf_xet=False` / `HF_HUB_DISABLE_XET=1` forces the classic non-Xet resume path; docstring updated to reflect the forced classic path.
- `app/api/routes_models.py` - `_run_download` await line unchanged (`await manager.ensure_downloaded(spec, category)`); the event loop is now responsive so 409 dedupe + SSE heartbeat + byte progress run concurrently. (Minor adjustment in `eae3776` to align with the offloaded path.)
- `tests/conftest.py` - new `slow_mock_hf_hub_download` fixture: patches `huggingface_hub.hf_hub_download` with a plain-`def` thread-blocking side_effect that writes byte increments to `<filename>.incomplete` every ~0.5s and blocks on a `threading.Event` until released, so the download stays in-flight past the 5s heartbeat threshold. The existing synchronous `mock_hf_hub_download` is untouched.
- `tests/test_download_routes.py` (new) - 5 tests: `test_hf_hub_download_is_offloaded_to_thread` (AST source-contract), `test_download_duplicate_in_flight_returns_409` (WR-01), `test_download_progress_sse_streams_live` (WR-02 heartbeat + progress while in-flight), `test_download_progress_byte_level` (byte-level progress), `test_resume_after_crash_uses_classic_path` (HW-09).

## Decisions Made
- `hf_xet=False` is passed when the installed `huggingface_hub` supports it (detected via `inspect.signature` at call time, >=0.26); on older versions `HF_HUB_DISABLE_XET=1` is set in `os.environ` around the call and restored after. Keeps the classic `.incomplete` + Range resume path on every supported version without a hard dependency bump.
- Kept the RED source-contract test as a permanent AST guard alongside the 4 live-behavior tests, so a future regression to a direct sync `hf_hub_download` call fails fast.
- Did NOT modify the 409 dedupe logic in `download_model` -- it was correct but unreachable while the event loop was frozen; the thread offload alone makes it fire.

## Deviations from Plan

None that change scope. The plan specified 4 new live-behavior tests; the executor added a 5th -- the AST source-contract test from the Task 1 RED commit was retained as a permanent guard rather than discarded after GREEN. This is strictly additive (better regression coverage) and matches TDD discipline. The `hf_xet=False` implementation is version-gated (the plan offered `hf_xet=False` OR `HF_HUB_DISABLE_XET=1`; the executor does both with a runtime version check), which is a more robust realization of the same must-have.

## Issues Encountered
- The executor subagent stalled after committing all three atomic commits: its final turn was "I'll wait for the background test run to finish" and it returned without writing SUMMARY.md or updating tracking. The orchestrator recovered by spot-checking commits (all three present), running the full suite itself (185 passed, exit 0), running the plan's AST verification gate (`ok`), and writing this SUMMARY + tracking inline. No implementation work was lost.

## User Setup Required
None - no external service configuration required. asyncio is stdlib; huggingface_hub already declared in pyproject.toml (>=0.25). No new dependencies.

## Next Phase Readiness
- SC-3 blocker resolved: the live download UX contract (409, live SSE, byte progress, resume) holds and is locked by tests.
- Ready for 02-05 (SC-4 vram indicator) in the same wave -- no file overlap (02-05 touches `app/models/vram.py` + `tests/test_diagnostics_api.py`).
- Phase 3 inference adapters can rely on a responsive download path; the ROCm-on-Windows GPU blocker (separate concern, paused by user before Phase 3) is unaffected -- this plan only touches the download/event-loop layer.

---
*Phase: 02-gpu-backend-detection-model-manager*
*Completed: 2026-06-19*