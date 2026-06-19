---
phase: 02-gpu-backend-detection-model-manager
verified: 2026-06-19T10:30:00Z
status: passed
score: 5/5 ROADMAP success criteria verified · 5/5 phase requirements (HW-02, HW-03, HW-04, HW-07, HW-09) accounted for · 188/188 tests green
source:
  - .planning/ROADMAP.md
  - .planning/REQUIREMENTS.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-01-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-02-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-04-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-05-PLAN.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-01-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-02-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-04-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-05-SUMMARY.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-UAT.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-REVIEW.md
  - .planning/phases/02-gpu-backend-detection-model-manager/02-03-SPIKE.md
reviewed_at: 2026-06-19
scope: Read-only adversarial re-verification. Verifier did not modify source. Closes the SC-3 + SC-4 UAT gaps via source inspection, AST gate, targeted pytest, and the full 188-test suite.
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 5/5 SC · 155/155 tests (initial verification, pre-UAT)
  gaps_closed:
    - "SC-3 download contract: hf_hub_download offloaded via asyncio.to_thread; classic non-Xet resume path forced (hf_xet=False + HF_HUB_DISABLE_XET=1); 5 live-behavior tests lock 409 dedupe + live SSE heartbeat + byte progress + resume"
    - "SC-4 vram indicator on CPU: probe_vram CPU error-fallbacks return loaded=_loaded_list(manager_state); psutil installed in runtime env; 3 live tests lock the contract (psutil-present, psutil-absent, empty-state)"
  gaps_remaining: []
  regressions: []
---

# Phase 02 — GPU Backend Detection + Model Manager · Verification Report

**Mode:** mvp (per ROADMAP.md; success-criteria-driven)
**Goal (from ROADMAP.md):** The system auto-detects CUDA vs ROCm vs CPU on first run, persists the choice, and owns the lifecycle of every local model on disk and in VRAM.
**Verifier mode:** adversarial / goal-backward. SUMMARY claims are not evidence; only source code, tests, and live gates count.
**Result:** **VERIFIED — all 5 ROADMAP success criteria pass; 5/5 phase requirements accounted for; 188/188 tests green; the two UAT gaps (SC-3 download, SC-4 vram indicator) are closed in code and locked by integration tests; one open concurrency-risk note (CR-01) recorded below as a verified-in-single-thread / open-concurrency-risk item, NOT a hard gap.**

---

## 1. ROADMAP Success Criteria (5/5 PASS)

### SC-1: First run silently writes `settings.json` with the right backend; re-detect via `POST /diagnostics/gpu-burn`

**Status: PASS (regression check — unchanged by 02-04/02-05)**

- `app/models/backend.py` `async def detect() -> GpuBackend` + `async def burn_test(backend) -> BackendProbe` unchanged (not in 02-04/02-05 file lists).
- `app/main.py` lifespan first-boot detect + atomic write unchanged.
- `POST /diagnostics/gpu-burn` hot-swap route unchanged.
- `tests/test_gpu_detect.py` + `tests/test_diagnostics_api.py` (4 + 4 SC-1 tests) green in the 188-test run.

### SC-2: Default model set fits within 8 GB laptop VRAM; per-model VRAM budget logged on load

**Status: PASS (regression check — unchanged by 02-04/02-05)**

- `app/models/presets.py` BALANCED triple (faster-whisper-large-v3 + pyannote/speaker-diarization-3.1 + Qwen2.5-7B-Instruct Q4_K_M) unchanged.
- `app/models/manager.py:load` VRAM budget gate + structured INFO log line unchanged (the 02-04 edit was inside `ensure_downloaded`, not `load`).
- `tests/test_presets.py` + `tests/test_vram_budget.py` green.

### SC-3: Model manager downloads, verifies size + SHA, exposes a download log, supports resume after crash

**Status: PASS (gap closed by 02-04)**

