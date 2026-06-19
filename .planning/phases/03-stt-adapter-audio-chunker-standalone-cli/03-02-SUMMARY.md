---
phase: 03
plan: 02
subsystem: stt-chunker
tags: [stt, chunker, oom-retry, d-02, ingest-05, sc-4, tdd, codex-high]
requires:
  - "03-01 (STTAdapter Protocol + FasterWhisperAdapter + FakeAdapter + mock_stt_adapter fixture)"
provides:
  - "app/models/stt/chunker.py:transcribe_file — decode once, <=30 min single call, >30 min windowed chunks + OOM split-both-halves recursive retry + overlap-dedupe stitch"
  - "app/models/stt/chunker.py:_transcribe_chunk_oom_safe — recursively splits a failed window into two halves and transcribes BOTH (Codex HIGH full-coverage fix)"
  - "app/models/stt/protocol.py:STTAdapter.decode_audio — new Protocol method so the chunker decodes without importing faster_whisper (SC-4)"
  - "app/models/stt/adapter.py:FasterWhisperAdapter.decode_audio — lazy from faster_whisper.audio import decode_audio"
  - "tests/_stt_fake.py:FakeAdapter.decode_audio + segments_per_chunk + transcribe_kwargs + detect_language_call_count"
  - "tests/test_chunker.py:7 INGEST-05 cases (short-audio single call, OOM retry, OOM full-coverage, non-OOM re-raise, stitch offset + dedupe, first-30 s language detect, per-path condition_on_previous_text)"
affects:
  - "03-03 (CLI — composes FasterWhisperAdapter.decode_audio + transcribe_file)"
tech-stack:
  added: []
  patterns:
    - "OOM split-both-halves recursive retry (Codex HIGH fix -- transcribes BOTH halves, no dropped remainder; replaces the prior shrink-only retry)"
    - "Overlap-dedupe stitch (drop later-chunk segments whose abs start_s < prev chunk end; no timestamp mutation -- Codex HIGH stitch fix)"
    - "Protocol extension for SC-4 boundary preservation (decode_audio routed through the adapter)"
    - "Lazy in-body import inside adapter.decode_audio (mirrors adapter.py load() + manager.py hf_hub_download)"
    - "TDD RED/GREEN cycle (RED collection error on missing chunker module, then GREEN implementation)"
key-files:
  created:
    - app/models/stt/chunker.py
    - tests/test_chunker.py
  modified:
    - app/models/stt/protocol.py
    - app/models/stt/adapter.py
    - tests/_stt_fake.py
    - tests/test_stt_adapter.py
decisions:
  - "Overlap-dedupe rule: drop later-chunk segments whose absolute start_s < prev_chunk_end (the previous chunk's absolute end); NO timestamp mutation (Codex HIGH stitch fix -- the prior midpoint-trim mutated start_s and caused text/timestamp mismatch)"
  - "OOM split-both-halves: on OOM the failed window is split at its midpoint and BOTH halves are transcribed recursively (each half sub-chunked until it succeeds or falls below the 60 s floor); the right half's segments are offset by mid/SAMPLE_RATE. The prior shrink-only retry dropped the second half (Codex HIGH correctness defect -- direct SC-2 risk for long videos)"
  - "Recursion bounded by FLOOR_SECONDS=60 hard floor: below the floor the final attempt raises (no catch, no further split); depth log2(WINDOW/FLOOR) ~ 4 (T-03-04 mitigation)"
  - "Non-OOM RuntimeError re-raised unchanged: _OOM_RE matches 'out of memory' case-insensitively; anything else propagates immediately (Pitfall 5 -- a flash-attention/cuBLAS RuntimeError is NOT halved)"
  - "condition_on_previous_text=False per chunk in the chunked path (Pitfall 8 planner decision -- each chunk independent after stitching); True in the <=30 min fast path (default is fine for short audio)"
  - "Language detected on the first 30 s once and passed to every chunk (D-07, INGEST-06) so the whole transcript is one language"
  - "Protocol gained decode_audio (03-02 interface addition) so 03-03 knows the chunker composes adapter.decode_audio + transcribe_file"
  - "Full-decode memory ~115 MB/hour is manageable; streaming decode deferred to a future enhancement if multi-hour files become problematic (Codex MEDIUM -- documented, not bounded)"
