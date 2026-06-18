---
phase: 2
slug: gpu-backend-detection-model-manager
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-15
---

# Phase 2 Validation Contract

## Test Infrastructure

The Phase 2 test suite extends the existing `tests/conftest.py` fixture triplet (`tmp_data_dir` + `app_under_test` + `client`) with three new function-scoped fixtures. All new tests use the existing `httpx.AsyncClient` + `client` pattern. No new pytest plugins; no `conftest.py` rewrite.

| Fixture | Scope | Purpose | Plan |
|---------|-------|---------|------|
| `mock_hf_hub_url` | function | Patches `app.models.hf_token._hf_hub_url` and `httpx.AsyncClient.head` for the four-state token table | 02-01 |
| `mock_backend_detect` | function | Patches `app.models.backend.detect` + `app.models.backend.burn_test` for SC-1 paths | 02-01 |
| `mock_probe_vram` | function | Patches `app.models.vram.probe_vram` (extended in 02-02 to also patch `app.models.manager.hf_hub_download`) | 02-01, 02-02 |
| `configured_model_manager` | function | Builds a `ModelManager` from the test settings + `tmp_data_dir` and calls `configure_manager`; cleans up in `finally` | 02-02 |

The `tmp_data_dir` fixture is updated to write `Settings(data_dir=str(data_dir.resolve()), backend=GpuBackend.CPU, ...)` with the new field defaults so the lifespan does not re-run the detect on test boot. Existing tests that read the file by parsing JSON do not change.

## Sampling Rate

| Item | Sample count | Source of truth |
|------|--------------|-----------------|
| Settings round-trip fields (the 7 new fields + hf_token null-in-response) | 1 per field (8 tests) | `test_settings_phase2.py` |
| Detect paths (CUDA / ROCM / CPU + subsequent-boot) | 4 paths | `test_gpu_detect.py` |
| HF token four-state table (skipped / ok / 401 / 403 / network-error) | 5 tests | `test_hf_token.py` |
| Diagnostics API (gpu-burn / vram / test-hf-token) | 4 tests | `test_diagnostics_api.py` |
| Presets table (BALANCED stt/diarize/llm + override) | 4 tests | `test_presets.py` |
| Manager download (size/SHA / resume / gated / corrupt) | 4 tests | `test_manager_download.py` |
| VRAM budget (refuse / succeed / unload clears) | 3 tests | `test_vram_budget.py` |
| Concurrent models (refuse default / opt-in / openapi / unload-then-load) | 4 tests | `test_concurrent_models.py` |
| Spike contract guard (exists / sections / verdict / Phase 3 must-have) | 4 tests | `test_spike_documented.py` |
| **Total new test cases** | **40** | across 9 files |

## Per-Task Verification Map

| Task | Plan | SC-1 | SC-2 | SC-3 | SC-4 | SC-5 |
|------|------|------|------|------|------|------|
| Task 1: extend Settings + diagnostics + backend/vram/hf_token modules | 02-01 | ✓ | | | | |
| Task 2: lifespan first-boot detect + diagnostics routes | 02-01 | ✓ | | | | |
| Task 3: 4 new test files + conftest mock fixture | 02-01 | ✓ | | | ✓ | |
| Task 1: model registry + presets + storage helpers | 02-02 | | ✓ | | | |
| Task 2: ModelManager class + typed errors + structured log | 02-02 | | ✓ | ✓ | ✓ | ✓ |
| Task 3: model API routes + lifespan wire + 4 new test files | 02-02 | | ✓ | ✓ | ✓ | ✓ |
| Task 1: run the ROCm spike + write 02-03-SPIKE.md | 02-03 | ✓ | | | | |
| Task 2: contract-guard test for the spike deliverable | 02-03 | ✓ | | | | |

## Wave 0 Gap Checklist

Tests that MUST exist before the phase can be considered ready for execution. The gap-closure work is part of Wave 0 of execution; if any of these files is missing, the phase is not executable.

- [ ] `tests/test_gpu_detect.py` — covers SC-1 (CUDA, ROCM, CPU variants + subsequent-boot does-not-redetect)
- [ ] `tests/test_settings_phase2.py` — strict-input 422 for `backend` / `backend_probe`; `vram_budget_fraction` validator; hot-swap; HF token base64-on-disk + null-in-response
- [ ] `tests/test_hf_token.py` — four-state table + network-error fallback
- [ ] `tests/test_diagnostics_api.py` — gpu-burn updates in-memory + on-disk; vram returns the live state; test-hf-token returns the typed result
- [ ] `tests/test_presets.py` — BALANCED is the right triple; SMALL/LARGE entries exist; per-category override wins
- [ ] `tests/test_manager_download.py` — size/SHA verify; resume after crash; gated-repo 403; corrupt-SHA 500
- [ ] `tests/test_vram_budget.py` — refuse when over budget; succeed within budget; unload clears the live entry
- [ ] `tests/test_concurrent_models.py` — default refuses second model; opt-in allows; OpenAPI exposes the field; unload-then-load
- [ ] `tests/test_spike_documented.py` — contract guard for 02-03-SPIKE.md (4 tests)
- [ ] `tests/conftest.py` extended with `mock_hf_hub_url`, `mock_backend_detect`, `mock_probe_vram`, `configured_model_manager`

## Nyquist Compliance Checklist

The Nyquist rule: every `<verify>` in every task has an `<automated>` element that runs in under 60 seconds. Tasks without an automated verify MUST have a `<automated>MISSING — Wave 0 must create {test_file} first</automated>` and a scaffolded test file.

- [x] 02-01 Task 1: `<automated>python -c "from app.models...; print(...)"</automated>` — under 60s
- [x] 02-01 Task 2: `<automated>python -c "from app.api.routes_diagnostics import router; print([r.path for r in router.routes]); ..."</automated>` — under 60s
- [x] 02-01 Task 3: implicitly verified via `pytest -q` on the new test files
- [x] 02-02 Task 1: `<automated>python -c "from app.models.registry import REGISTRY, ...; print(...)"</automated>` — under 60s
- [x] 02-02 Task 2: `<automated>python -c "from app.models.manager import ModelManager, ...; print(...)"</automated>` — under 60s
- [x] 02-02 Task 3: `<automated>pytest tests/test_presets.py tests/test_manager_download.py tests/test_vram_budget.py tests/test_concurrent_models.py -q</automated>` — under 60s
- [x] 02-03 Task 1: `<automated>pytest tests/test_spike_documented.py -q</automated>` — under 60s (asserts the SPIKE file exists)
- [x] 02-03 Task 2: `<automated>pytest tests/test_spike_documented.py -q</automated>` — under 60s

**Nyquist compliance: PASS for all 8 tasks.** No `MISSING` placeholders. No manual-only verifications. Every task has a deterministic automated check that runs in under 60 seconds.

## Grep Gate Hygiene

The following grep gates are used by the acceptance criteria across the plans. They are designed to NOT be self-invalidating (no `== 0` on a `grep -c` of a file that has comment lines mentioning the pattern).

- [x] `grep -rE "from huggingface_hub" app/` — must return matches only in `app/models/manager.py` and `app/models/hf_token.py` (boundary check; the route layer + `app/main.py` must not import the library directly)
- [x] `grep -E "BackendProbe|VRAMState|LoadedModelInfo|...|ModelSet" app/main.py` — must return matches in `_EXTRA_OPENAPI_MODELS` (OpenAPI surface check)
- [x] `pytest tests/test_presets.py tests/test_manager_download.py tests/test_vram_budget.py tests/test_concurrent_models.py -q` — must exit 0
- [x] `pytest -q` (full suite) — must exit 0; the 113 Phase 1 tests + the 40 new tests = 153 total

## Open Questions for Verify-Phase

These are questions that the executor or verifier should answer in their report (or carry into a follow-up gap-closure plan if the answer is "no"):

1. Does the laptop (CUDA) first-boot path actually detect a real NVIDIA GPU and write `backend: "cuda"` to `data/settings.json`? (Currently mocked in tests; verifier runs against real hardware.)
2. Does the desktop (ROCM) first-boot path install the TheRock nightly wheel and write `backend: "rocm"`? (Depends on the 02-03 spike verdict; if the spike says FALLBACK, the detect returns CPU.)
3. Does the structured per-model VRAM log line appear in the back-end logs at the right format (parseable as JSON)? (Verified by the caplog test; the verifier should also run a smoke test against the real `python -m app` and read the log file.)
4. Does the `GET /openapi.json` schema contain the new types? (Verified by a single command in the verification section.)
5. Does the 02-03 spike deliverable's §5 "What Phase 3 must do" section name the `device: Literal['cuda', 'cpu', 'rocm']` arg shape that Phase 3's STT adapter must accept? (The contract guard asserts "must" is in the section; the verifier should also eyeball the section for completeness.)
6. Does the boundary check (`grep -rE "from huggingface_hub" app/`) confirm no leak of the `huggingface_hub` import into the route layer or `app/main.py`?

## Status

- `status: draft` — the plans are written; the spike is pending the user's action
- `nyquist_compliant: false` — will flip to `true` after execution completes and the full suite is green
- `wave_0_complete: false` — will flip to `true` after execution completes the test-file scaffolding in Wave 0 of 02-01