- **Thread offload (root cause A fixed):** `app/models/manager.py:ensure_downloaded` wraps BOTH `hf_hub_download` calls (primary + bounded retry) in `asyncio.to_thread(...)`. AST gate (02-04 Task 1 `<verify><automated>`) prints `ok` — 0 direct `hf_hub_download` Call nodes, 2 offloaded calls. `import asyncio` is now at the module top.
- **Classic non-Xet resume path forced (root cause B fixed):** `hf_xet=False` is passed to `hf_hub_download` when the installed version supports the kwarg (version-gated via `inspect.signature`, huggingface_hub>=0.26); on older versions `HF_HUB_DISABLE_XET=1` is set in `os.environ` around the call and restored in a `finally`. Verified by `grep -nE "hf_xet|HF_HUB_DISABLE_XET" app/models/manager.py` → hits at lines 264, 267, 331-332, 336, 340, 350-351, 357-358, 404, 406.
- **WR-01 409 dedupe:** `app/api/routes_models.py:download_model` 409 branch (`_in_flight` state in `{queued, running}`) was correct but unreachable while the event loop was frozen; the thread offload alone makes it fire. Locked by `tests/test_download_routes.py::test_download_duplicate_in_flight_returns_409` (asserts `body.detail.error == "download_in_flight"`).
- **WR-02 live SSE:** `tests/test_download_routes.py::test_download_progress_sse_streams_live` + `test_download_progress_byte_level` use the new `slow_mock_hf_hub_download` conftest fixture (a thread-blocking side_effect controlled by a `threading.Event`, writing byte increments every ~0.5s, released after ~6s) so the 5s `: ping` heartbeat at `routes_models.py:264` fires WHILE the download is in-flight. Both pass in the 188-test run.
- **HW-09 resume:** `tests/test_download_routes.py::test_resume_after_crash_uses_classic_path` asserts `hf_hub_download` was called with `hf_xet=False` AND without `force_download`. The classic `.incomplete` + HTTP Range resume path the `_poll_bytes` scanner assumes now actually applies.
- **SHA verification path unchanged:** `app/models/manager.py:_sha256_of_file` + the post-download SHA verify with bounded 1-retry → `ModelIntegrityError` (lines 370-399) are intact. `expected_sha256` is None for the current registry entries (deferred per `registry.py:20-23`), but the code path is present and test-covered (`tests/test_manager_download.py`).
- **New AST source-contract guard:** `test_hf_hub_download_is_offloaded_to_thread` permanently locks the offload (a future regression to a direct sync call fails fast).

### SC-4: Loading blocks past 85% VRAM; unload explicit on idle; "what's in VRAM" indicator exposed

**Status: PASS (gap closed by 02-05)**

- **CPU error-fallback fix (root cause D fixed):** Both CPU `except Exception:` fallbacks in `app/models/vram.py:probe_vram` (import-fail ~149-155, psutil-call-fail ~167-173) now return `loaded=_loaded_list(manager_state)` instead of `loaded=[]`. Source gate: `cpu_branch.count('loaded=[]') == 0` and `cpu_branch.count('loaded=_loaded_list(manager_state)') >= 3` → prints `ok`. Full-file grep: 8 `loaded=_loaded_list(manager_state)` hits (DIRECTML/VULKAN, CPU import-fail, CPU success, CPU psutil-call-fail, CUDA import-fail, CUDA not-available, CUDA success, CUDA exception); the only `loaded=[]` is in the module docstring (line 14, describing boot state). Uniform graceful degradation across every branch; `probe_vram` still never raises.
- **psutil installed (root cause E fixed):** `pip install -e .` user_setup installed `psutil-7.2.2` (>= 5.9 declared in `pyproject.toml:24`). Verified by `python -c "import psutil; print(psutil.__version__)"` → `7.2.2`. Recorded in 02-05 SUMMARY "User setup" so env rebuilds preserve it.
- **Live tests lock the contract:** `tests/test_diagnostics_api.py::test_get_vram_reflects_loaded_model_on_cpu` (psutil present, asserts `backend=="cpu"`, `total_mb > 0`, `len(loaded)==1`, `loaded[0].category=="stt"`); `test_get_vram_loaded_when_psutil_absent` (inline `no_psutil` fixture via `monkeypatch.setitem(sys.modules, "psutil", None)` — asserts `total_mb==0` AND `len(loaded)==1` — the exact UAT failure mode); `test_get_vram_empty_when_nothing_loaded` (regression guard). All three pass in the 188-test run.
- **507 + idempotent 204 unload unchanged:** `tests/test_vram_budget.py` (3 tests) green.
- The `no_psutil` + `cpu_manager` fixtures are defined INLINE in `tests/test_diagnostics_api.py` (not in conftest.py — 02-04 owns the conftest edit this wave); `cpu_manager` mirrors `configured_model_manager` but does NOT pull `mock_probe_vram` so the real CPU branch runs.

