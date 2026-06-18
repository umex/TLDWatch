---
phase: 02-gpu-backend-detection-model-manager
plan: 02
subsystem: model-manager
tags: [models, huggingface-hub, vram, concurrency, fastapi, pydantic]
requires:
  - "02-01: GpuBackend enum, ModelSpec/ModelSet/QualityPreset/ModelCategory, Settings hot-swap fields, probe_vram + ManagerState, atomic-write helper"
provides:
  - "app.models.registry: REGISTRY (9 entries: 3 categories x 3 presets) + get_spec/get_category/list_specs; BALANCED triple per D-09"
  - "app.models.presets: PRESETS dict + active_model_set(settings) resolver (override > preset, HW-06)"
  - "app.storage.models_dir: data_models_dir/ensure_models_dir/category_models_dir/spec_dir/spec_file_path; repo_id sandboxed (/ -> --) per Pitfall 4"
  - "app.models.manager: ModelManager (ensure_downloaded/load/unload/unload_all/verify/list_installed/currently_loaded) + 5 typed errors + LoadedModel/DownloadProgress/ModelsListResponse/DownloadTaskResponse + get_manager/configure_manager singleton"
  - "app.api.routes_models: GET /models, POST /models/{id}/download (202), GET /models/{id}/status, GET /models/{id}/download-progress (SSE), POST /models/{id}/load (507/409/403/500 mapping), POST /models/{id}/unload (204 idempotent)"
  - "ManagerState.loaded_meta field + vram._loaded_list prefers real LoadedModel records over the placeholder"
affects:
  - "Phase 3/7/8: STT/diarize/LLM adapters call get_manager().load(ModelCategory.X) and ensure_downloaded(spec, category) before inference"
  - "Phase 4: orchestrator owns the load/unload sequence per D-03/D-04; prefetch-at-submit is a Phase 4 follow-up (D-02 just-in-time at stage start in Phase 2)"
  - "Phase 5: React UI consumes the /models routes + the SSE download-progress stream"
  - "Phase 10: settings panel surfaces quality_preset + per_category_overrides + concurrent_models + vram_budget_fraction"
tech-stack:
  added: []
  patterns:
    - "Lazy import inside function body for huggingface_hub.hf_hub_download + errors (boundary check: only manager.py + hf_token.py import huggingface_hub)"
    - "Typed error hierarchy in the manager + HTTP mapping in the routes (D-15 strict contract: VramBudgetExceeded->507, ConcurrentModelRefused->409, ModelGatedError->403, ModelIntegrityError->500)"
    - "Module-level singleton (get_manager/configure_manager) mirroring app.settings.service; configure_manager also installs manager._state as the vram ManagerState singleton so GET /diagnostics/vram sees live loaded_meta"
    - "Per-category VRAM overhead multipliers (LLM=1.2, STT=1.5, DIARIZE=1.2) applied to expected_size_bytes for budget math"
    - "Structured JSON INFO log line on load (event/category/model_id/expected_vram_mb/measured_vram_mb_after_load/total_vram_mb/available_vram_mb_after_load) for SC-2 diagnostics panel"
    - "Bounded SHA retry (1 re-download, no infinite loop) per Pitfall 4"
    - "ManagerState.loaded_meta typed as dict[ModelCategory, Any] to avoid circular import with app.models.manager (LoadedModel lives there)"
    - "mock_probe_vram fixture uses side_effect (not return_value) so the default reflects manager_state.loaded_meta for diagnostics assertions; tests override side_effect for the tight-budget case"
key-files:
  created:
    - app/storage/models_dir.py
    - app/models/registry.py
    - app/models/presets.py
    - app/models/manager.py
    - app/api/routes_models.py
    - tests/test_presets.py
    - tests/test_manager_download.py
    - tests/test_vram_budget.py
    - tests/test_concurrent_models.py
  modified:
    - app/models/vram.py
    - app/main.py
    - tests/conftest.py
