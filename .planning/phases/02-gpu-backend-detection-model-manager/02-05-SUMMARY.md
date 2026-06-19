---
phase: 02-gpu-backend-detection-model-manager
plan: 05
subsystem: back-end (diagnostics / vram indicator)
tags: [gap-closure, sc-4, vram, cpu, psutil, graceful-degradation, tdd]
requires:
  - 02-02 (ModelManager + ManagerState + _loaded_list + probe_vram)
  - 02-UAT (SC-4 gap diagnosis)
provides:
  - "probe_vram CPU error-fallbacks preserve loaded=_loaded_list(manager_state) (uniform graceful degradation)"
  - "Live-behavior tests locking the WR-03 / SC-4 vram indicator contract on CPU"
affects:
  - app/models/vram.py
  - tests/test_diagnostics_api.py
tech-stack:
  added: []
  patterns:
    - "lazy in-body import (psutil) with graceful-degradation fallback that still surfaces the loaded list"
    - "inline test fixtures (no_psutil, cpu_manager) to avoid a parallel conftest edit"
key-files:
  created: []
  modified:
    - app/models/vram.py
    - tests/test_diagnostics_api.py
decisions:
  - "CPU error-fallbacks aligned with every other backend (loaded=_loaded_list(manager_state) instead of loaded=[]); total/available/used stay 0 to signal 'RAM probe unavailable' while the indicator still shows what is loaded."
  - "psutil stays a lazy in-body import (NOT a top-level import) so CPU-only test envs without psutil do not crash on module import."
  - "no_psutil + cpu_manager fixtures defined INLINE in tests/test_diagnostics_api.py (02-04 owns conftest.py this wave; a parallel conftest edit would risk a merge conflict)."
  - "cpu_manager mirrors configured_model_manager but WITHOUT mock_probe_vram so the real probe_vram CPU branch runs with real psutil reads (the mock forces backend='cuda', which would hide the CPU fallback the SC-4 fix is about)."
metrics:
  duration: ~12 min
  completed: 2026-06-19
  tasks: 2
  files: 2
  tests-added: 3
  tests-total: 188
---

# Phase 02 Plan 05: SC-4 VRAM Indicator CPU Graceful-Degradation Fix Summary

Restored the WR-03 "what's in VRAM" indicator contract on the CPU path: `probe_vram`'s two CPU error-fallbacks now return `loaded=_loaded_list(manager_state)` instead of `loaded=[]`, so `/diagnostics/vram` reflects the loaded model even when the psutil RAM probe fails (the exact SC-4 UAT trigger). Locked with 3 live-behavior tests.

## User setup

- **`pip install -e .`** run once before execution (env sync, not a code change). `psutil` (declared `>=5.9` in `pyproject.toml` line 24) was NOT installed in the runtime env — this is what triggered the SC-4 failure live (`ModuleNotFoundError: import of psutil`). Installed `psutil-7.2.2`. Verified via `python -c "import psutil; print(psutil.__version__)"` -> `7.2.2` (>= 5.9). Recorded here so env rebuilds preserve it; NOT a repeatable verify step and NOT a pyproject change.

## What was built

### Task 1 — Fix CPU error-fallbacks in `probe_vram` (TDD RED -> GREEN)

**Root cause (from 02-UAT):** `probe_vram`'s two CPU `except Exception:` fallbacks (vram.py import-fail ~149-155 and psutil-call-fail ~167-173) returned `loaded=[]`. Every other backend branch (DIRECTML/VULKAN stub, CPU success, all three CUDA fallbacks) returned `loaded=_loaded_list(manager_state)`. The defect was triggered live because `psutil` was declared in `pyproject.toml` but not installed in the runtime env, so `import psutil` raised -> CPU fallback -> `loaded=[]` immediately after a 200 load. The prior WR-03 fix in 02-REVIEW-FIX only changed the CPU SUCCESS branch (vram.py:164), not the two error-fallbacks, so it did not hold live when psutil was missing.

**Fix (2-line):** Both CPU error-fallback `VRAMState(...)` constructions now pass `loaded=_loaded_list(manager_state)` instead of `loaded=[]`. The CPU success branch (159-165) is unchanged (already correct). `total_mb`/`available_mb`/`used_mb` stay 0 on the fallback (correctly signals "RAM probe unavailable" while still showing what is loaded). psutil stays a lazy in-body import (NOT a top-level import) so CPU-only test envs without psutil do not crash on module import.

After the fix, ALL four CPU-branch returns (DIRECTML/VULKAN stub, CPU import-fail, CPU psutil-call-fail, CPU success) and all three CUDA-branch returns use `loaded=_loaded_list(manager_state)` — uniform graceful degradation. `probe_vram` still never raises.

**TDD flow:**
- RED: added `test_get_vram_loaded_when_psutil_absent` + inline `no_psutil` + `cpu_manager` fixtures. Verified the test FAILS (`assert len(body["loaded"]) == 1` -> `assert 0 == 1`) against the unfixed code. Commit `9f07bc8`.
- GREEN: applied the 2-line fix. Verified the test PASSES. Commit `f0b7608`.

### Task 2 — Live CPU loaded-model + empty-state coverage

Added 2 tests (the psutil-absent variant was added under Task 1 RED; total 3 new tests):
- `test_get_vram_reflects_loaded_model_on_cpu` — psutil present: POST `/models/small.stt/load` -> 200, GET `/diagnostics/vram` -> `backend=="cpu"`, `total_mb > 0` (real system RAM via psutil), `len(loaded)==1`, `loaded[0].category=="stt"`, `model_id` contains "small". SC-4 happy path.
- `test_get_vram_empty_when_nothing_loaded` — empty manager state: GET `/diagnostics/vram` -> `loaded==[]` (now via `_loaded_list(empty)` instead of literal `[]`). Regression guard.

Commit `fec16e7`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Split the 3 tests across Task 1 RED and Task 2 (TDD flow)**
- **Found during:** Task 1 TDD execution
- **Issue:** The plan lists all 3 tests under Task 2's `<action>`, but Task 1 is `tdd="true"` and its `<behavior>` describes the psutil-absent test directly. A strict reading ("Task 2 adds all 3 tests in one commit") would skip the Task 1 RED gate, violating the TDD flow the plan frontmatter mandates.
- **Fix:** Added `test_get_vram_loaded_when_psutil_absent` + the inline `no_psutil` / `cpu_manager` fixtures as the Task 1 RED commit (failing against unfixed code), then applied the vram.py fix as GREEN. Task 2 added the remaining 2 tests. Total new tests = 3, matching the plan's expected 188 (185 + 3).
- **Files modified:** tests/test_diagnostics_api.py
- **Commit:** 9f07bc8 (RED), fec16e7 (Task 2 coverage)

**2. [Rule 3 - Blocking] Used a new inline `cpu_manager` fixture instead of `configured_model_manager`**
- **Found during:** Task 1 test design
- **Issue:** The plan acceptance for `test_get_vram_reflects_loaded_model_on_cpu` requires `body.backend=="cpu"` and `body.total_mb > 0` (real system RAM via psutil). But `configured_model_manager` pulls `mock_probe_vram`, which patches `probe_vram` in both `routes_diagnostics` and `manager` to return `backend=GpuBackend.CUDA, total_mb=8192` — that would make `body.backend=="cuda"` (not `"cpu"`) and hide the real CPU fallback the SC-4 fix is about. The plan's own hint ("Use `mock_probe_vram` if needed ... but ensure the CPU branch is the one exercised") is self-contradictory because the mock forces CUDA.
- **Fix:** Defined `cpu_manager` INLINE in `tests/test_diagnostics_api.py` — mirrors `configured_model_manager` (fresh `ModelManager` + `configure_manager` + `configure_manager(None)` teardown) but does NOT pull `mock_probe_vram`, so the real `probe_vram` CPU branch runs with real psutil reads. The manager state is still live (not the empty module-level singleton) because `configure_manager` calls `set_manager_state(mgr._state)`. The plan's "manager state is live" acceptance is satisfied.
- **Files modified:** tests/test_diagnostics_api.py
- **Commit:** 9f07bc8