### SC-5: No two models resident concurrently unless the user opts in via a hidden-by-default settings toggle

**Status: PASS (regression check — unchanged by 02-04/02-05)**

- `app/models/settings.py` `concurrent_models: bool = False` (D-04 default-off, hidden by default) unchanged.
- `app/models/manager.py:load` `ConcurrentModelRefused` → 409 unchanged (the 02-04 edit was inside `ensure_downloaded`, not `load`).
- `tests/test_concurrent_models.py` (4 tests) green.

---

## 2. Requirements Coverage (5/5 accounted for)

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| HW-02 | 02-01, 02-02 | Transcription/diarization/LLM run on local models on GPU | SATISFIED (lifecycle layer) | ModelManager owns lifecycle (download/verify/load/unload/VRAM reservation). GPU inference execution is intentionally deferred to Phase 3/7/8 per REQUIREMENTS.md HW-02 row ("lifecycle in 02-02; actual GPU inference in Phase 3/7/8") and the 02-02 SUMMARY Known Stubs. The phase goal ("owns the lifecycle of every local model on disk and in VRAM") is achieved; real weight loading is out of scope for Phase 2. |
| HW-03 | 02-01, 02-03 | App auto-detects GPU (CUDA vs ROCm vs CPU) on first run, configures backends silently | SATISFIED | `detect()` + `burn_test()` + lifespan first-boot write (02-01); `02-03-SPIKE.md` verdict `ROCM_FALLBACK_TO_CPU` is the empirical evidence on the actual desktop; the fallback chain is proven. Contract guard test green. |
| HW-04 | 02-02 | App downloads its own models on first run; user can swap model variants in settings | SATISFIED (download + swap mechanism) | `ensure_downloaded` via `hf_hub_download` (resumable, now thread-offloaded + classic non-Xet path); `per_category_overrides` + `active_model_set` resolver (override > preset, HW-06 mechanism). The settings-panel UI for swapping is Phase 10 (REQUIREMENTS.md maps HW-05/HW-06/HW-08 to Phase 10). The Phase 2 contract is the download + the per-category override data layer, both present. |
| HW-07 | 02-02, 02-05 | Default model set fits the 8 GB laptop VRAM budget | SATISFIED | BALANCED triple verified; budget math (0.85 × 8192 = 6963 MB ≥ 5.15 GB LLM estimate) holds; `tests/test_presets.py` green. 02-05 restored the SC-4 vram indicator that reports the loaded model on CPU (the HW-07 diagnostics surface). |
| HW-09 | 02-02, 02-04 | Per-job VRAM discipline: on-demand load, idle unload, no concurrent multi-model residency | SATISFIED | `load` on demand (D-01), `unload` explicit-only idempotent (D-03), `ConcurrentModelRefused` 409 when `concurrent_models=False` (D-04). 02-04 closed the download-resume half of HW-09 (classic non-Xet `.incomplete` + Range path forced + thread offload so the 409 dedupe fires). Tests green. |

### Orphaned Requirements Check

`REQUIREMENTS.md` traceability table maps exactly HW-02, HW-03, HW-04, HW-07, HW-09 to Phase 2 — no orphaned IDs. All five are claimed by the PLANs (02-01: HW-02, HW-03; 02-02: HW-02, HW-04, HW-07, HW-09; 02-03: HW-03; 02-04: HW-09; 02-05: HW-07). No orphans.

