---
phase: 02-gpu-backend-detection-model-manager
plan: 01
subsystem: backend-detect-settings-diagnostics
tags: [gpu, settings, diagnostics, hf-token, pydantic, fastapi]
requires:
  - "01-04: atomic-write helper (D-04), strict UpdateSettingsRequest (D-15), pending-slot restart-only data_dir (H1)"
provides:
  - "app.models.diagnostics: GpuBackend, QualityPreset, ModelCategory enums + BackendProbe, VRAMState, LoadedModelInfo, HfTokenResult, GpuBurnResult, ModelSpec, ModelSet"
  - "app.models.backend.detect() + burn_test() (silent CPU fallback D-06; subprocess + lazy torch)"
  - "app.models.vram.probe_vram() + ManagerState (two-pool fix Pitfall 2)"
  - "app.models.hf_token.validate_token() four-state shim (D-05, Pitfall 3)"
  - "Settings extended with 7 Phase 2 fields (D-08); hf_token base64 on disk + null in GET (D-05)"
  - "POST /diagnostics/gpu-burn, GET /diagnostics/vram, POST /diagnostics/test-hf-token"
  - "lifespan first-boot detect path (Phase 1 file -> detect + burn + atomic write)"
affects:
  - "02-02: ModelManager consumes GpuBackend, ModelCategory, VRAMState, ManagerState, Settings.quality_preset + vram_budget_fraction + concurrent_models"
  - "Phase 3/7/8: STT/diarize/LLM stages call get_manager().load(ModelCategory.X)"
  - "Phase 5/10: React settings panel reads/writes the new Settings fields via PATCH /settings"
tech-stack:
  added:
    - "huggingface_hub>=0.25"
    - "psutil>=5.9"
    - "httpx>=0.27 (promoted from dev to main)"
    - "pytest-mock>=3.12 (dev)"
  patterns:
    - "Pydantic v2 field_serializer + field_validator (mode=before) for hf_token base64 round-trip (D-05), mirroring app.models.job created_at"
    - "Lazy import inside function body for torch / psutil / huggingface_hub / httpx so a CPU-only test env does not crash on import"
    - "Per-field strict=False override on enum/nested-model fields of UpdateSettingsRequest so JSON string/dict coerces to typed values while strict=True stays on scalars (D-15)"
    - "Lifespan try/except ValidationError around load_settings_from_disk -> first-boot detect + burn + atomic write (D-08 required backend field)"
    - "apply_update writes the FULL new.model_dump() to disk (not just data_dir) so Phase 2 hot-swap fields persist"
key-files:
  created:
    - app/models/diagnostics.py
    - app/models/backend.py
    - app/models/vram.py
    - app/models/hf_token.py
    - app/api/routes_diagnostics.py
    - tests/test_gpu_detect.py
    - tests/test_settings_phase2.py
    - tests/test_hf_token.py
    - tests/test_diagnostics_api.py
  modified:
    - app/models/settings.py
    - app/models/__init__.py
    - app/main.py
    - app/api/routes_settings.py
    - app/settings/service.py
    - pyproject.toml
    - tests/conftest.py
    - tests/test_cleanup.py
    - tests/test_create_job.py
    - tests/test_manifest_helpers.py
    - tests/test_manifest_patch.py
    - tests/test_migration_idempotency.py
    - tests/test_reconcile.py
    - tests/test_resume.py
    - tests/test_stage_files.py
    - tests/test_wal.py
    - tests/test_windows_retry_integration.py
