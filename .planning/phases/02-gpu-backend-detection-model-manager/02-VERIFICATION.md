---
phase: 02-gpu-backend-detection-model-manager
verified: 2026-06-18T00:00:00Z
status: passed
score: 5/5 ROADMAP success criteria verified · 5/5 phase requirements (HW-02, HW-03, HW-04, HW-07, HW-09) accounted for · 155/155 tests green
source:
  - .planning/ROADMAP.md
  - .planning/REQUIREMENTS.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-01-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-02-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-01-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-02-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-SPIKE.md
reviewed_at: 2026-06-18
scope: Read-only adversarial verification. Verifier did not modify source. Confirms Phase 2 goal achievement via source code, live OpenAPI, and the green test suite (155 passed).
overrides_applied: 0
re_verification: # No previous Phase 2 VERIFICATION.md existed; initial verification
  previous_status: none
  previous_score: 0/0
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 02 — GPU Backend Detection + Model Manager · Verification Report

**Mode:** mvp (per ROADMAP.md; success-criteria-driven)
**Goal (from ROADMAP.md):** The system auto-detects CUDA vs ROCm vs CPU on first run, persists the choice, and owns the lifecycle of every local model on disk and in VRAM.
**Verifier mode:** adversarial / goal-backward. SUMMARY claims are not evidence; only source code, tests, and live OpenAPI count.
**Result:** **VERIFIED — all 5 ROADMAP success criteria pass; 5/5 phase requirements accounted for; 155/155 tests green; OpenAPI exposes every new type; boundary checks clean; the 02-03 spike verdict (ROCM_FALLBACK_TO_CPU) is valid empirical evidence for HW-03.**

---

## 1. ROADMAP Success Criteria (5/5 PASS)

### SC-1: First run silently writes `settings.json` with the right backend; re-detect via `POST /diagnostics/gpu-burn`

**Status: PASS**

- `app/models/backend.py` defines `async def detect() -> GpuBackend` (ordered subprocess + env-var + lazy-torch probe; every `subprocess.run` wrapped in `try/except (TimeoutExpired, FileNotFoundError, OSError)` → silent CPU fallback, D-06) and `async def burn_test(backend) -> BackendProbe` (real 1024×1024 matmul on `cuda` + `torch.cuda.synchronize()` + `perf_counter`; CPU returns `burn_test_ms=None`, `vram_total_mb=None`).
- `app/main.py:120` lifespan calls `await backend_module.detect()` + `await backend_module.burn_test(backend)` on the first-boot path (wraps `load_settings_from_disk` in `try/except`; builds a full `Settings` with all 7 fields; writes atomically). Subsequent boot (backend already set) skips detect.
- `app/api/routes_diagnostics.py` exposes `POST /diagnostics/gpu-burn` which re-runs detect+burn and hot-swaps in-memory `Settings.backend` + `backend_probe` + atomic-writes the full settings (no `X-Restart-Required` — H1).
- Tests: `tests/test_gpu_detect.py` (4 tests) cover CUDA/ROCm/CPU first-boot paths + subsequent-boot no-redetect; `tests/test_diagnostics_api.py` (4 tests) cover the gpu-burn hot-swap + on-disk persist. All pass.

### SC-2: Default model set fits within 8 GB laptop VRAM; per-model VRAM budget logged on load

**Status: PASS**

- `app/models/presets.py` `PRESETS[QualityPreset.BALANCED]` is `Systran/faster-whisper-large-v3` + `pyannote/speaker-diarization-3.1` + `Qwen/Qwen2.5-7B-Instruct-GGUF` (`qwen2.5-7b-instruct-q4_k_m.gguf` ~4.5 GB); SMALL and LARGE entries also present. Verified by direct import (line 1 of evidence below).
- `app/models/manager.py:383-404` `ModelManager.load` probes VRAM via `probe_vram(settings.backend, self._state)` (Pitfall 2 two-pool fix), enforces `budget_mb = vram.total_mb * settings.vram_budget_fraction` (default 0.85), records the reservation in `live_vram_bytes` + `loaded_meta`, and emits a structured JSON INFO log line with the SC-2 keys (`event`/`category`/`model_id`/`expected_vram_mb`/`measured_vram_mb_after_load`/`total_vram_mb`/`available_vram_mb_after_load`).
- 7B Q4_K_M = 4.5 GB on disk × LLM 1.2 overhead ≈ 5.15 GB in-VRAM, fits 0.85 × 8192 = 6963 MB budget.
- Tests: `tests/test_presets.py` (6 tests) cover the BALANCED triple + override-wins; `tests/test_vram_budget.py` (3 tests) cover the budget gate + load + unload.