---

## 3. Required Artifacts (all VERIFIED)

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `app/models/backend.py` | detect() + burn_test() | VERIFIED | unchanged by 02-04/02-05; regression-green. |
| `app/models/vram.py` | probe_vram with uniform `loaded=_loaded_list(manager_state)` on every branch | VERIFIED | 02-05 fix: 8 hits of `loaded=_loaded_list(manager_state)`, 0 `loaded=[]` in CPU branch (only docstring hit). Source gate prints `ok`. |
| `app/models/manager.py` | ensure_downloaded offloaded + classic non-Xet resume + SHA verify | VERIFIED | 02-04 fix: AST gate → 0 direct `hf_hub_download` calls, 2 `asyncio.to_thread` offloads, `hf_xet` + `HF_HUB_DISABLE_XET` present. SHA verify path at lines 370-399 intact. |
| `app/api/routes_models.py` | 6 model routes + 409 dedupe + SSE + error mapping | VERIFIED | 409 dedupe at line 200 (`download_in_flight`); `_in_flight` dict at line 61; `asyncio.create_task(_run_download(...))` at line 212; SSE generator with `: ping` heartbeat. All 6 routes registered. |
| `tests/test_download_routes.py` | 5 live-behavior tests for SC-3 | VERIFIED | 5 tests collected, all pass: `test_hf_hub_download_is_offloaded_to_thread` (AST guard), `test_download_duplicate_in_flight_returns_409` (WR-01), `test_download_progress_sse_streams_live` (WR-02 heartbeat), `test_download_progress_byte_level` (byte progress), `test_resume_after_crash_uses_classic_path` (HW-09). |
| `tests/test_diagnostics_api.py` | 4 existing + 3 new SC-4 tests | VERIFIED | 7 tests collected, all pass: existing 4 + `test_get_vram_loaded_when_psutil_absent`, `test_get_vram_reflects_loaded_model_on_cpu`, `test_get_vram_empty_when_nothing_loaded`. |
| `tests/conftest.py` | `slow_mock_hf_hub_download` fixture added; existing `mock_hf_hub_download` untouched | VERIFIED | `slow_mock_hf_hub_download` at line 269; `mock_hf_hub_download` at line 230 (untouched). |
| `02-03-SPIKE.md` | 5-section spike + verdict | VERIFIED | unchanged; contract guard test green. |

---

## 4. Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `app/api/routes_models.py:_run_download` | `app/models/manager.py:ensure_downloaded` | `await manager.ensure_downloaded(spec, category)` which internally awaits `asyncio.to_thread(hf_hub_download, ...)` | WIRED | `routes_models.py:156` await + `manager.py:361/387` `asyncio.to_thread` confirmed. |
| `app/api/routes_models.py:download_model` | `_in_flight` running-state check | HTTP 409 on duplicate in-flight | WIRED | `routes_models.py:200` `"error": "download_in_flight"`; locked by `test_download_duplicate_in_flight_returns_409`. |
| `app/api/routes_diagnostics.py (GET /diagnostics/vram)` | `app/models/vram.py:probe_vram` | `probe_vram(backend, manager_state)` returns `VRAMState` with `loaded` populated from `manager_state` on EVERY branch | WIRED | 8 hits of `loaded=_loaded_list(manager_state)`; locked by `test_get_vram_reflects_loaded_model_on_cpu` + `test_get_vram_loaded_when_psutil_absent`. |
| `app/models/vram.py CPU error-fallbacks` | `app.models.vram._loaded_list(manager_state)` | `loaded=_loaded_list(manager_state)` instead of `loaded=[]` | WIRED | 02-05 fix verified by source gate. |
| `app/models/manager.py:ensure_downloaded` | `huggingface_hub.hf_hub_download` | `asyncio.to_thread(hf_hub_download, **_download_kwargs())` with `hf_xet=False` | WIRED | AST gate + `test_resume_after_crash_uses_classic_path`. |
| `app/main.py` | `app/models/manager.py` | lifespan `configure_manager(ModelManager(...))` + teardown `unload_all` | WIRED | unchanged by 02-04/02-05. |
| `app/models/presets.py` | `app/models/settings.py` | `active_model_set(settings)` reads `quality_preset` + `per_category_overrides` | WIRED | unchanged; resolver present. |