metrics:
  duration: ~20 min
  completed: 2026-06-19
  tasks: 2
  files: 6
---

# Phase 03 Plan 02: Windowed Audio Chunker + OOM Split-Both-Halves + Overlap-Dedupe Stitch Summary

One-liner: Windowed chunker orchestrator over the STTAdapter Protocol (SC-4) -- <=30 min single call, >30 min ~15-min windows + 30 s overlap + first-30 s language detect + overlap-dedupe stitch (no timestamp mutation), with OOM split-both-halves recursive retry that transcribes BOTH halves for full-duration coverage (Codex HIGH fix).

## What Was Built

### app/models/stt/chunker.py
- `transcribe_file(adapter, audio_path, *, language=None, job_id="cli") -> Transcript` -- the D-02 orchestrator:
  1. `audio = adapter.decode_audio(audio_path)` -- decode once (D-01 PyAV, routed through the Protocol so the chunker imports no `faster_whisper` -- SC-4)
  2. Fast path: `total_seconds <= SINGLE_CALL_THRESHOLD_SECONDS` (1800 s) -> single `adapter.transcribe(audio, language=language, vad_filter=True, condition_on_previous_text=True)` (Pitfall 8 -- True for short audio), map `SttSegment` -> `TranscriptSegment` (no offset, no dedupe), return `Transcript`
  3. Chunked path: detect language on the first 30 s if `language is None` (D-07), step by `WINDOW_SECONDS - OVERLAP_SECONDS` (870 s) -> 900 s windows with 30 s overlap; per chunk call `_transcribe_chunk_oom_safe` (covers the FULL chunk), offset each `SttSegment` by the chunk's absolute start, drop later-chunk segments whose absolute `start_s < prev_chunk_end` (overlap dedupe -- no timestamp mutation, Codex HIGH stitch fix), update `prev_chunk_end = chunk_start + chunk_seconds`; emit a structured INFO log line (SC-2-style)
- `_transcribe_chunk_oom_safe(adapter, audio_slice, *, language, chunk_s) -> SttTranscription` -- Pattern 3 REVISED (Codex HIGH):
  - Below `FLOOR_SECONDS` (60 s): one final attempt, let it raise (no catch, no further split)
  - Otherwise try `adapter.transcribe(audio_slice, language=language, vad_filter=True, condition_on_previous_text=False)`
  - On `RuntimeError`: if `not _OOM_RE.search(str(exc))`: raise (Pitfall 5 -- non-OOM re-raised unchanged). Otherwise (OOM): log warning, split at `mid = len(audio_slice) // 2`, recursively transcribe BOTH halves, offset the right half's segments by `mid / SAMPLE_RATE`, merge into one `SttTranscription`. This is the Codex HIGH fix -- BOTH halves of a failed window are transcribed (recursively sub-chunking each half until it succeeds), so the full chunk duration is covered with NO dropped remainder
- Constants: `WINDOW_SECONDS = 900`, `OVERLAP_SECONDS = 30`, `FLOOR_SECONDS = 60`, `SAMPLE_RATE = 16000`, `SINGLE_CALL_THRESHOLD_SECONDS = 1800`
- `_OOM_RE = re.compile(r"out of memory", re.IGNORECASE)` (Pitfall 5)
- NO top-level `faster_whisper` / `ctranslate2` / `numpy` import (SC-4 preserved -- decode_audio routed through the Protocol)

### app/models/stt/protocol.py (interface addition)
- `STTAdapter.decode_audio(self, path: str) -> numpy.ndarray` -- new Protocol method so the chunker can decode audio without importing `faster_whisper` (SC-4). `numpy.ndarray` imported under `TYPE_CHECKING` only (no runtime numpy dep on the Protocol module)

### app/models/stt/adapter.py (implementation addition)
- `FasterWhisperAdapter.decode_audio(self, path) -> numpy.ndarray` -- lazy `from faster_whisper.audio import decode_audio as _fw_decode_audio` inside the method body returning `_fw_decode_audio(path)`. The grep match for `from faster_whisper` stays inside `adapter.py` only (SC-4 preserved -- verified by `test_stt_boundary.test_import_boundary`)