### SC-3: Model manager downloads, verifies size + SHA, exposes a download log, supports resume after crash

**Status: PASS**

- `app/models/manager.py:284-308` `ensure_downloaded` lazy-imports `huggingface_hub.hf_hub_download` + the error classes inside the body (boundary check — only `manager.py` and `hf_token.py` import `huggingface_hub`); size fast-path; corrupt-SHA delete + re-download; `GatedRepoError` → `ModelGatedError`; `RepositoryNotFoundError` → `ModelManagerError`; post-download SHA verify with bounded 1-retry (Pitfall 4) → `ModelIntegrityError`. `force_download` is NOT passed (default False — resume via `<blob>.incomplete` + Range header).
- `app/api/routes_models.py` six routes: `GET /models`, `POST /models/{id}/download` (202), `GET /models/{id}/status`, `GET /models/{id}/download-progress` (SSE), `POST /models/{id}/load`, `POST /models/{id}/unload` (204 idempotent). Typed-error HTTP mapping verified: `VramBudgetExceeded`→507, `ConcurrentModelRefused`→409, `ModelGatedError`→403, `ModelIntegrityError`→500.
- `app/storage/models_dir.py` sandboxes `repo_id` `/` → `--` (Pitfall 4 mitigation; no path traversal — T-02-10).
- Tests: `tests/test_manager_download.py` (4 tests) cover size+SHA fast-path, resume-after-crash, gated-repo → ModelGatedError, corrupt-SHA → ModelIntegrityError. All pass.

### SC-4: Loading blocks past 85% VRAM; unload explicit on idle; "what's in VRAM" indicator exposed

**Status: PASS**

- `app/models/manager.py:383-404` `load` raises `VramBudgetExceeded(category, needed_mb, available_mb)` when `state.used_mb + expected_mb > vram_budget_fraction * total_mb`; route maps to 507.
- `app/models/manager.py:430-446` `unload` is idempotent (D-03 explicit-only; no time-based timer); clears `live_vram_bytes` + `loaded_meta`; emits an `model_unloaded` log line. `unload_all()` snapshot-then-unload is used in lifespan teardown (`app/main.py:227`).
- `app/models/vram.py` `probe_vram` returns a typed `VRAMState` with `total_mb`/`available_mb`/`used_mb`/`loaded`; `_loaded_list` prefers the real `LoadedModel` records from `ManagerState.loaded_meta`.
- `GET /diagnostics/vram` returns the current VRAM state; `configure_manager` installs `manager._state` as the vram ManagerState singleton so the endpoint sees the live `loaded_meta`.
- Tests: `tests/test_vram_budget.py` (3 tests) cover 507 refusal, 200 + LoadedModel, 204 idempotent unload + diagnostics reflection.

### SC-5: No two models resident concurrently unless the user opts in via a hidden-by-default settings toggle

**Status: PASS**

- `app/models/settings.py` `concurrent_models: bool = False` (D-04 default-off; hidden by default). The field is in `UpdateSettingsRequest.properties` (verified live in OpenAPI).
- `app/models/manager.py:375-381` `load` raises `ConcurrentModelRefused(loaded_category, requested_category)` when `concurrent_models=False` and a model is already resident; route maps to 409 with `fix="set concurrent_models=true in settings"`. Auto-swap is deliberately NOT Phase 2 behavior (D-04 — caller unloads first).
- Tests: `tests/test_concurrent_models.py` (4 tests) cover default refuse (409), opt-in 200 via PATCH, OpenAPI exposure, unload-then-load.

---