---

## 5. Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `GET /diagnostics/vram` `loaded` | `ManagerState.loaded_meta` | `ModelManager.load` records `LoadedModel` per category; `_loaded_list(manager_state)` surfaces it on EVERY probe_vram branch | Yes (populated by real load calls; empty by default — correct) | FLOWING |
| `POST /models/{id}/download` | `hf_hub_download` | HuggingFace Hub (network), thread-offloaded | Real (mocked in tests via `slow_mock_hf_hub_download` + `mock_hf_hub_download`; production path is the real library call) | FLOWING |
| `GET /models/{id}/download-progress` SSE | `_in_flight[id]` + `_poll_bytes` scanner | `DownloadProgress` updated by background task + `.incomplete` byte scanner | Real (mocked with incremental byte writes in `slow_mock_hf_hub_download`) | FLOWING |
| `POST /diagnostics/gpu-burn` `probe` | `backend.detect()` + `burn_test()` | Subprocess + lazy torch on the real box | Yes (real-kernel matmul; CPU returns nulls per D-06) | FLOWING |

---

## 6. Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| AST gate: 0 direct hf_hub_download, 2 offloaded, xet disabled | `python -c "import ast; ..."` (02-04 Task 1 verify) | `direct calls: 0 / offloaded calls: 2 / hf_xet: True / HF_HUB_DISABLE_XET: True / asyncio imported: True` | PASS |
| vram.py CPU branch: no `loaded=[]`, ≥3 `_loaded_list` | `python -c "src=open(...); cpu=src[...]; assert cpu.count('loaded=[]')==0; assert cpu.count('loaded=_loaded_list(manager_state)')>=3; print('ok')"` | `ok` | PASS |
| Full-file `loaded=_loaded_list(manager_state)` hits | `grep -nE "loaded=_loaded_list\(manager_state\)" app/models/vram.py` | 8 hits (lines 143, 154, 164, 172, 184, 194, 206, 214) | PASS |
| `loaded=[]` only in docstring | `grep -nE "loaded=\[\]" app/models/vram.py` | 1 hit at line 14 (module docstring, boot state) — 0 in code paths | PASS |
| New SC-3 tests exist | `pytest tests/test_download_routes.py --collect-only` | 5 tests collected | PASS |
| New SC-4 tests exist | `pytest tests/test_diagnostics_api.py --collect-only` | 7 tests collected (4 existing + 3 new) | PASS |
| Targeted SC-3 + SC-4 tests | `pytest tests/test_download_routes.py tests/test_diagnostics_api.py -q` | 12 passed in 64.77s | PASS |
| Full test suite | `python -m pytest -q` | 188 passed in 295.02s | PASS |
| psutil installed in runtime env | `python -c "import psutil; print(psutil.__version__)"` | `7.2.2` (>= 5.9) | PASS |
| SHA256 verify path present | `grep -nE "sha256|ModelIntegrityError" app/models/manager.py` | `_sha256_of_file` at line 192; post-download verify at 370-399; `ModelIntegrityError` at 119 | PASS |
| No debt markers in modified files | `grep -nE "TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER" app/models/manager.py app/api/routes_models.py app/models/vram.py tests/conftest.py tests/test_download_routes.py tests/test_diagnostics_api.py` | 0 hits | PASS |
| Gap-closure commits present | `git log --oneline -15` | 243362b, 7dc1dec, eae3776 (02-04); 9f07bc8, f0b7608, fec16e7 (02-05) all present | PASS |

---

## 7. Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| SC-3 + SC-4 targeted suite | `pytest tests/test_download_routes.py tests/test_diagnostics_api.py -q` | 12 passed in 64.77s | PASS |
| Full suite | `python -m pytest -q` | 188 passed in 295.02s (0 failed, 0 skipped) | PASS |
| AST source-contract gate (02-04 Task 1) | `python -c "import ast; ..."` | `ok` (0 direct, 2 offloaded, xet disabled) | PASS |
| vram.py CPU branch gate (02-05 Task 1) | `python -c "...assert cpu.count('loaded=[]')==0; assert cpu.count('loaded=_loaded_list(manager_state)')>=3; print('ok')"` | `ok` | PASS |

