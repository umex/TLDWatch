---
status: testing
phase: 02-gpu-backend-detection-model-manager
source:
  - 02-01-SUMMARY.md
  - 02-02-SUMMARY.md
  - 02-03-SUMMARY.md
started: 2026-06-18T22:55:27.046Z
updated: 2026-06-19T00:53:58.510Z
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
<!-- OVERWRITE each test - shows where we are -->

[session paused — resuming user wishes to resolve the ROCm-on-Windows GPU path before continuing; see Notes]

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
result: [pending]

### 3. SC-2 — Default model set fits 8 GB VRAM; per-model budget logged (HW-04, HW-07)
expected: The BALANCED preset (faster-whisper-large-v3 + pyannote/speaker-diarization-3.1 + Qwen2.5-7B-Instruct Q4_K_M) is the default. Loading a model emits a structured JSON INFO log line with expected_vram_mb / measured_vram_mb_after_load / total_vram_mb / available_vram_mb_after_load. The per-category overhead multipliers (LLM=1.2, STT=1.5, DIARIZE=1.2) keep the 7B (~5.15 GB in-VRAM) within the 8 GB laptop budget (0.85 * 8192 = 6963 MB). STT/diarize specs now carry `expected_size_bytes` so the budget gate is not bypassed (WR-04 fix — flagged human-verify).
result: [pending]

### 4. SC-3 — Download, size+SHA verify, download log, resume after crash (HW-09)
expected: `POST /models/{id}/download` returns 202 and starts a background task; `GET /models/{id}/download-progress` streams `event: progress` SSE lines with a `: ping` heartbeat. `ensure_downloaded` does a size fast-path, SHA256 verify when `expected_sha256` is set (bounded 1-retry → ModelIntegrityError on mismatch), maps GatedRepoError→403, and resumes after crash (force_download NOT passed — the library resumes via `.incomplete` + Range). Duplicate in-flight downloads are refused with 409 (WR-01 fix) and byte-level progress is reported to the SSE stream (WR-02 fix — flagged human-verify).
result: [pending]

### 5. SC-4 — Load blocks past 85% VRAM; explicit idle unload; "what's in VRAM" indicator (HW-07)
expected: `POST /models/{id}/load` on a tight budget returns 507 with `error="vram_budget_exceeded"`; on a generous budget returns 200 with a `LoadedModel` body. `POST /models/{id}/unload` returns 204 and is idempotent (explicit-only, no idle timer — D-03). `GET /diagnostics/vram` reflects the currently-loaded model(s) via the two-pool probe (torch allocated + live_vram_bytes); the CPU branch reports `loaded` from manager_state (WR-03 fix).
result: [pending]

### 6. SC-5 — No two models concurrent unless opted in via hidden toggle (HW-09)
expected: With default `concurrent_models=False`, loading a second model while one is already resident returns 409 `concurrent_model_refused` (D-04 — caller must explicitly unload first; no auto-swap). With `concurrent_models=True` (set via `PATCH /settings`), both models load 200. The toggle defaults to False and is not surfaced in the default UI flow. A non-restart PATCH (e.g. quality_preset) preserves a queued restart-required `data_dir` change rather than dropping it (WR-05 fix — flagged human-verify).
result: [pending]

## Summary

total: 6
passed: 1
issues: 0
pending: 5
skipped: 0

## Gaps

[none yet]

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