decisions:
  - "ManagerState.loaded_meta typed as dict[ModelCategory, Any] (not a LoadedModel forward-ref) to avoid the circular import with app.models.manager; Pydantic stores whatever the manager assigns and the runtime behavior is identical"
  - "mock_probe_vram fixture uses side_effect by default so the diagnostics endpoint reflects the live manager_state.loaded_meta (a plain return_value would always return loaded=[] and break the diagnostics-reflection tests); tests that need a canned tight state override side_effect"
  - "FastAPI wraps HTTPException detail in a {detail: ...} envelope; tests read body['detail']['error'] (not body['error']) for the 507/409/403/500 cases"
  - "mock_hf_hub_download patches the real huggingface_hub.hf_hub_download attribute (huggingface_hub is a real installed dependency); the manager's lazy `from huggingface_hub import hf_hub_download` resolves to the mock at call time"
  - "GatedRepoError in tests constructed with a minimal httpx.Response stand-in (the manager only re-wraps the exception, it does not read the response)"
metrics:
  duration: ~25 min
  completed: 2026-06-18
  tasks: 3
  files: 12
  tests_added: 17
  tests_total: 151
---

# Phase 02 Plan 02: Model manager -- download, verify, lazy load, idle unload, VRAM probe, model API Summary

The `ModelManager` owns every model's lifecycle on disk (resumable download via `huggingface_hub.hf_hub_download` + SHA256 verify with bounded retry) and in VRAM (lazy load with 85% budget gate via the two-pool `probe_vram`, refuse-then-caller-unloads concurrent policy per D-04, explicit-only idempotent unload per D-03, structured per-model VRAM log line per SC-2); six `/models` routes wired into the lifespan with the typed-error-to-HTTP mapping (507/409/403/500).

## What Was Built

### Registry + presets (D-09, HW-06)

- **app/models/registry.py** -- `REGISTRY: dict[str, ModelSpec]` with 9 entries (`<preset>.<category>` keys): BALANCED triple (`Systran/faster-whisper-large-v3` + `pyannote/speaker-diarization-3.1` + `Qwen/Qwen2.5-7B-Instruct-GGUF` `qwen2.5-7b-instruct-q4_k_m.gguf` ~4.5 GB), SMALL triple (faster-whisper-small + Qwen2.5-3B ~2 GB), LARGE triple (Qwen2.5-14B ~10 GB, HW-08 desktop opt-in). `get_spec` raises `KeyError` with the list of valid ids on unknown (T-02-10); `get_category` parses `<preset>.<category>` -> `ModelCategory`; `list_specs` returns `sorted(REGISTRY.items())`.
- **app/models/presets.py** -- `PRESETS: dict[QualityPreset, ModelSet]` + `active_model_set(settings)` resolver: `overrides.stt or preset.stt` (None falls through) so a per-category override wins over the preset for the overridden category only (HW-06).

### Storage helpers (Pitfall 4)

- **app/storage/models_dir.py** -- `data_models_dir` / `ensure_models_dir` / `category_models_dir` (validates `isinstance(category, ModelCategory)`) / `spec_dir` (sandboxes `repo_id` `/` -> `--`) / `spec_file_path`. The on-disk path is `<data_dir>/models/<category>/<sanitized_repo_id>/<file>` -- flat directory, no path traversal from a project-controlled `repo_id`.

### ModelManager (D-01, D-03, D-04, SC-2, SC-3, SC-4, SC-5)

- **app/models/manager.py** -- `ModelManager` class with:
  - `ensure_downloaded(spec, category)` -- lazy-imports `huggingface_hub.hf_hub_download` + the error classes inside the body (boundary check); size fast-path; corrupt-SHA delete + re-download; `GatedRepoError` -> `ModelGatedError` (Pitfall 3); `RepositoryNotFoundError` -> `ModelManagerError`; post-download SHA verify with bounded 1-retry (Pitfall 4) -> `ModelIntegrityError` on mismatch. `force_download` is NOT passed (default False -- the library resumes via `<blob>.incomplete` + Range header).
  - `load(category, spec)` -- re-reads settings via a factory (H1 hot-swap); checks D-04 concurrent policy (`ConcurrentModelRefused` when `concurrent_models=False` and a model is already resident); probes VRAM via `probe_vram` (Pitfall 2 two-pool fix); computes the expected in-VRAM footprint with per-category overhead multipliers (LLM=1.2, STT=1.5, DIARIZE=1.2); raises `VramBudgetExceeded` when `used_mb + expected_mb > vram_budget_fraction * total_mb` (SC-4); records the reservation in `live_vram_bytes` + `loaded_meta`; emits a structured JSON INFO log line (SC-2). Phase 2 does NOT instantiate the real model -- the load is a typed VRAM reservation; Phase 3/7/8 adapters own the inference.
  - `unload(category)` -- idempotent (D-03 explicit-only; no timer); clears both `live_vram_bytes` + `loaded_meta`; emits an `model_unloaded` log line.
  - `unload_all()` -- snapshot then unload each (lifespan teardown).
  - `verify(spec, category)` / `list_installed()` / `currently_loaded()`.
