---
status: testing
phase: 03-stt-adapter-audio-chunker-standalone-cli
source: [03-VERIFICATION.md]
started: 2026-06-19T13:40:45Z
updated: 2026-06-19T13:40:45Z
---

## Current Test

number: 1
name: SC-5 laptop CUDA half — CLI runs end-to-end on the CUDA laptop (int8_float16 verified; closes Open Q1)
expected: |
  On the physical CUDA laptop (not the CPU desktop — that half is already verified):

  1. `python -c "import ctranslate2; print(sorted(ctranslate2.get_supported_compute_types('cuda',0)))"`
     - PASS if the list includes `int8` and/or `int8_float16` (NOT only `float32`) — the CUDA
       runtime libs (`cublas64_12.dll` / `cudart12.dll`) are findable by CTranslate2.
     - If only `float32`, OR `RuntimeError: Library cublas64_12.dll is not found`:
       `pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12`, then re-run the command.
       If `int8`/`int8_float16` now appear -> continue. If they still do not appear -> STOP and
       report (a system CUDA 12.x toolkit is required; this is a known blocker, not a code bug).

  2. `transcribe <small-audio-file> --out out.json`  (any short 1-3 min local MP4/WAV; default preset)
     - PASS if exit 0, stdout `language=<code> segments=<N> -> out.json`, and `out.json` is valid
       Transcript JSON (`schema_version=1`, `job_id`, `language`, non-empty `segments`).
     - Default `compute_type` on CUDA is `int8_float16` (confirm via `--verbose` adapter INFO log).
     - Same command as the desktop (no `--device` flag) — proves the SC-5 "same command on both
       machines, no code changes" seam.

  Follow-up to record (do NOT implement without confirmation): whether
  `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` pip packages were required. If so, they must
  be added to `pyproject.toml` as a mandatory follow-up.
awaiting: user response

## Tests

### 1. SC-5 laptop CUDA half + Open Q1 (CUDA runtime libs findable by CTranslate2)

expected: |
  CLI runs end-to-end on the CUDA laptop with default compute_type=int8_float16; `out.json` has
  non-empty segments + detected language; same command as the desktop CPU half (no code changes).
  Closes SC-5 laptop CUDA half + Open Q1. If `nvidia-*-cu12` were required, record as a mandatory
  follow-up to add to `pyproject.toml`.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps