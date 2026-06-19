---
status: resolved
phase: 02-gpu-backend-detection-model-manager
source:
  - 02-01-SUMMARY.md
  - 02-02-SUMMARY.md
  - 02-03-SUMMARY.md
  - 02-04-SUMMARY.md
  - 02-05-SUMMARY.md
started: 2026-06-18T22:55:27.046Z
updated: 2026-06-19T07:40:00.000Z
mode: goal-backward
note: >
  Phase 2 is a back-end/infrastructure phase (GPU detection + model lifecycle; no UI,
  no user flow). The mvp user-flow framing does not apply — the phase Goal is not a
  User Story and there is no UI to walk. Verification is goal-backward against the 5
  ROADMAP success criteria, evidenced by the 155-test pytest run (post code-review-fix)
  plus a live cold-start boot of `uvicorn app.main:app`. Three of the 9 review fixes
  (WR-02 byte-progress, WR-04 size estimates, WR-05 pending data_dir preservation)
  are flagged "requires human verification" and are exercised by the SC-3 / SC-2 / SC-1
  checks below.
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running uvicorn. Remove/ignore any warmed settings.json so the lifespan takes the first-boot detect path. Run `uvicorn app.main:app` from scratch. Server boots without errors; first-boot detect()+burn_test() runs (CPU fallback on this box per the spike verdict — no crash, no wizard); a settings.json with `backend`+`backend_probe`+7 Phase-2 fields is written atomically; `/health` returns live data; `/openapi.json` loads and exposes the Phase-2 schemas.
result: pass
evidence:
  - User ran `uvicorn app.main:app` from scratch; server process started, lifespan took the first-boot detect path.
  - `detect: no usable GPU path found; falling back to CPU (D-06 silent)` — CPU fallback per the 02-03 ROCM_FALLBACK_TO_CPU verdict; no crash, no wizard.
  - User confirmed "it did" — startup completed and the endpoints (/health, /openapi.json Phase-2 schemas) checked out.
  - Full pytest suite: 155 passed in 118.86s (post code-review-fix baseline).

### 2. SC-1 — First-run GPU auto-detect persists backend (HW-02, HW-03)
expected: On a fresh data dir (no settings.json, or a Phase-1-shaped file lacking `backend`), booting triggers detect() + burn_test() and atomically writes settings.json with `backend` ∈ {cuda, rocm, cpu} plus a `backend_probe`. A subsequent boot (backend already set) skips re-detect. `POST /diagnostics/gpu-burn` re-runs detect+burn and hot-swaps `backend`/`backend_probe` in-memory + on disk with no restart required. `GET /settings` never returns `hf_token` (D-05); `PATCH /settings` also never returns `hf_token` (CR-02 fix).
result: pass
evidence:
  - `PATCH /settings` with a valid single-field body returns 200 with `hf_token: null` (D-05/CR-02 nulling at routes_settings.py:70-72). An initial 422 was the designed empty/no-body contract (UpdateSettingsRequest rejects no-op PATCH, settings.py:158-162), not a defect.
  - User confirmed the REST method surface (GET /settings read, PATCH /settings partial update, POST /diagnostics/gpu-burn state-mutating action) is correct as built — no design change.