- 5 typed error classes: `ModelManagerError` (base), `VramBudgetExceeded` (-> 507), `ConcurrentModelRefused` (-> 409, D-04), `ModelGatedError` (-> 403), `ModelIntegrityError` (-> 500).
- Response models: `LoadedModel`, `DownloadProgress` (Literal state), `ModelsListResponse`, `DownloadTaskResponse`.
- Module-level singleton: `get_manager()` (raises `RuntimeError` if not configured), `configure_manager(manager)` (also calls `set_manager_state(manager._state)` so `GET /diagnostics/vram` sees the live `loaded_meta`).

### vram.py extension

- `ManagerState` extended with `loaded_meta: dict[ModelCategory, Any]` (typed `Any` to avoid the circular import with `app.models.manager`; the runtime values are `LoadedModel` instances). `_loaded_list` now prefers the real `LoadedModel` records from `loaded_meta` over the 02-01 `"<category>:unknown"` placeholder, so `GET /diagnostics/vram` surfaces the real `model_id` + `loaded_at`.

### API (app/api/routes_models.py)

- `router = APIRouter(prefix="/models", tags=["models"])` with six routes:
  1. `GET /models` -> `ModelsListResponse` (`installed` from `manager.list_installed()`, `available` from registry entries not installed, `active_set` from `active_model_set(settings)`).
  2. `POST /models/{id}/download` -> 202 `DownloadTaskResponse`; kicks off `asyncio.create_task(_run_download(...))` that calls `manager.ensure_downloaded` and updates the in-memory `_in_flight` progress dict.
  3. `GET /models/{id}/status` -> `DownloadProgress` (default `state="queued"`).
  4. `GET /models/{id}/download-progress` -> `text/event-stream` SSE (Phase 5 consumer); yields `event: progress` lines + a `: ping` heartbeat every 5 s.
  5. `POST /models/{id}/load` -> `LoadedModel`; catches `VramBudgetExceeded` -> 507, `ConcurrentModelRefused` -> 409 (D-04), `ModelGatedError` -> 403, `ModelIntegrityError` -> 500.
  6. `POST /models/{id}/unload` -> 204 No Content, idempotent (D-03).
- `id` resolved via `registry.get_spec` (raises `KeyError` -> 404 on unknown; no path traversal -- T-02-10).

### Lifespan (app/main.py)

- `configure_manager(ModelManager(settings))` added AFTER `set_manager_state(...)` from 02-01 and before `reconcile_all`, so the manager is built after the settings are fully populated (after the first-boot detect + `apply_pending()` from H1).
- Lifespan teardown: `await get_manager().unload_all()` BEFORE `engine.dispose()` (D-03 shutdown path); `configure_manager(None)` on teardown resets the singleton + the vram ManagerState.
- `models_router` registered; `DownloadProgress`, `LoadedModel`, `ModelsListResponse`, `DownloadTaskResponse` added to `_EXTRA_OPENAPI_MODELS`.

### Tests (17 new + 134 existing = 151 total)