decisions:
  - "UpdateSettingsRequest made all-optional (data_dir: str | None = None) + a model_validator that rejects empty PATCH and explicit null data_dir, preserving both Phase 1 contracts (test_empty_patch_returns_422, test_data_dir_null_returns_422) AND enabling single-field hot-swaps (H1)"
  - "Per-field strict=False on quality_preset + per_category_overrides so JSON string/dict coerces to typed enum/nested model; strict=True stays on scalars (data_dir, hf_token, concurrent_models, vram_budget_fraction) so wrong-typed scalars 422 (D-15)"
  - "apply_update rewritten to write the FULL new.model_dump() to disk in the non-restart path (was only writing data_dir) so Phase 2 hot-swap fields (quality_preset, hf_token, concurrent_models, vram_budget_fraction, per_category_overrides) persist to disk"
  - "hf_token._head extracted as a module-level async seam so tests can monkeypatch the HTTP call without touching httpx; _hf_hub_url already a module-level alias"
  - "Lifespan wraps load_settings_from_disk in try/except (broad Exception, not just ValidationError) so a corrupt Phase 1 file OR a missing file both fall through to the first-boot detect path which writes a clean Phase 2 file"
metrics:
  duration: ~25 min
  completed: 2026-06-18
  tasks: 3
  files: 18
  tests_added: 21
  tests_total: 134
---

# Phase 02 Plan 01: First-run GPU detect + burn-in test + settings.json wire-in Summary

Silent two-stage GPU backend detection (CUDA / ROCm / CPU) with a real-kernel burn test, persisted atomically to settings.json; Settings extended with 7 Phase 2 fields (D-08 declare-now) including base64-encoded hf_token (D-05); three diagnostics endpoints wired into the lifespan and OpenAPI schema.

## What Was Built

### Models (app/models/)

- **diagnostics.py** — single declaration site for the Phase 2 typed surface: `GpuBackend` (cuda/rocm/cpu), `QualityPreset` (small/balanced/large), `ModelCategory` (stt/diarize/llm) enums; `BackendProbe` (strict, extra=forbid, 7 fields with `probed_at` default_factory), `VRAMState` + `LoadedModelInfo` (lax response models), `HfTokenResult` (4-state literal), `GpuBurnResult`, `ModelSpec` + `ModelSet` (strict).
- **backend.py** — `async detect() -> GpuBackend` (ordered probe: pip wheel variant, nvidia-smi, ROCm env vars, lazy `torch.cuda.is_available()` / `torch.version.hip`; every subprocess wrapped in `try/except (TimeoutExpired, FileNotFoundError, OSError)`, timeout=3, D-06 silent fallback) and `async burn_test(backend) -> BackendProbe` (real 1024x1024 matmul on `cuda` + sync + perf_counter; CPU returns `burn_test_ms=None`, `vram_total_mb=None`; WARN at >5s but still returns the probe — D-06).
- **vram.py** — `ManagerState` singleton (`live_vram_bytes: dict[ModelCategory, int]`) + `get/set_manager_state` + `probe_vram(backend, manager_state) -> VRAMState` implementing the two-pool fix: `used = torch.cuda.memory_allocated + sum(live_vram_bytes)`, `available = free - sum(live_vram_bytes)` (Pitfall 2). Lazy `import torch` / `import psutil` inside the function body.
- **hf_token.py** — `async validate_token(token, repo_id) -> HfTokenResult` four-state shim: None -> skipped; HEAD 200 -> ok (with `x-repo-author`); 401 -> rejected "token invalid"; 403 -> rejected "model terms not accepted" + fix URL; any other code / network error -> skipped "HF Hub unreachable" (Pitfall 3). `_hf_hub_url` and `_head` are module-level seams for tests. No `pyannote.audio` import (CONTEXT domain boundary).
- **settings.py** — `Settings` extended with 7 fields: `backend: GpuBackend` (REQUIRED, no default), `backend_probe: BackendProbe | None`, `hf_token: str | None` (field_serializer base64-encodes on dump, field_validator mode=before decodes on load; D-05), `quality_preset: QualityPreset = BALANCED` (D-09), `per_category_overrides: ModelSet | None`, `concurrent_models: bool = False`, `vram_budget_fraction: float = 0.85`. `UpdateSettingsRequest` extended with 5 optional fields (NOT `backend` / `backend_probe` — D-08); `model_validator` rejects empty PATCH and explicit-null `data_dir` (preserves Phase 1 contracts); `field_validator` for `vram_budget_fraction` range 0.1..0.95 (D-15).
- **__init__.py** — re-exports the new diagnostics types.