---

## 8. Anti-Patterns Scan

No blocker debt markers (`TBD`/`FIXME`/`XXX`) in any Phase 2 file modified this wave. No `TODO`/`HACK`/`PLACEHOLDER` either.

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `app/models/manager.py` | 357-406 | `HF_HUB_DISABLE_XET` env var mutated from concurrent worker threads with no lock (CR-01 from 02-REVIEW.md) | WARNING (open concurrency risk) | See §9 Open Concurrency Risk Note. NOT a hard gap: the single-download contract (one user, one model at a time, loopback box) holds; the env-var save/restore is correct for the single-thread case. The `hf_xet=False` kwarg is per-call and thread-safe, so on huggingface_hub>=0.26 the env-var path is a redundant belt-and-suspenders fallback. |
| `app/api/routes_models.py` | 212 | Fire-and-forget `asyncio.create_task` with no stored reference (WR-01 from 02-REVIEW.md) | WARNING (robustness) | CPython's asyncio docs warn the task can be GC'd mid-download. Not exercised by current tests. Does not break the SC-3 contract under single-download use. |
| `app/api/routes_models.py` | 155-176 | `_run_download` does not set `progress.state` on `asyncio.CancelledError` (WR-02 from 02-REVIEW.md) | WARNING (robustness) | On cancellation the SSE client hangs on a "running" frame. Not exercised by current tests; cancellation is not in the SC-3 contract. |
| `tests/test_download_routes.py` | 122-165, 176-220 | Live SSE tests depend on real 5-7s wall-clock timers (WR-05 from 02-REVIEW.md) | INFO (test flakiness risk) | Tests pass on this machine (64.77s for 12 tests). May flake on a loaded CI runner; not a goal blocker. |

No `TBD` / `FIXME` / `XXX` debt markers. The `ModelManager.load` is a typed VRAM reservation by design (not a stub) — Phase 3/7/8 adapters own the real weight loading; this is the intentional deferral of HW-02's GPU-inference-execution layer.

---

## 9. Open Concurrency Risk Note (CR-01)

**Item:** `app/models/manager.py:357-406` sets `os.environ["HF_HUB_DISABLE_XET"] = "1"` before `await asyncio.to_thread(hf_hub_download, ...)` and restores it in a `finally`. `asyncio.to_thread` runs the body on the default `ThreadPoolExecutor`, so two concurrent downloads (e.g. `POST /models/small.stt/download` and `POST /models/balanced.llm/download` issued back-to-back) execute in two worker threads simultaneously. The save/restore is per-call and unsynchronized: thread A's `finally` can `pop` the env var while thread B is still inside `hf_hub_download`, silently re-enabling the Xet backend for B's download — exactly the HW-09 regression 02-04 was written to prevent.

**Classification:** Verified-in-single-thread / open-concurrency-risk — NOT a hard gap.

**Reasoning:**
- The phase goal's "model download with SHA verification" + HW-09 "resume after crash" contract is a single-user, single-model-at-a-time contract on a loopback box. The SC-5 concurrent_models=False default (D-04) means the manager refuses a second model load while one is resident; download concurrency is not a stated SC-3 requirement.
- The single-download path (the contract being verified) is correct: the env var is set before the call, restored after, and the `hf_xet=False` kwarg is also passed (per-call, thread-safe) on huggingface_hub>=0.26. The integration tests (`test_resume_after_crash_uses_classic_path`, `test_download_duplicate_in_flight_returns_409`) pass.
- The 02-REVIEW.md recommended fix is a one-liner: `os.environ.setdefault("HF_HUB_DISABLE_XET", "1")` at module load / lifespan startup, removing the save/restore block. This is a robustness improvement, not a goal blocker.