## 2. Requirements Coverage (5/5 accounted for)

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| HW-02 | 02-01, 02-02 | Transcription/diarization/LLM run on local models on GPU | SATISFIED (lifecycle layer) | ModelManager owns lifecycle (download/verify/load/unload/VRAM reservation). GPU inference execution is a later phase per the project's explicit deferral: REQUIREMENTS.md row HW-02 says "lifecycle in 02-02; actual GPU inference in Phase 3/7/8", and the 02-02 SUMMARY Known Stubs notes "the load is a typed VRAM reservation; Phase 3/7/8 adapters own the inference." The phase goal ("owns the lifecycle of every local model on disk and in VRAM") is achieved; real weight loading is intentionally out of scope for Phase 2. |
| HW-03 | 02-01, 02-03 | App auto-detects GPU (CUDA vs ROCm vs CPU) on first run, configures backends silently | SATISFIED | `detect()` + `burn_test()` + lifespan first-boot write (02-01); `02-03-SPIKE.md` verdict `ROCM_FALLBACK_TO_CPU` is the empirical evidence on the actual desktop (the fallback chain is proven; per D-07 the code ships targeting the documented paths regardless). Contract guard test green. |
| HW-04 | 02-02 | App downloads its own models on first run; user can swap model variants in settings | SATISFIED (download + swap mechanism) | `ensure_downloaded` via `hf_hub_download` (resumable); `per_category_overrides` + `active_model_set` resolver (override > preset, HW-06 mechanism); the settings-panel UI for swapping is Phase 10 (REQUIREMENTS.md maps HW-05/HW-06/HW-08 to Phase 10, not Phase 2). The Phase 2 contract is the download + the per-category override data layer, both present. |
| HW-07 | 02-02 | Default model set fits the 8 GB laptop VRAM budget | SATISFIED | BALANCED triple (faster-whisper large-v3 + pyannote 3.1 + Qwen2.5-7B Q4_K_M) verified; budget math (0.85 × 8192 = 6963 MB ≥ 5.15 GB LLM estimate) holds; `tests/test_presets.py` green. |
| HW-09 | 02-02 | Per-job VRAM discipline: on-demand load, idle unload, no concurrent multi-model residency | SATISFIED | `load` on demand (D-01), `unload` explicit-only idempotent (D-03), `ConcurrentModelRefused` 409 when `concurrent_models=False` (D-04). Tests green. |

### Orphaned Requirements Check

`REQUIREMENTS.md` traceability table maps exactly HW-02, HW-03, HW-04, HW-07, HW-09 to Phase 2 — no orphaned IDs. All five are claimed by the PLANs (02-01: HW-02, HW-03; 02-02: HW-02, HW-04, HW-07, HW-09; 02-03: HW-03). No orphans.

---

## 3. Required Artifacts (all VERIFIED)

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `app/models/diagnostics.py` | Phase 2 typed surface (10 types) | VERIFIED | All 10 types import cleanly: GpuBackend, QualityPreset, ModelCategory, BackendProbe, VRAMState, LoadedModelInfo, HfTokenResult, GpuBurnResult, ModelSpec, ModelSet. |
| `app/models/backend.py` | detect() + burn_test() | VERIFIED | `async def detect` + `async def burn_test` present; subprocess timeout=3 + try/except; lazy torch import. |
| `app/models/vram.py` | probe_vram + ManagerState + set_manager_state | VERIFIED | `ManagerState` extended with `loaded_meta`; `probe_vram` two-pool fix; lazy torch/psutil import. |
| `app/models/hf_token.py` | validate_token four-state shim | VERIFIED | `async def validate_token`; no `pyannote.audio` import (boundary). |
| `app/models/settings.py` | 7 new Settings fields + strict UpdateSettingsRequest | VERIFIED | hf_token base64 round-trip verified (`aGZfYWJjMTIz` on disk, no cleartext); backend/backend_probe rejected by UpdateSettingsRequest; vram_budget_fraction range 0.1..0.95 enforced. |
| `app/models/registry.py` | REGISTRY 9 entries + helpers | VERIFIED | 9 entries (3 presets × 3 categories); `get_spec` raises KeyError with valid-id list; `get_category` parses `<preset>.<category>`. |
| `app/models/presets.py` | PRESETS + active_model_set | VERIFIED | BALANCED triple is the right repo_ids/file; override-wins resolver present. |
| `app/storage/models_dir.py` | data_models_dir + spec_dir sandboxing | VERIFIED | `spec_dir` sandboxes `repo_id` `/` → `--`; `category_models_dir` validates isinstance. |
| `app/models/manager.py` | ModelManager + 5 errors + singleton | VERIFIED | `ModelManager`, `VramBudgetExceeded`, `ConcurrentModelRefused`, `ModelGatedError`, `ModelIntegrityError`, `LoadedModel`, `DownloadProgress`, `ModelsListResponse`, `DownloadTaskResponse`, `get_manager`, `configure_manager` all importable; budget + concurrency logic present at lines 375-404. |
| `app/api/routes_diagnostics.py` | 3 diagnostics routes | VERIFIED | All 3 routes registered in the app. |
| `app/api/routes_models.py` | 6 model routes + error mapping | VERIFIED | All 6 routes registered; 507/409/403/500 mapping present. |
| `app/main.py` | lifespan detect + configure_manager + teardown unload_all | VERIFIED | `backend_module.detect()` at line 120; `set_manager_state` at 180; `configure_manager(ModelManager(settings))` at 189; `await _get_manager().unload_all()` at 227; both routers registered at 329-330. |
| `tests/test_gpu_detect.py` | 4 SC-1 tests | VERIFIED | 4 tests, pass. |
| `tests/test_settings_phase2.py` | 8 strict-input/hot-swap tests | VERIFIED | 8 tests, pass. |
| `tests/test_hf_token.py` | 5 four-state tests | VERIFIED | 5 tests, pass. |
| `tests/test_diagnostics_api.py` | 4 diagnostics API tests | VERIFIED | 4 tests, pass. |
| `tests/test_presets.py` | 4-6 preset tests | VERIFIED | 6 tests, pass. |
| `tests/test_manager_download.py` | 4 download/verify tests | VERIFIED | 4 tests, pass. |
| `tests/test_vram_budget.py` | 3 budget tests | VERIFIED | 3 tests, pass. |
| `tests/test_concurrent_models.py` | 4 concurrency tests | VERIFIED | 4 tests, pass. |
| `02-03-SPIKE.md` | 5-section spike + verdict | VERIFIED | All 5 sections present; verdict `VERDICT: ROCM_FALLBACK_TO_CPU`; Phase 3 "must" requirements present. |
| `tests/test_spike_documented.py` | 4-assertion contract guard | VERIFIED | 4 tests, pass. |