### 3. SC-2 — Default model set fits 8 GB VRAM; per-model budget logged (HW-04, HW-07)
expected: The BALANCED preset (faster-whisper-large-v3 + pyannote/speaker-diarization-3.1 + Qwen2.5-7B-Instruct Q4_K_M) is the default. Loading a model emits a structured JSON INFO log line with expected_vram_mb / measured_vram_mb_after_load / total_vram_mb / available_vram_mb_after_load. The per-category overhead multipliers (LLM=1.2, STT=1.5, DIARIZE=1.2) keep the 7B (~5.15 GB in-VRAM) within the 8 GB laptop budget (0.85 * 8192 = 6963 MB). STT/diarize specs now carry `expected_size_bytes` so the budget gate is not bypassed (WR-04 fix — flagged human-verify).
result: pass
evidence:
  - Code-verified: BALANCED triple = Systran/faster-whisper-large-v3 + pyannote/speaker-diarization-3.1 + Qwen/Qwen2.5-7B-Instruct-GGUF q4_k_m (registry.py:32-58); BALANCED is the default (settings.py:73 quality_preset default).
  - Overhead multipliers LLM=1.2 / STT=1.5 / DIARIZE=1.2 (manager.py:184-186), applied at manager.py:389. Budget math: 7B → 4500 MiB × 1.2 = 5150 MB < 0.85 × 8192 = 6963 MB (manager.py:388-392). Fits.
  - WR-04: expected_size_bytes set on STT (3.0 GB, registry.py:39) and diarize (90 MB, registry.py:49) with explicit WR-04 comments; budget gate no longer bypassed (manager.py:388 uses `spec.expected_size_bytes or 0`).
  - Structured INFO log line with all four fields (event/model_id/expected_vram_mb/measured_vram_mb_after_load/total_vram_mb/available_vram_mb_after_load) at manager.py:413-428.
  - Targeted pytest: tests/test_presets.py + tests/test_vram_budget.py + tests/test_settings_phase2.py → 18 passed in 0.63s.
  - Caveat (not a defect): observing the log line live with real VRAM numbers requires the GPU path (ROCm/RX 6800 blocker). Log-line emission + budget math are test-covered, so the SC-2 contract is satisfied; live-GPU observation is a hardware prerequisite already noted in the session.

### 4. SC-3 — Download, size+SHA verify, download log, resume after crash (HW-09)
expected: `POST /models/{id}/download` returns 202 and starts a background task; `GET /models/{id}/download-progress` streams `event: progress` SSE lines with a `: ping` heartbeat. `ensure_downloaded` does a size fast-path, SHA256 verify when `expected_sha256` is set (bounded 1-retry → ModelIntegrityError on mismatch), maps GatedRepoError→403, and resumes after crash (force_download NOT passed — the library resumes via `.incomplete` + Range). Duplicate in-flight downloads are refused with 409 (WR-01 fix) and byte-level progress is reported to the SSE stream (WR-02 fix — flagged human-verify).
result: issue
reported: "1 works, 2 never triggers, 3 and 4 request gets trough only after model is downloaded, 5 worked, 6 canceled mid download, got error, it didnt resume. (KeyboardInterrupt traceback in xet_get -> hf_hub_download during _run_download -> ensure_downloaded.)"
severity: blocker
evidence:
  - Step 1 (POST /models/small.stt/download -> 202): PASS.
  - Step 2 (duplicate in-flight -> 409, WR-01): FAILED — second POST never returned 409; the event loop was blocked by the sync hf_hub_download call so the request was not serviced until the first download finished (state=done), then a fresh 202 was returned.
  - Steps 3 & 4 (status + SSE event:progress + :ping heartbeat + byte progress, WR-02): FAILED live — /status and /download-progress only responded AFTER the download completed; no live heartbeat or byte-progress frames streamed.
  - Step 5 (gated balanced.diarize -> 403): PASS.
  - Step 6 (resume after crash, HW-09): FAILED — Ctrl+C mid-download, on restart the download re-fetched from zero instead of resuming.
  - Root cause (confirmed in code): ensure_downloaded (manager.py:298) calls the SYNCHRONOUS blocking hf_hub_download directly inside an async background task (_run_download, routes_models.py:156) with no asyncio.to_thread/run_in_executor offload, freezing the event loop for the whole download. This single defect breaks WR-01 (409), WR-02 (live SSE heartbeat + byte progress), and concurrent request handling.
  - Secondary cause (resume): the download used HF's Xet backend (xet_get in traceback), which does NOT use the classic <blob>.incomplete + HTTP Range resume path the code assumes (manager.py:246-249 docstring + routes_models.py:135 *.incomplete scanner). On restart it re-downloaded from zero -> HW-09 resume-after-crash broken for Xet downloads.
  - Not testable live: SHA256-mismatch -> ModelIntegrityError path (registry expected_sha256 is None for all models, deferred per registry.py:20-23); covered by tests/test_manager_download.py only.