- **conftest.py** -- `mock_probe_vram` rewritten to use `side_effect` (default returns a generous CUDA state whose `loaded` list is built from the real `manager_state.loaded_meta` via `_loaded_list`, so diagnostics-reflection assertions work); patches BOTH `routes_diagnostics.probe_vram` AND `manager_module.probe_vram`. `mock_hf_hub_download` patches the real `huggingface_hub.hf_hub_download` attribute; default writes `b"x" * expected_size_bytes` to `<local_dir>/<filename>`. `configured_model_manager` fixture (function scope).
- **test_presets.py** (6) -- D-09 BALANCED triple + HW-06 override-wins + registry helpers (get_category, get_spec KeyError listing).
- **test_manager_download.py** (4) -- SC-3 size+SHA fast-path; resume-after-crash (force_download NOT passed); GatedRepoError -> ModelGatedError (Pitfall 3); corrupt-SHA -> ModelIntegrityError after bounded retry.
- **test_vram_budget.py** (3) -- SC-4 507 refusal on tight budget; 200 + LoadedModel on generous budget; 204 idempotent unload + diagnostics reflection.
- **test_concurrent_models.py** (4) -- SC-5 D-04 409 default refuse; opt-in 200 via PATCH; concurrent_models in OpenAPI; unload-then-load (caller-unloads pattern).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] ManagerState.loaded_meta forward-ref broke module-load**
- **Found during:** Task 2 (verify command failed with `PydanticUserError: ManagerState is not fully defined`)
- **Issue:** The plan specified `loaded_meta: dict[ModelCategory, "LoadedModel"] = Field(default_factory=dict)` with a forward-reference string. vram.py instantiates `_manager_state: ManagerState = ManagerState()` at module load, which requires the forward-ref to be resolvable. Resolving it requires `ManagerState.model_rebuild()` after `LoadedModel` is defined -- but `app.models.manager` imports `ManagerState` from `app.models.vram`, so vram.py finishes loading (including the module-level instantiation) BEFORE manager.py is even imported. The forward-ref cannot be resolved in time.
- **Fix:** Typed `loaded_meta` as `dict[ModelCategory, Any]` (with a docstring noting the runtime values are `LoadedModel` instances). Pydantic stores whatever the manager assigns; the runtime behavior is identical and the circular import is avoided without a `model_rebuild` dance.
- **Files modified:** app/models/vram.py
- **Commit:** 91000eb

**2. [Rule 1 - Bug] mock_probe_vram with return_value broke diagnostics-reflection tests**
- **Found during:** Task 3 (test_load_succeeds_within_budget failed: `loaded=[]` after a successful load)
- **Issue:** The 02-01 `mock_probe_vram` fixture used `return_value=VRAMState(... loaded=[])`. A plain `return_value` ignores the `manager_state` argument, so `GET /diagnostics/vram` always returned `loaded=[]` even after a model was loaded -- breaking the must-have "GET /diagnostics/vram now shows the loaded entry in `loaded`".
- **Fix:** Rewrote `mock_probe_vram` to use `side_effect` by default: the default returns a generous CUDA state whose `loaded` list is built from the real `manager_state.loaded_meta` via `_loaded_list(manager_state)`. Tests that need a canned tight state override `side_effect` per-case.
- **Files modified:** tests/conftest.py
- **Commit:** a8f8ac2

**3. [Rule 3 - Blocking Issue] mock_hf_hub_download stub module broke `from huggingface_hub.errors import ...`**
- **Found during:** Task 3 (test_ensure_downloaded_size_and_sha failed: `'huggingface_hub' is not a package`)
- **Issue:** The initial `mock_hf_hub_download` fixture installed a `types.ModuleType("huggingface_hub")` stub when `huggingface_hub` was not already in `sys.modules`. The stub was a plain module (not a package), so the manager's `from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError` raised `ModuleNotFoundError`.
- **Fix:** The fixture now `import huggingface_hub` first (it is a real installed dependency per pyproject) and patches the `hf_hub_download` attribute on the real module via `monkeypatch.setattr`. The real `huggingface_hub.errors` submodule is then available to the manager's lazy import.
- **Files modified:** tests/conftest.py
- **Commit:** a8f8ac2

### Notes on Plan Interpretation

- **FastAPI HTTPException detail envelope:** The plan's must-have truth `{"error": "vram_budget_exceeded", ...}` is the typed-error payload. FastAPI wraps `HTTPException(detail={...})` in a `{"detail": {...}}` envelope, so the tests read `body["detail"]["error"]` (the route layer's `detail` dict is the structured payload). This is the standard FastAPI behavior and matches the existing `routes_jobs.py` `HTTPException(detail=...)` pattern.
- **`concurrent_models` OpenAPI shape:** The plan's truth "`concurrent_models: bool` in `UpdateSettingsRequest.properties`" is satisfied -- the property appears as `{"anyOf": [{"type": "boolean"}, {"type": "null"}], "title": "Concurrent Models"}` because the field is typed `bool | None`. The test checks presence in `properties`, which is the contract.
- **LLM VRAM overhead multiplier:** The 7B Q4_K_M GGUF is 4.5 GB on disk; with the LLM 1.2x overhead the in-VRAM estimate is ~5.15 GB, which fits the 8 GB laptop budget (0.85 * 8192 = 6963 MB) with headroom per RESEARCH math (D-09).