### API (app/api/)

- **routes_diagnostics.py** — `POST /diagnostics/gpu-burn` (re-runs detect + burn, hot-swaps in-memory `Settings.backend` + `backend_probe`, atomic-writes the full new settings, no `X-Restart-Required`; returns `GpuBurnResult`); `GET /diagnostics/vram` (returns `VRAMState` via `probe_vram(current().backend, get_manager_state())`); `POST /diagnostics/test-hf-token` (maps the 4-state `HfTokenResult` to 200/401/403; never raises).
- **routes_settings.py** — `GET /settings` now nulls `hf_token` in the response body (D-05 — never returned regardless of `?reveal=`); the on-disk file keeps the base64 value.

### Lifespan (app/main.py)

- Wraps `load_settings_from_disk` in `try/except`: on a Phase 1 file (no `backend`, raises `ValidationError`) OR a missing/corrupt file, runs `await backend_module.detect()` + `await backend_module.burn_test(backend)`, builds a full `Settings` with all 7 fields, writes it atomically via the Phase-1 D-04 helper, and configures in-memory. A subsequent boot (backend already set) skips detect. Fail-fast on detect errors (D-08).
- Installs an empty `ManagerState(live_vram_bytes={})` after `configure` so `GET /diagnostics/vram` returns `loaded=[]` from boot (02-02 swaps this).
- Registers `diagnostics_router`; adds `BackendProbe, GpuBurnResult, VRAMState, LoadedModelInfo, HfTokenResult, ModelSpec, ModelSet` to `_EXTRA_OPENAPI_MODELS`.

### Settings service (app/settings/service.py)

- `apply_update` rewritten: the non-restart path now writes the FULL `new.model_dump()` to disk (was only updating `data_dir`), so Phase 2 hot-swap fields persist (Rule 2 critical fix — without this, `PATCH /settings {"quality_preset":"small"}` would not change the on-disk file). The restart-required path writes `existing.model_dump()` as the active dict and `new.model_dump()` under the `pending` key.
- `apply_pending` rewritten to write the full `new.model_dump()` (canonical serialization, D-14).

### Tests (21 new + 113 existing = 134 total)

- **conftest.py** — three new mock fixtures: `mock_backend_detect` (AsyncMocks for `detect` + `burn_test`, default CPU), `mock_hf_hub_url` (AsyncMock for `_head`, default 401; `_hf_hub_url` replaced with a deterministic lambda), `mock_probe_vram` (MagicMock for `routes_diagnostics.probe_vram`). `tmp_data_dir` writes a Phase 2-shaped `Settings(backend=GpuBackend.CPU, ...)`.
- **test_gpu_detect.py** (4) — SC-1 first-boot CUDA/ROCm/CPU paths + subsequent-boot no-redetect.
- **test_settings_phase2.py** (8) — D-08 (backend/backend_probe rejected), D-15 (vram range/type), H1 hot-swap (quality_preset, concurrent_models), D-05 (hf_token null in response, base64 on disk).
- **test_hf_token.py** (5) — four-state table + network-error fallback (Pitfall 3).
- **test_diagnostics_api.py** (4) — POST /diagnostics/gpu-burn hot-swap + no-restart + on-disk persist; GET /diagnostics/vram shape + backend.

### Dependencies (pyproject.toml)