---

## 4. Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `app/main.py` | `app/models/backend.py` | lifespan calls `backend_module.detect()` + `burn_test()` + atomic write | WIRED | `app/main.py:120` confirmed. |
| `app/api/routes_diagnostics.py` | `app/models/backend.py` | `POST /diagnostics/gpu-burn` calls detect + burn + atomic write | WIRED | route present + registered. |
| `app/models/vram.py` | `torch.cuda.mem_get_info` | `probe_vram` wraps the call; llm-pool sum is `manager_state.live_vram_bytes` | WIRED | two-pool fix in `probe_vram`. |
| `app/models/hf_token.py` | `huggingface_hub.hf_hub_url` | `validate_token` does a HEAD call to HF Hub | WIRED | lazy import + `_hf_hub_url` seam. |
| `app/models/manager.py` | `app/models/vram.py` | `ModelManager.load` calls `probe_vram` before loading | WIRED | `manager.py:383` `vram = probe_vram(settings.backend, self._state)`. |
| `app/models/manager.py` | `huggingface_hub.hf_hub_download` | `ensure_downloaded` wraps `hf_hub_download` (resumable) | WIRED | `manager.py:284` lazy import. |
| `app/api/routes_models.py` | `app/models/manager.py` | `POST /models/{id}/load` calls `manager.load`; 4 typed errors → HTTP codes | WIRED | `routes_models.py:202-234` mapping confirmed. |
| `app/main.py` | `app/models/manager.py` | lifespan calls `configure_manager(ModelManager(...))` + teardown `unload_all` | WIRED | `app/main.py:189` + `:227`. |
| `app/models/presets.py` | `app/models/settings.py` | `active_model_set(settings)` reads `quality_preset` + `per_category_overrides` | WIRED | resolver present, override > preset. |
| `tests/test_spike_documented.py` | `02-03-SPIKE.md` | test reads the file and asserts each required heading | WIRED | 4 tests pass. |

---

## 5. Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `GET /models` `active_set` | `active_model_set(settings)` | `settings.quality_preset` + `per_category_overrides` → `PRESETS` dict → `REGISTRY` | Yes (9 real ModelSpec entries with real repo_ids) | FLOWING |
| `GET /diagnostics/vram` `loaded` | `ManagerState.loaded_meta` | `ModelManager.load` records `LoadedModel` per category | Yes (populated by real load calls; empty by default — correct) | FLOWING |
| `POST /models/{id}/download` | `hf_hub_download` | HuggingFace Hub (network) | Real (mocked in tests; production path is the real library call) | FLOWING |
| `POST /diagnostics/gpu-burn` `probe` | `backend.detect()` + `burn_test()` | Subprocess + lazy torch on the real box | Yes (real-kernel matmul; CPU returns nulls per D-06) | FLOWING |

---

