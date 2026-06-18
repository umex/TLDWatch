---
phase: 02-gpu-backend-detection-model-manager
plan: 03
subsystem: infra
tags: [rocm, gfx1030, rdna2, spike, therock, gpu-detection, cpu-fallback]

requires:
  - phase: 02-gpu-backend-detection-model-manager/02-01
    provides: "GpuBackend enum + async detect()/burn_test() targeting the ROCm/CUDA/CPU paths the spike validates"
provides:
  - "Empirical spike verdict for the desktop box: ROCM_FALLBACK_TO_CPU (install command stale, not a hardware limit)"
  - "02-03-SPIKE.md — five-section living doc with verbatim terminal output + Phase 3 must-do list"
  - "Contract guard test (4 assertions) enforcing the spike file's shape before Phase 3 can be planned"
affects: [03-transcript-pipeline, 07-llm-adapter, 08-inference-tuning, phase-3-stt-adapter]

tech-stack:
  added: []
  patterns: ["spike-as-living-doc: empirical hardware verdict recorded per D-07; code ships against the fallback chain regardless of verdict"]

key-files:
  created:
    - ".planning/phases/02-gpu-backend-detection-model-manager/02-03-SPIKE.md"
    - "tests/test_spike_documented.py"
  modified: []

key-decisions:
  - "Verdict ROCM_FALLBACK_TO_CPU: the documented TheRock pin torch==2.10.0+rocm7.12 does not exist in the v2-staging index (only dated alphas); the existing torch is the CPU build; the GPU kernel failed"
  - "Root cause is a stale install command + wrong Python (global 3.12 vs locked 3.11), NOT a hardware limitation — the RX 6800 + Adrenalin driver 32.0.21043.12001 are confirmed present"
  - "RX 6800 is RDNA2/non-CUDA-capable: the only GPU paths are ROCm (TheRock, device='cuda' via HIP compat), DirectML, or Vulkan — never stock +cu* builds"
  - "Re-spike with the corrected dated-alpha pin in the locked Python 3.11 venv is a Phase 3 must before hardening on CPU"

patterns-established:
  - "Spike contract guard: a test that asserts a planning doc exists with required structure, so the spike deliverable cannot silently disappear before downstream phases consume it"

requirements-completed: [HW-03]

duration: ~15min
completed: 2026-06-18
---

# Phase 02-03: ROCm-on-Windows Spike Summary

**Empirical desktop spike verdict `ROCM_FALLBACK_TO_CPU` — RX 6800 + driver are present, but the documented TheRock wheel pin was stale (only dated alphas exist in the index) and the box ran the wrong Python, so the install failed; CPU fallback chain (already in 02-01/02-02) handles it safely per D-07.**

## Performance

- **Duration:** ~15 min (user-side spike run + agent continuation)
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- Captured verbatim terminal evidence from the AMD desktop: Win10 Pro build 19045, RX 6800 (DEV_73BF/Navi 21/RDNA2) with Adrenalin driver 32.0.21043.12001, CPU torch 2.12.0 on Python 3.12, ctranslate2 4.7.2.
- Recorded the verdict `ROCM_FALLBACK_TO_CPU` with the five required sections and a six-item Phase 3 must-do list (including the RDNA2/non-CUDA constraint and the corrected re-spike plan).
- Added a 4-assertion contract guard (`tests/test_spike_documented.py`) that fails loudly if the spike file is missing, malformed, or lacks a valid verdict — so Phase 3 cannot be planned against a vanished spike.

## Task Commits

Each task was committed atomically:

1. **Task 1: Run the ROCm spike on the desktop and write 02-03-SPIKE.md** - `d760b92` (docs) — human-action checkpoint; the user ran the spike, the agent drafted the SPIKE.md from verbatim output and committed after sign-off.
2. **Task 2: Write the contract-guard test for the spike deliverable** - `212a1ab` (test) — 4 assertions, green on first run.

## Files Created/Modified
- `.planning/phases/02-gpu-backend-detection-model-manager/02-03-SPIKE.md` - Five-section spike deliverable with verbatim terminal output, the ROCM_FALLBACK_TO_CPU verdict, pitfalls, and the Phase 3 must-do list.
- `tests/test_spike_documented.py` - Contract guard: asserts the spike file exists, has the five required sections in order, has exactly one of the two valid verdict strings, and the §5 section contains a "must" requirement.