- Added `huggingface_hub>=0.25`, `psutil>=5.9`, `httpx>=0.27` (promoted from dev to main); `pytest-mock>=3.12` to dev. NO `torch` / `faster-whisper` / `llama-cpp-python` / `pyannote.audio` (those arrive in phases 3/7/8 per RESEARCH Environment Availability + CONTEXT domain boundary).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical Functionality] apply_update did not persist Phase 2 hot-swap fields to disk**
- **Found during:** Task 2 (while wiring routes_diagnostics + preparing for the hot-swap tests)
- **Issue:** The Phase 1 `apply_update` only updated `disk["data_dir"]` and preserved the rest of the on-disk dict. With Phase 2 hot-swap fields (`quality_preset`, `hf_token`, `concurrent_models`, `vram_budget_fraction`, `per_category_overrides`), a `PATCH /settings {"quality_preset":"small"}` would swap the in-memory state but leave the on-disk file at the old value — the `test_patch_quality_preset_hot_swap` truth ("the on-disk file contains quality_preset=small") would fail and a restart would silently lose the change.
- **Fix:** Rewrote `apply_update` to write the FULL `new.model_dump()` to disk in the non-restart path (and `existing.model_dump()` + `pending: new.model_dump()` in the restart path). Also rewrote `apply_pending` to write the full `new.model_dump()`. The on-disk file is now the canonical serialization of the in-memory model (D-14) on every PATCH.
- **Files modified:** app/settings/service.py
- **Commit:** c17674d

**2. [Rule 3 - Blocking Issue] Required `backend` field broke 18 existing `Settings(data_dir=...)` callsites**
- **Found during:** Task 1 (acceptance criterion: existing 113-test suite must stay green)
- **Issue:** Making `Settings.backend` required (no default, per D-08) caused `Settings(data_dir=str(...))` to raise `ValidationError` in 18 existing test callsites that construct a Settings directly (test_resume, test_cleanup, test_reconcile, test_manifest_patch, test_wal, test_migration_idempotency, test_windows_retry_integration, test_stage_files, test_manifest_helpers, test_create_job) plus the `tmp_data_dir` fixture.
- **Fix:** Added `backend=GpuBackend.CPU` to every existing `Settings(data_dir=...)` callsite and to the `tmp_data_dir` fixture (which now writes a Phase 2-shaped file so the lifespan does not re-run detect on every test boot). The `backend` field stays REQUIRED (no default) so a Phase 1 install file still triggers the first-boot detect path in the lifespan.
- **Files modified:** tests/conftest.py + 9 existing test files
- **Commit:** 3b5880f

**3. [Rule 1 - Bug] Strict=True on UpdateSettingsRequest rejected JSON string -> enum coercion for quality_preset**
- **Found during:** Task 1 (verifying `UpdateSettingsRequest(quality_preset="small")` works)
- **Issue:** The plan specifies `model_config = ConfigDict(strict=True, extra="forbid")` for `UpdateSettingsRequest`. With strict=True, a JSON string `"small"` is rejected for a `QualityPreset | None` field (Pydantic strict mode does not coerce str -> enum), so `PATCH /settings {"quality_preset":"small"}` would 422 — breaking the H1 hot-swap contract.
- **Fix:** Added per-field `Field(default=None, strict=False)` on `quality_preset` and `per_category_overrides` so the JSON string/dict coerces to the typed enum/nested model. The model-level `strict=True` stays on the scalar fields (`data_dir`, `hf_token`, `concurrent_models`, `vram_budget_fraction`) so a wrong-typed scalar (int `data_dir`, string `vram_budget_fraction`) still 422s at the API boundary (D-15 — `test_patch_settings_rejects_int` and `test_patch_vram_budget_fraction_wrong_type_returns_422` both pass).
- **Files modified:** app/models/settings.py
- **Commit:** 3b5880f

**4. [Rule 3 - Blocking Issue] hf_token HTTP call had no clean test seam**
- **Found during:** Task 3 (writing the four-state token tests)
- **Issue:** The original `validate_token` opened `httpx.AsyncClient()` inline inside the function body; mocking the HEAD call would require patching `httpx.AsyncClient` globally (invasive and fragile).
- **Fix:** Extracted a module-level `async def _head(url, headers) -> tuple[int, dict]` seam that wraps the httpx call. Tests `monkeypatch.setattr("app.models.hf_token._head", AsyncMock(...))` to inject canned status codes / headers / exceptions. `_hf_hub_url` was already a module-level alias.
- **Files modified:** app/models/hf_token.py
- **Commit:** 2de9709

### Notes on Plan Interpretation