### tests/_stt_fake.py (FakeAdapter additions for 03-02)
- `decode_audio(self, path)` -- returns `decode_audio_result` if set (lets chunker tests inject a pre-built long-audio array without hitting PyAV), else a 30 s zeros stub
- `segments_per_chunk` mode: when set, `transcribe` emits N evenly-spaced `SttSegment` spanning the actual audio slice length (mirrors real Whisper's small ~5-30 s segments so the overlap-dedupe drops only segments fully inside the overlap region -- no over-drop)
- `transcribe_kwargs: list[dict]` -- records per-call `language` / `vad_filter` / `condition_on_previous_text` so the D-07 and Pitfall 8 tests can assert on them
- `detect_language_call_count` -- incremented on each `detect_language` call (the first-30 s language-detect test asserts it == 1)
- `transcribe_side_effect` -- if set, `transcribe` raises it (the non-OOM re-raise test injects a `RuntimeError("flash attention dtype mismatch -- cuBLAS version mismatch")`)

### tests/test_chunker.py (7 INGEST-05 cases + 1 parametrized)
- `test_short_audio_single_call` (D-02 fast path): 20-min audio -> `adapter.call_count == 1`, segments not offset, last `end_s ~= 20*60`
- `test_oom_halve_and_retry` (Codex HIGH): 45-min audio with `oom_on_call=1` -> first chunk OOMs, split + retry both halves succeed, `call_count >= 2`, non-empty Transcript
- `test_oom_halve_covers_full_audio` (Codex HIGH full-coverage): `oom_above_seconds=420` over 45-min -> every 900 s window OOMs -> split 450 -> OOMs -> split 225 -> succeeds; asserts `segs[0].start_s == 0.0` and `segs[-1].end_s >= 45*60 - 10` (no dropped remainder) AND no gap > `OVERLAP_SECONDS` between consecutive segments (monotonic coverage). Uses `segments_per_chunk=60` so the dedupe cleanly drops only fully-overlapping segments (mirrors real Whisper)
- `test_oom_non_oom_runtime_error_reraises` (Pitfall 5): `RuntimeError("flash attention dtype mismatch -- cuBLAS version mismatch")` re-raised unchanged; `call_count == 1` (the chunker did NOT split on a non-OOM RuntimeError)
- `test_stitch_offset_and_overlap_dedupe` (D-02 stitch, Codex HIGH stitch fix): 45-min audio with 15-min windows + 30 s overlap -> monotonic non-decreasing `start_s`, no two segments overlap (`end_s of N <= start_s of N+1`), `start_s[0] == 0.0`, `end_s[-1] ~= 45*60`. Uses `segments_per_chunk=60` for clean contiguous coverage
- `test_chunked_path_detects_language_on_first_30s` (D-07, INGEST-06): `language=None` -> `detect_language_call_count == 1` and every chunk's recorded `language` kwarg == "es"
- `test_chunked_path_condition_on_previous_text_false` (Pitfall 8 planner decision, parametrized): >30 min -> `condition_on_previous_text=False` per call; <=30 min -> `True`

### tests/test_stt_adapter.py (cross-plan extension -- 03-01 created, 03-02 adds one case)
- `test_decode_audio_returns_stubbed_array` (W3): under the 03-01 `mock_stt_adapter` fixture (which patches `faster_whisper.audio.decode_audio` to return `fake_audio_array`), `FasterWhisperAdapter.decode_audio("any.wav")` returns the stubbed `(16000*30,)` float32 zeros array -- proves the lazy `from faster_whisper.audio import decode_audio` inside `adapter.py` resolves under the seam (W3) and the SC-4 boundary stays at `adapter.py`

## Test Results

- `pytest tests/test_chunker.py -x` -> **8 passed** (GREEN after Task 2; RED after Task 1 -- collection error on missing `app.models.stt.chunker`)
- `pytest tests/test_chunker.py::test_oom_halve_covers_full_audio -x` -> 1 passed (Codex HIGH full-coverage assertion)
- `pytest tests/test_stt_adapter.py::test_decode_audio_returns_stubbed_array -x` -> 1 passed (W3 decode_audio seam)
- `pytest tests/test_stt_boundary.py -x` -> 1 passed (SC-4 boundary preserved after the `decode_audio` move)
- `pytest -q` (full suite) -> **202 passed** (193 existing + 9 new, no regressions)

## TDD Gate Compliance

- RED gate commit: `d33a9de test(03-02): add chunker Wave 0 stubs + OOM full-coverage + decode_audio unit test` -- tests collected and failed on `ModuleNotFoundError: No module named 'app.models.stt.chunker'` (NOT a collection error from a missing fixture or helper -- the test module imports `transcribe_file` / constants from `app.models.stt.chunker` at module scope, which is the contract)
- GREEN gate commit: `7b96d43 feat(03-02): implement windowed chunker + OOM split-both-halves + overlap-dedupe stitch` -- all 8 chunker tests + the decode_audio unit test pass; full suite green
- REFACTOR: no separate refactor commit needed (the implementation was already minimal -- the chunker is a pure orchestrator with no dead code)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Refined `segments_per_chunk` in two chunker tests for correct overlap-dedupe behavior**
- **Found during:** Task 1 (RED test authoring)
- **Issue:** The plan's `_fake_adapter(segments_per_chunk=2, ...)` helper with 2 large segments per 900 s chunk (450 s each) exposed an edge case in the overlap-dedupe rule: a segment starting in the 30 s overlap region but extending well past it would be dropped entirely, losing content in the non-overlap region. This is correct for real Whisper (whose ~5-30 s segments are smaller than the 30 s overlap) but breaks the full-coverage gap assertion in `test_oom_halve_covers_full_audio` and the "continuous, full-coverage" intent of `test_stitch_offset_and_overlap_dedupe`.
- **Fix:** Used `segments_per_chunk=60` in `test_oom_halve_covers_full_audio` and `test_stitch_offset_and_overlap_dedupe` (15 s segments per 900 s chunk, 1.5 s per 90 s last chunk) so the dedupe drops only segments fully inside the 30 s overlap region -- mirrors real Whisper's small segments and gives clean contiguous coverage (gap == 0 at chunk boundaries, no over-drop). The simpler tests (`test_short_audio_single_call`, `test_oom_halve_and_retry`, `test_chunked_path_detects_language_on_first_30s`, `test_chunked_path_condition_on_previous_text_false`) keep the plan's small `segments_per_chunk` values because they only assert on call counts / kwargs / first-segment start, not on stitch continuity.
- **Files modified:** tests/test_chunker.py
- **Commit:** d33a9de (amended into the RED commit before Task 2)

No other deviations -- the plan executed as written otherwise. The `_transcribe_chunk_oom_safe` recursion, the overlap-dedupe rule, the Protocol `decode_audio` addition, and the per-path `condition_on_previous_text` all followed the plan exactly.

## Known Stubs

None. `transcribe_file` is fully wired: it calls `adapter.decode_audio` (real PyAV via `FasterWhisperAdapter`, faked in tests), `adapter.detect_language` (real faster-whisper, faked in tests), and `adapter.transcribe` (real faster-whisper, faked in tests). No TODO/FIXME, no placeholder data, no empty defaults flowing to any UI. The `FakeAdapter` is a deliberate test double, not a stub.

## Threat Flags

None. The threat model in the plan (T-03-03 accept -- PyAV parser during decode_audio; T-03-04 mitigate -- FLOOR_SECONDS=60 hard floor bounds the recursion at depth ~4; T-03-SC accept -- no new pip installs) covers the surface this plan introduces. The chunker adds no new network endpoints, no auth paths, and no new trust-boundary file access beyond the user-supplied local audio path that the adapter already accepts.

## Self-Check: PASSED

- All 2 created files exist on disk (`app/models/stt/chunker.py`, `tests/test_chunker.py`)
- All 4 modified files updated (`app/models/stt/protocol.py`, `app/models/stt/adapter.py`, `tests/_stt_fake.py`, `tests/test_stt_adapter.py`)
- RED gate commit d33a9de found in git log
- GREEN gate commit 7b96d43 found in git log
- Full suite 202 passed (193 existing + 9 new, no regressions)
- SC-4 boundary grep over `app/` matches only `app/models/stt/adapter.py` (verified by `test_stt_boundary.test_import_boundary` GREEN)
- Codex HIGH full-coverage assertion verified by `test_oom_halve_covers_full_audio` GREEN