### 5. SC-4 — Load blocks past 85% VRAM; explicit idle unload; "what's in VRAM" indicator (HW-07)
expected: `POST /models/{id}/load` on a tight budget returns 507 with `error="vram_budget_exceeded"`; on a generous budget returns 200 with a `LoadedModel` body. `POST /models/{id}/unload` returns 204 and is idempotent (explicit-only, no idle timer — D-03). `GET /diagnostics/vram` reflects the currently-loaded model(s) via the two-pool probe (torch allocated + live_vram_bytes); the CPU branch reports `loaded` from manager_state (WR-03 fix).
result: issue
reported: "load -> 200 {category:stt, model_id:Systran/faster-whisper-small, vram_bytes:1500000000, loaded_at:...}; GET /diagnostics/vram -> {backend:cpu,total_mb:0,available_mb:0,used_mb:0,loaded:[]}; unload -> 204; unload again -> 204; GET /diagnostics/vram -> loaded:[]. loaded is empty right after a 200 load."
severity: major
evidence:
  - Load (200 + LoadedModel body, vram_bytes=1.5GB = 1GB expected_size * 1.5 STT multiplier): PASS.
  - Unload (204) + idempotent unload (204 again, no error): PASS.
  - 507 vram_budget_exceeded (GPU-gated, not live-testable on CPU): PASS via tests/test_vram_budget.py:36 (:40 asserts error=="vram_budget_exceeded"), 7 passed.
  - FAILED — "what's in VRAM" indicator (WR-03): GET /diagnostics/vram returned loaded=[] immediately after a 200 load, with total_mb=0. total_mb=0 proves the CPU branch hit an exception fallback (happy path returns system RAM at vram.py:161, never 0).
  - Root cause D (code defect, vram.py:149-155 + 167-173): the CPU branch's two error-fallbacks return loaded=[] instead of loaded=_loaded_list(manager_state). Every other backend's fallbacks (DIRECTML/VULKAN vram.py:143; CUDA vram.py:184/194/214) preserve loaded. The CPU branch is the lone exception — WR-03 holds on the happy path (vram.py:164) but not on the fallback.
  - Trigger E (environment): psutil is declared in pyproject.toml (psutil>=5.9) but NOT installed in the running env (ModuleNotFoundError: No module named 'psutil'), so `import psutil` raises -> CPU fallback -> loaded=[].
  - Test-coverage gap: tests/test_diagnostics_api.py:89-101 (test_get_vram_returns_state) only asserts loaded==[] and the VRAMState shape; no test loads a model then asserts /diagnostics/vram reflects it on CPU. This is why the 155-green baseline did not catch the WR-03 regression.