No other deviations. The vram.py fix is exactly the 2-line change the plan specified; psutil stays a lazy in-body import; conftest.py was NOT modified (02-04 owns it this wave); no new routes, config keys, settings fields, or pyproject dependencies.

## Verification

- [x] `python -c "import psutil; print(psutil.__version__)"` -> `7.2.2` (>= 5.9, after `pip install -e .` user_setup)
- [x] `pytest tests/test_diagnostics_api.py -x -q` -> 7 passed (4 existing + 3 new)
- [x] `pytest -q` -> **188 passed in 120.25s** (185 baseline from 02-04 + 3 new; no regressions)
- [x] `grep -nE "loaded=\[\]" app/models/vram.py` -> 1 hit, in the module docstring (line 14, describing the boot state), 0 hits in the CPU branch
- [x] `grep -nE "loaded=_loaded_list\(manager_state\)" app/models/vram.py` -> 8 hits (DIRECTML/VULKAN 1, CPU import-fail 1, CPU success 1, CPU psutil-call-fail 1, CUDA import-fail 1, CUDA not-available 1, CUDA success 1, CUDA exception 1) — >= 5 required
- [x] `python -c "...cpu branch assert cpu.count('loaded=[]')==0; assert cpu.count('loaded=_loaded_list(manager_state)')>=3..."` -> `ok`
- [x] `python -c "import app.models.vram; print('imports ok')"` -> `imports ok`
- [ ] LIVE manual check (post-execute, not run by the executor): `uvicorn app.main:app`, POST `/models/small.stt/load` -> 200, GET `/diagnostics/vram` -> `loaded:[{category:stt,...}]` with `total_mb > 0`.

## Test results

- 188 passed, 0 failed, 0 skipped (full suite, ~2 min on this machine)
- 3 new tests in `tests/test_diagnostics_api.py`:
  - `test_get_vram_loaded_when_psutil_absent` (SC-4 graceful degradation — the exact UAT failure mode)
  - `test_get_vram_reflects_loaded_model_on_cpu` (SC-4 happy path with real psutil)
  - `test_get_vram_empty_when_nothing_loaded` (regression guard)

## TDD Gate Compliance

- RED gate: `test(02-05): add failing SC-4 psutil-absent graceful-degradation test` (9f07bc8) — verified failing before the fix.
- GREEN gate: `fix(02-05): preserve loaded list in CPU error-fallbacks (SC-4)` (f0b7608) — verified passing after the fix.
- REFACTOR gate: not needed (the fix is a 2-line change; no cleanup warranted).

## Known Stubs

None. The `loaded` list is fully wired from `manager_state.live_vram_bytes` + `loaded_meta` (set by `ModelManager.load` in 02-02); no placeholder/TODO/mock data flows to the `/diagnostics/vram` response in production code paths.

## Threat Flags

None. No new trust boundaries, network endpoints, auth paths, or schema changes. The `pip install -e .` user_setup installs an already-declared dep (`psutil>=5.9`, audited in Phase 2). T-02-17 (DoS via psutil hang/crash) is mitigated by the two `except Exception:` fallbacks that guarantee `probe_vram` never raises and always returns 200 with `loaded` populated — this is exactly the SC-4 graceful-degradation contract the fix restores.

## Commits

- `9f07bc8` — test(02-05): add failing SC-4 psutil-absent graceful-degradation test (RED)
- `f0b7608` — fix(02-05): preserve loaded list in CPU error-fallbacks (SC-4) (GREEN)
- `fec16e7` — test(02-05): add CPU loaded-model + empty-state vram coverage (Task 2)