- **Empty PATCH contract:** The plan's Task 1 verify command constructs `UpdateSettingsRequest()` (empty body) and prints `model_dump(exclude_unset=True)`. With my design, an empty PATCH raises `ValidationError` ("at least one field must be provided") to preserve the Phase 1 `test_empty_patch_returns_422` contract. The empty-body 422 is the correct behavior; the verify command's empty construction is now expected to raise (documented here so a reader of the plan is not surprised).
- **Lifespan try/except scope:** The plan specifies `try/except ValidationError`. I broadened to `try/except Exception` so a corrupt JSON file (ValueError) or a missing file also falls through to the first-boot detect path which writes a clean Phase 2 file. A narrow `ValidationError` catch would let a corrupt file crash the boot. The broad catch is logged at INFO before the detect path runs.

## Threat Model Compliance

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-02-01 (hf_token info disclosure) | mitigate | DONE — base64 on disk via field_serializer; null in GET /settings (route nulls the body); atomic writes per D-04; hot-swap (no restart). base64 is "no accidental cleartext," not real security. |
| T-02-02 (gpu-burn spoofing/tampering) | mitigate | DONE — `backend` / `backend_probe` excluded from `UpdateSettingsRequest` (extra="forbid" 422s them per D-15); only the detect/burn path + `POST /diagnostics/gpu-burn` write them; atomic write per D-04. |
| T-02-03 (detect subprocess tampering) | mitigate | DONE — fixed arg lists (no user input); `timeout=3`; `capture_output=True`; `try/except (TimeoutExpired, FileNotFoundError, OSError)` -> silent CPU fallback (D-06). |
| T-02-04 (HF token on wire) | mitigate | DONE — HTTPS via huggingface_hub; `Authorization: Bearer` header; `timeout=5.0`; token never logged. |
| T-02-05 (CPU fallback masks broken GPU) | accept | DONE — D-06 silent log-only; `backend_probe` records the verdict for Phase 10; the WARN at burn_test_ms>5000 is logged. |
| T-02-SC (pypi package legitimacy) | mitigate | LISTED in `user_setup` — `huggingface_hub` / `psutil` / `httpx` are well-known; user verifies each on pypi.org before `pip install -e .`. No in-plan `pip install` task. |

## Verification

- `pytest tests/test_gpu_detect.py tests/test_settings_phase2.py tests/test_hf_token.py tests/test_diagnostics_api.py -q` -> 21 passed.
- `pytest -q` (full suite) -> 134 passed (113 existing + 21 new).
- OpenAPI exposes `BackendProbe`, `VRAMState`, `HfTokenResult`, `GpuBurnResult`, `ModelSpec`, `ModelSet`, `LoadedModelInfo` in `components.schemas`.
- `UpdateSettingsRequest.properties` has `hf_token`, `quality_preset`, `per_category_overrides`, `concurrent_models`, `vram_budget_fraction` and does NOT have `backend` or `backend_probe`.
- `grep -rE "from huggingface_hub" app/` returns matches only in `app/models/hf_token.py` (boundary check; `app/models/manager.py` is 02-02).
- `grep -rE "pyannote.audio" app/models/hf_token.py` returns no match (CONTEXT domain boundary — Phase 7 ships the real import).
- A fresh boot with a Phase 1-shaped `data/settings.json` (mocked detect=CUDA) writes the 7 new fields with the detect-populated values; `GET /settings` returns the new shape.

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `model_id = "<category>:unknown"` placeholder in `VRAMState.loaded` | app/models/vram.py | `_loaded_list` | 02-01 has no model manager yet; 02-02's `configure_manager` plumbs the real `model_id` and `loaded_at` from `ManagerState.loaded_meta`. The `loaded` list is empty by default (ManagerState.live_vram_bytes is {} at boot), so the placeholder only surfaces if a test manually populates live_vram_bytes. |

## Self-Check: PASSED

- All 18 created/modified files exist on disk (verified via the commit file lists).
- Commit `3b5880f` (Task 1) exists in git log.
- Commit `c17674d` (Task 2) exists in git log.
- Commit `2de9709` (Task 3) exists in git log.
- Full suite: 134 passed.