## 6. Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| All types import cleanly | `python -c "from app.models.diagnostics import ...; from app.models.manager import ...; ..."` | OK | PASS |
| BALANCED triple is the right repo_ids | direct import of `PRESETS[QualityPreset.BALANCED]` | `Systran/faster-whisper-large-v3` / `pyannote/speaker-diarization-3.1` / `qwen2.5-7b-instruct-q4_k_m.gguf` | PASS |
| hf_token base64 on disk, no cleartext | `Settings(... hf_token='hf_abc123').model_dump_json()` | contains `aGZfYWJjMTIz`, NOT `hf_abc123` | PASS |
| UpdateSettingsRequest rejects backend | `UpdateSettingsRequest(backend='cuda')` | `ValidationError` | PASS |
| vram_budget_fraction range enforced | `UpdateSettingsRequest(vram_budget_fraction=1.5)` | `ValidationError` | PASS |
| OpenAPI exposes all 10 new schemas | `app.openapi()['components']['schemas']` | all 10 present | PASS |
| UpdateSettingsRequest has no backend/backend_probe | OpenAPI properties | `backend`/`backend_probe` absent; `concurrent_models` present | PASS |
| All 9 routes registered | `app.routes` paths | all 9 present (3 diagnostics + 6 models) | PASS |
| huggingface_hub boundary | `grep "from huggingface_hub" app/` | only `hf_token.py` + `manager.py` (line 38 is a docstring comment) | PASS |
| Full test suite green | `pytest -q` | 155 passed in 99.36s | PASS |
| Spike contract guard green | `pytest tests/test_spike_documented.py -q` | 4 passed | PASS |
| Manager load wiring | grep `probe_vram(`/`VramBudgetExceeded`/`ConcurrentModelRefused` in `manager.py` | lines 383/389/377 — budget + concurrency gates present | PASS |
| Routes error mapping | grep `status_code=507/409/403/500` in `routes_models.py` | all four present | PASS |

---

## 7. Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| `tests/test_spike_documented.py` | `python -m pytest tests/test_spike_documented.py -q` | 4 passed | PASS |
| Full suite | `python -m pytest -q` | 155 passed | PASS |

---

## 8. Anti-Patterns Scan

No blockers found.

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `app/models/vram.py` | `_loaded_list` | `"<category>:unknown"` placeholder model_id | INFO | Documented in 02-01 SUMMARY Known Stubs; 02-02's `loaded_meta` overrides it when a real model is loaded. The `loaded` list is empty by default so the placeholder only surfaces in contrived test paths. Not a stub that prevents the goal. |

No `TBD` / `FIXME` / `XXX` debt markers in any Phase 2 file. The `ModelManager.load` is a typed VRAM reservation by design (not a stub) — Phase 3/7/8 adapters own the real weight loading; this is documented in the plan and the 02-02 SUMMARY Known Stubs and is the intentional deferral of HW-02's GPU-inference-execution layer.

---

## 9. Human Verification Required

None. All Phase 2 success criteria are observable via tests + live OpenAPI + source inspection. The one inherently-human step (running the ROCm spike on the physical desktop) was already performed by the user and recorded in `02-03-SPIKE.md` with verbatim terminal output; the contract guard test enforces its presence. No additional human verification is required for Phase 2 closure.

---

## 10. Deferred Items (Step 9b)

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Real GPU weight loading (faster-whisper / llama-cpp-python / pyannote.audio inference execution) | Phase 3 / 7 / 8 | ROADMAP Phase 3 goal: "proves the GPU abstraction works"; Phase 7 "pyannote adapter"; Phase 8 "llama-cpp-python adapter". REQUIREMENTS.md HW-02 row: "actual GPU inference in Phase 3/7/8". 02-02 SUMMARY Known Stubs documents this explicitly. |
| 2 | Prefetch-at-submit + auto-swap load policy | Phase 4 | 02-02 PLAN: "prefetch-at-job-submit (per D-02 just-in-time at stage start is a Phase 4 orchestrator concern; Phase 2 is the mechanism, Phase 4 is the policy)". ROADMAP Phase 4: "Job Orchestrator + Persistent Queue". |
| 3 | Settings panel UI for quality preset + per-category override + concurrent_models toggle | Phase 10 | ROADMAP Phase 10 goal: "Settings Panel + Quality Preset + Per-Category Overrides". REQUIREMENTS.md maps HW-05/HW-06/HW-08 to Phase 10. Phase 2 ships the data layer (`per_category_overrides`, `active_model_set`, `concurrent_models`), not the UI. |

---

## 11. Gaps Summary

No gaps. All 5 ROADMAP success criteria pass; all 5 phase requirements are satisfied (HW-02 at the lifecycle layer per the project's explicit deferral; the rest end-to-end); all artifacts exist, are substantive, and are wired; data flows are real; the full suite is green (155 passed); the boundary checks are clean; the 02-03 spike verdict is valid empirical evidence for HW-03 per D-07.

---

_Verified: 2026-06-18_
_Verifier: Claude (gsd-verifier)_