**Recommendation:** Address CR-01 in a future robustness pass (Phase 3 download orchestration, or a Phase 2.6 hardening plan) alongside WR-01 (fire-and-forget task ref) and WR-02 (CancelledError handling). Until then, the app's documented usage pattern (one download at a time) is safe.

---

## 10. Human Verification Required

None required for phase closure. The two UAT gaps (SC-3, SC-4) were live-confirmed by the user in `02-UAT.md` (the failure modes were observed live), and the gap-closure fixes are locked by integration-level tests that reproduce the exact failure modes (`test_get_vram_loaded_when_psutil_absent` reproduces the SC-4 UAT trigger; `test_download_duplicate_in_flight_returns_409` + `test_download_progress_sse_streams_live` reproduce the SC-3 UAT trigger via the slow in-flight mock). The previous V-UAT live boot was the human confirmation; the fixes restore the contract the human originally verified.

Optional (not blocking) live re-confirmation: `uvicorn app.main:app`, POST `/models/small.stt/download` → 202, immediately POST again → 409, GET `/models/small.stt/download-progress` shows live `event: progress` + `: ping` lines while downloading; POST `/models/small.stt/load` → 200, GET `/diagnostics/vram` → `loaded:[{category:stt,...}]` with `total_mb > 0`. This is the same live check the 02-04 and 02-05 SUMMARYs mark as "post-execute, not run by the executor"; the integration tests cover the same contract.

---

## 11. Deferred Items (Step 9b)

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Real GPU weight loading (faster-whisper / llama-cpp-python / pyannote.audio inference execution) | Phase 3 / 7 / 8 | ROADMAP Phase 3 goal: "proves the GPU abstraction works"; Phase 7 "pyannote adapter"; Phase 8 "llama-cpp-python adapter". REQUIREMENTS.md HW-02 row: "actual GPU inference in Phase 3/7/8". 02-02 SUMMARY Known Stubs documents this explicitly. |
| 2 | Prefetch-at-submit + auto-swap load policy | Phase 4 | 02-02 PLAN: "prefetch-at-job-submit (per D-02 just-in-time at stage start is a Phase 4 orchestrator concern; Phase 2 is the mechanism, Phase 4 is the policy)". ROADMAP Phase 4: "Job Orchestrator + Persistent Queue". |
| 3 | Settings panel UI for quality preset + per-category override + concurrent_models toggle | Phase 10 | ROADMAP Phase 10 goal: "Settings Panel + Quality Preset + Per-Category Overrides". REQUIREMENTS.md maps HW-05/HW-06/HW-08 to Phase 10. Phase 2 ships the data layer (`per_category_overrides`, `active_model_set`, `concurrent_models`), not the UI. |
| 4 | CR-01 concurrency hardening (HF_HUB_DISABLE_XET lock) + WR-01/WR-02 download-task robustness | Robustness pass (Phase 3 or Phase 2.6) | 02-REVIEW.md §Critical + §Warnings. The single-download contract holds; concurrent download hardening is a robustness improvement, not a Phase 2 SC. |

---

## 12. Gaps Summary

No gaps. All 5 ROADMAP success criteria pass (SC-3 + SC-4 gaps from 02-UAT.md closed by 02-04 + 02-05); all 5 phase requirements are satisfied (HW-02 at the lifecycle layer per the project's explicit deferral; the rest end-to-end); all artifacts exist, are substantive, and are wired; data flows are real; the full suite is green (188 passed, +33 from the 155 baseline: 5 new SC-3 tests + 3 new SC-4 tests + 25 from other phase work); the boundary checks are clean; no debt markers; the 02-03 spike verdict is valid empirical evidence for HW-03 per D-07.

The one open item (CR-01 concurrency risk in `HF_HUB_DISABLE_XET` save/restore) is recorded as a verified-in-single-thread / open-concurrency-risk NOTE, not a gap: the single-download HW-09 contract holds and is test-locked; concurrent download hardening is deferred to a future robustness pass.

---

_Verified: 2026-06-19_
_Verifier: Claude (gsd-verifier)_