## Threat Model Compliance

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-02-06 (model download supply chain) | mitigate | DONE -- SHA256 verify against `spec.expected_sha256` when set; size fast-path; bounded 1-retry (Pitfall 4); `ModelIntegrityError` -> 500. `repo_id` is from the registry (not user input); the on-disk path is built from `spec_file_path` which sandboxes `/` -> `--`. |
| T-02-07 (DoS via oversized load) | mitigate | DONE -- 85% VRAM budget gate (`vram_budget_fraction`); `probe_vram` sums torch + llama.cpp pools (Pitfall 2); `VramBudgetExceeded` -> 507 refusal. |
| T-02-08 (concurrent-model starvation) | mitigate | DONE -- `concurrent_models: bool` defaults to `False`; a second `load` raises `ConcurrentModelRefused` -> 409 (D-04); caller must explicitly unload first; no auto-swap in Phase 2. |
| T-02-09 (HF token on wire) | mitigate | DONE -- HTTPS via huggingface_hub; token read from `current().hf_token` (decoded from base64 per D-05); never logged. |
| T-02-10 (`{id}` path param tampering) | mitigate | DONE -- `id` resolved via `registry.get_spec` which raises `KeyError` on unknown (no path traversal); on-disk path built from `spec_file_path` which sandboxes `repo_id` `/` -> `--`; `category` validated as a `ModelCategory` member. |
| T-02-11 (load/unload repudiation) | accept | DONE -- single-user loopback; the structured INFO log line on load + unload is the audit record. |

## Verification

- `pytest tests/test_presets.py tests/test_manager_download.py tests/test_vram_budget.py tests/test_concurrent_models.py -q` -> 17 passed.
- `pytest -q` (full suite) -> 151 passed (134 existing + 17 new).
- `GET /openapi.json` exposes `DownloadProgress`, `LoadedModel`, `ModelsListResponse`, `DownloadTaskResponse`, `ModelSpec`, `ModelSet` in `components.schemas`.
- `UpdateSettingsRequest.properties` includes `concurrent_models` (anyOf boolean/null).
- `grep -rE "from huggingface_hub" app/` returns matches only in `app/models/manager.py` and `app/models/hf_token.py` (boundary check -- no leak into routes or main).
- `POST /models/balanced.llm/load` with mocked generous `probe_vram` returns 200 with a `LoadedModel` body; `GET /diagnostics/vram` then shows the loaded entry.
- `POST /models/balanced.llm/load` with mocked tight `probe_vram` returns 507 with `error="vram_budget_exceeded"`.
- `POST /models/balanced.stt/load` then `POST /models/balanced.llm/load` (default `concurrent_models=False`) returns 409; with `concurrent_models=True` (via PATCH) returns 200 for both.
- `pyproject.toml` was NOT modified by this plan (no new deps; faster-whisper/llama-cpp-python/pyannote.audio/torch arrive in their own phases per RESEARCH).

## Known Stubs

None. The `ModelManager.load` is a typed VRAM reservation (not a real weight load) by design -- Phase 3/7/8 adapters own the inference. This is documented in the plan (`<action>`: "Phase 2 does NOT instantiate a faster-whisper or llama.cpp model -- the load is a typed VRAM reservation") and is not a stub that prevents the plan's goal; HW-02 (models run on GPU) is satisfied at the lifecycle layer in Phase 2 and the real weight loading arrives in Phases 3/7/8.

## Self-Check: PASSED

- All 12 created/modified files exist on disk (verified via the commit file lists).
- Commit `91fb190` (Task 1) exists in git log.
- Commit `91000eb` (Task 2) exists in git log.
- Commit `a8f8ac2` (Task 3) exists in git log.
- Full suite: 151 passed.