## Decisions Made
- **Verdict = ROCM_FALLBACK_TO_CPU.** The spike-as-run failed: the documented `torch==2.10.0+rocm7.12` pin does not exist in the TheRock `v2-staging/gfx103X-dgpu/` index (only dated alphas like `2.11.0+rocm7.13.0a20260421`), the existing torch is the CPU build (`Torch not compiled with CUDA enabled`), and `lemon-clip` is not installed.
- **Not a hardware verdict.** `Get-CimInstance Win32_VideoController` confirms the RX 6800 + Adrenalin driver are present. The blockers are the stale command and the wrong Python (global 3.12 vs locked 3.11), both fixable — so a re-spike is high-value.
- **RDNA2 is non-CUDA.** Explicitly recorded that stock `+cu*` torch builds and NVIDIA-only tooling will not use this GPU; the only GPU paths are ROCm (TheRock; its `device='cuda'` string is HIP's CUDA-compat layer, not NVIDIA CUDA), DirectML, or Vulkan.
- **pnputil false negative.** `pnputil | findstr amdkmdap` returned empty but the driver IS present — the identifier pattern is wrong for this Win10 build; use `Win32_VideoController` instead.

## Deviations from Plan

### Auto-fixed Issues

**1. (Plan correction) Stale TheRock wheel pin**
- **Found during:** Task 1 (user spike run)
- **Issue:** The plan's `<action>` pinned `torch==2.10.0+rocm7.12`, which does not exist in the index (only dated alphas do).
- **Fix:** Recorded the actual available versions in §4 Pitfall 1 and §5 #3 (resolve the wheel dynamically; do not hardcode a pin) + §5 #5 (schedule a re-spike with the corrected dated-alpha pin).
- **Verification:** The pip "from versions:" list in the user's terminal output.
- **Committed in:** `d760b92`

**2. (Hardware correction) pnputil returned a false negative for the AMD driver**
- **Found during:** Task 1 (user spike run)
- **Issue:** `pnputil /enum-drivers | findstr amdkmdap` returned empty, which initially read as "no AMD driver."
- **Fix:** The user ran `Get-CimInstance Win32_VideoController`, which confirmed the driver IS present (32.0.21043.12001). Recorded in §1 and §4 Pitfall 3; switched the recommended confirmation command to `Win32_VideoController`.
- **Verification:** The WMI output table in §1.
- **Committed in:** `d760b92`

**3. (Constraint clarification) RDNA2 is not CUDA-capable**
- **Found during:** Task 1 (user feedback on the draft)
- **Issue:** The draft risked Phase 3 reaching for a stock CUDA build, which the RX 6800 cannot use.
- **Fix:** Added an explicit RDNA2/non-CUDA statement to the verdict intro and §4 Pitfall 5, and a "must" item in §5 (#6) rejecting any GPU path other than ROCm/DirectML/Vulkan up front.
- **Verification:** Cross-checked against the WMI device ID (VEN_1002/DEV_73BF = Navi 21/RDNA2).
- **Committed in:** `d760b92`

**Total deviations:** 3 auto-fixed (all plan/hardware corrections surfaced by the empirical spike run, not scope creep).
**Impact on plan:** All corrections strengthen the spike's accuracy for Phase 3. No scope change.

## Issues Encountered
- The spike is a `checkpoint:human-action` plan — the agent has no access to the user's AMD desktop, so it returned a structured checkpoint; the user ran the commands and pasted verbatim output, the agent drafted the SPIKE.md, and the user signed off before commit. Resolved via the standard checkpoint flow.

## User Setup Required
None for code. The spike itself was the user-setup task (running the TheRock install attempt on the physical desktop). A future re-spike (§5 #5) will require the user to run the corrected dated-alpha install in the locked Python 3.11 venv.

## Next Phase Readiness
- Phase 2 is now fully executable-complete: 02-01 (detect + settings), 02-02 (model manager), 02-03 (spike verdict) all shipped; **155 tests green**.
- Phase 3 (transcript pipeline) can be planned with the `ROCM_FALLBACK_TO_CPU` verdict in hand — STT adapter defaults to `device='cpu'`, stays pluggable for a future ROCm flip, and must reject stock-CUDA paths on this RDNA2 box.
- Open follow-up: schedule the re-spike (corrected pin + Python 3.11 venv) before Phase 3 hardens on CPU; the current verdict reflects a stale command, not a hardware limit.

---
*Phase: 02-gpu-backend-detection-model-manager*
*Completed: 2026-06-18*