### 6. SC-5 — No two models concurrent unless opted in via hidden toggle (HW-09)
expected: With default `concurrent_models=False`, loading a second model while one is already resident returns 409 `concurrent_model_refused` (D-04 — caller must explicitly unload first; no auto-swap). With `concurrent_models=True` (set via `PATCH /settings`), both models load 200. The toggle defaults to False and is not surfaced in the default UI flow. A non-restart PATCH (e.g. quality_preset) preserves a queued restart-required `data_dir` change rather than dropping it (WR-05 fix — flagged human-verify).
result: pass
evidence:
  - D-04 concurrent refusal: with concurrent_models=False (confirmed on disk), load small.stt -> 200, then load small.llm -> 409 concurrent_refused {loaded:stt, requested:llm, fix:"set concurrent_models=true in settings"}. PASS.
  - Earlier 200 on the second load was a test-setup artifact: concurrent_models was still true on disk, persisted from the {"concurrent_models":true} example PATCH given in Test 2 (SC-1). After resetting to false, the 409 fires correctly. The code is correct.
  - Opt-in: with concurrent_models=true (PATCH /settings), both small.stt and small.llm load 200 (demonstrated in the earlier sequence). PASS.
  - Toggle default False (settings.py:76) and exposed in UpdateSettingsRequest (PATCHable); no UI yet (back-end phase, Phase 10 surfaces it). PASS (code check).
  - This also confirms the manager state DOES accumulate across requests (small.stt stayed resident -> second load saw it), which narrows SC-4's loaded=[] root cause to the psutil error-fallback (issue D) alone, not a state-disconnection.
  - WR-05 (flagged human-verify): PATCH data_dir=data2 -> 200 + x-restart-required:true (body still shows boot data_dir=original, correct H1). PATCH quality_preset=small (non-restart) -> 200, no restart header. On-disk data/settings.json after: top-level data_dir=original, quality_preset=small; pending block carries data_dir=data2. The queued restart-required data_dir change was PRESERVED across the non-restart PATCH (not dropped). WR-05 contract PASSES.
  - Adjacent observation (NOT a formal gap, flagged as follow-up): apply_pending (service.py:244-250) installs the ENTIRE pending snapshot on restart, and the hot-swap preserve path (service.py:219-220) re-attaches that snapshot unchanged. The pending snapshot was captured at data_dir-PATCH time (quality_preset=balanced), so a later hot-swap (quality_preset=small) is NOT reflected in pending. On restart, data_dir correctly becomes data2 but quality_preset reverts small->balanced, silently dropping the hot-swap change made after the queue. The WR-05 assertion (data_dir preserved) holds; this stale-snapshot-reverts-hotswaps behavior is adjacent and worth a follow-up verify/design decision.
  - Cleanup note: a pending data_dir=data2 is currently queued on disk; on next restart the server will move data_dir to data2 (fresh DB). Clear by PATCHing data_dir back to E:\Projects\TranscriptionAndNotes\data (restart-required) or by removing the pending key from data/settings.json while the server is stopped.

## Summary

total: 6
passed: 4
issues: 2
pending: 0
skipped: 0

## Gaps

- truth: "POST /models/{id}/download returns 202; GET /download-progress streams event:progress with a :ping heartbeat and byte-level progress (WR-02); duplicate in-flight downloads are refused with 409 (WR-01); downloads resume after a mid-download crash (HW-09)."
  status: resolved
  resolved_by: "02-04 — hf_hub_download offloaded via asyncio.to_thread (event loop unfrozen) + classic non-Xet resume path forced (hf_xet=False / HF_HUB_DISABLE_XET=1); 5 live tests (409, live SSE, byte progress, resume). Verified 2026-06-19."
  reason: "User reported: 1 works, 2 never triggers, 3 and 4 request gets through only after model is downloaded, 5 worked, 6 canceled mid download got error it didnt resume. KeyboardInterrupt traceback in xet_get -> hf_hub_download during _run_download -> ensure_downloaded."
  severity: blocker
  test: 4
  root_cause: "Two defects. (A) ensure_downloaded (manager.py:298) calls the SYNCHRONOUS hf_hub_download directly inside an async background task (_run_download, routes_models.py:156) with no asyncio.to_thread/run_in_executor, freezing the event loop for the whole download -> WR-01 (409), WR-02 (live SSE heartbeat + byte progress), and concurrent request handling all break. (B) The download used HF's Xet backend (xet_get in traceback), which does NOT use the classic .incomplete + HTTP Range resume path the code assumes (manager.py:246-249, routes_models.py:135 scanner) -> HW-09 resume-after-crash broken for Xet downloads."
  artifacts:
    - path: "app/models/manager.py"
      issue: "sync hf_hub_download called inside async ensure_downloaded with no thread offload (line 298); resume docstring assumes .incomplete+Range (246-249) which Xet does not use"
    - path: "app/api/routes_models.py"
      issue: "_run_download awaits the blocking ensure_downloaded (line 156); _poll_bytes (124-151) and the SSE generator (229-269) share the same loop and cannot run while it blocks"
  missing:
    - "Offload hf_hub_download via asyncio.to_thread (or loop.run_in_executor) so the event loop stays responsive during downloads."
    - "Re-verify WR-01 (409 duplicate-in-flight) and WR-02 (live SSE :ping heartbeat + byte-level progress) after un-blocking."
    - "Handle Xet resume: force the classic non-Xet download path, or confirm Xet's own resume and update the byte-progress scanner (routes_models.py:135) for Xet's staging location."
  debug_session: ""

