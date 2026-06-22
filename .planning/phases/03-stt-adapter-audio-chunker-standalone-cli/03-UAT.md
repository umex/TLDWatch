---
status: complete
phase: 03-stt-adapter-audio-chunker-standalone-cli
source: [03-VERIFICATION.md]
started: 2026-06-19T13:40:45Z
updated: 2026-06-22T17:41:16Z
---

## Current Test

[testing complete]

## Tests

### 1. SC-5 laptop CUDA half + Open Q1 (CUDA runtime libs findable by CTranslate2)

expected: |
  CLI runs end-to-end on the CUDA laptop with default compute_type=int8_float16; `out.json` has
  non-empty segments + detected language; same command as the desktop CPU half (no code changes).
  Closes SC-5 laptop CUDA half + Open Q1. If `nvidia-*-cu12` were required, record as a mandatory
  follow-up to add to `pyproject.toml`.
result: pass
evidence: |
  Human-verified on the physical CUDA laptop (2026-06-22):

  1. `python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda',0))"`
     returned `{'int8_float16', 'bfloat16', 'int8_float32', 'float32', 'float16', 'int8_bfloat16',
     'int8'}` — includes BOTH `int8` and `int8_float16` (NOT only `float32`). CUDA runtime libs
     (`cublas64_12.dll` / `cudart12.dll`) are findable by CTranslate2 with no extra install.

  2. `transcribe <small-file> --out out.json` ran end-to-end on the laptop with no `--device` flag
     (same command as the desktop CPU half — no code changes).

  Open Q1 RESOLVED: `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` pip packages were NOT
  required. No `pyproject.toml` change needed; the deferred dependency question is closed
  (no-install outcome recorded per 03-03-SUMMARY Open Q1).

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]