- truth: "GET /diagnostics/vram reflects the currently-loaded model(s); on CPU the loaded list is populated from manager_state (WR-03)."
  status: resolved
  resolved_by: "02-05 — CPU error-fallbacks now return loaded=_loaded_list(manager_state); psutil installed in runtime env (7.2.2); 3 live tests (loaded-on-cpu, psutil-absent graceful degradation, empty-state). Verified 2026-06-19."
  reason: "User reported: loaded is empty right after a 200 load (GET /diagnostics/vram -> {backend:cpu,total_mb:0,available_mb:0,used_mb:0,loaded:[]}). load returned 200 with vram_bytes=1.5GB; unload 204 idempotent worked."
  severity: major
  test: 5
  root_cause: "probe_vram's CPU error-fallbacks (vram.py:149-155 psutil-import-fail, 167-173 psutil-call-fail) return loaded=[] instead of loaded=_loaded_list(manager_state); every other backend's fallbacks (DIRECTML/VULKAN vram.py:143; CUDA vram.py:184/194/214) preserve loaded. Triggered by psutil being declared in pyproject.toml (psutil>=5.9) but NOT installed in the runtime env (ModuleNotFoundError), so import psutil raises -> CPU fallback -> loaded=[]. The manager state itself accumulates correctly (confirmed via SC-5), so this is purely a diagnostics-reporting defect on the CPU error path."
  artifacts:
    - path: "app/models/vram.py"
      issue: "CPU branch error-fallbacks return loaded=[] (lines 149-155, 167-173) instead of loaded=_loaded_list(manager_state); inconsistent with every other backend's fallbacks"
    - path: "pyproject.toml"
      issue: "psutil>=5.9 declared but not installed in the runtime env (ModuleNotFoundError: No module named 'psutil')"
    - path: "tests/test_diagnostics_api.py"
      issue: "test_get_vram_returns_state (89-101) only asserts loaded==[] + shape; no test loads a model then asserts /diagnostics/vram reflects it on CPU"
  missing:
    - "Change the two CPU loaded=[] fallbacks to loaded=_loaded_list(manager_state) so the indicator degrades gracefully (show loaded even with total_mb=0), matching the other branches."
    - "Install psutil in the runtime env (pip install -e . / venv sync) so the CPU happy path reports real total/available/used RAM."
    - "Add a test that loads a model then asserts /diagnostics/vram reflects it on CPU, including a variant with psutil absent to lock the graceful-degradation contract."
  debug_session: ""

## Notes

- **Session paused at Test 1/6 (2026-06-19).** Cold-start smoke test passed (CPU
  fallback works, server boots, endpoints respond). The user paused before SC-1..SC-5
  because the ROCm-on-Windows GPU path for the RX 6800 (RDNA2) is genuinely hard to
  get working and they want to find a better GPU solution before proceeding.
- This is NOT a UAT failure — the CPU fallback chain (D-06) is working as designed and
  the 02-03 spike verdict `ROCM_FALLBACK_TO_CPU` already records the blocker as a
  stale-install + wrong-Python issue, not a hardware limit. The pause is a strategic
  decision about the GPU path, not a defect in Phase 2's deliverables.
- Tests 2-6 (SC-1..SC-5) remain `[pending]`; resume with `/gsd-verify-work 2` once the
  GPU-path decision is made. The pytest suite (155 green) already covers SC-1..SC-5 at
  the contract level, so resumption is mostly live-boot confirmation of the model
  manager endpoints.