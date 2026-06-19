---
phase: 03
plan: 01
subsystem: stt-adapter
tags: [stt, adapter, faster-whisper, d-06, d-08, sc-4, tdd]
requires:
  - "02-02 (model manager — resolves model_path; adapter receives it)"
  - "02-01 (backend.device_for — resolves device arg; adapter receives it)"
provides:
  - "app/models/stt/protocol.py:STTAdapter Protocol + SttSegment + SttTranscription"
  - "app/models/stt/adapter.py:FasterWhisperAdapter (the ONLY faster_whisper/ctranslate2 import site)"
  - "tests/_stt_fake.py:FakeAdapter (with oom_on_call + oom_above_seconds for chunker tests)"
  - "tests/conftest.py:mock_stt_adapter + fake_audio_array + mock_ct2_supported_compute_types fixtures"
affects:
  - "03-02 (chunker — extends STTAdapter Protocol with decode_audio; reuses mock_stt_adapter)"
  - "03-03 (CLI — composes FasterWhisperAdapter + chunker)"
tech-stack:
  added:
    - "faster-whisper==1.2.1"
    - "ctranslate2==4.7.2"
  patterns:
    - "Protocol seam (D-06, mirrors BackendProvider)"
    - "Lazy in-body import (mirrors manager.py hf_hub_download)"
    - "D-08 _ACCEPTED equivalence table (dual-purpose: accepts CUDA int8->int8_float16, rejects float32 fallback)"
    - "TDD RED/GREEN cycle (interface + failing tests first, then implementation)"
key-files:
  created:
    - app/models/stt/__init__.py
    - app/models/stt/protocol.py
    - app/models/stt/adapter.py
    - tests/_stt_fake.py
    - tests/test_stt_adapter.py
    - tests/test_stt_boundary.py
  modified:
    - tests/conftest.py
    - pyproject.toml
decisions:
  - "SttSegment deliberately mirrors TranscriptSegment field shape but is a SEPARATE type (D-06 layering — keeps STT contract decoupled from storage schema; chunker does the single SttSegment->TranscriptSegment conversion)"
  - "protocol.py forward-discloses 03-02's decode_audio extension (Codex LOW on Wave-1 interface modified in Wave 2)"
  - "[project.scripts] transcribe entry deferred to 03-03 (Codex HIGH — declaring it before app.cli.transcribe exists breaks editable installs / smoke tests)"
  - "nvidia-cublas-cu12 / nvidia-cuda-runtime-cu12 NOT pinned here (deferred to SC-5 checkpoint in 03-03)"
  - "confidence = exp(avg_logprob) documented as a PROXY, not a calibrated probability (Codex LOW)"
  - "mock_stt_adapter also patches ctranslate2.get_supported_compute_types (real call raised CUDA-driver-version RuntimeError on this machine)"
metrics:
  duration: ~6 min
  completed: 2026-06-19
  tasks: 2
  files: 8
---

# Phase 03 Plan 01: STTAdapter Protocol + FasterWhisperAdapter Summary

One-liner: STTAdapter Protocol seam (D-06) + FasterWhisperAdapter as the single faster_whisper/ctranslate2 import site with D-08 int8 fail-loud verification (accepts CUDA int8->int8_float16, rejects silent float32 fallback).

## What Was Built

### app/models/stt/protocol.py
- `class STTAdapter(Protocol)` — `load()`, `transcribe(audio, language=None, vad_filter=True, condition_on_previous_text=True) -> SttTranscription`, `detect_language(audio) -> tuple[str, float]`, `unload()`
- `@dataclass class SttSegment` — `start_s`, `end_s`, `text`, `confidence: float | None` (STT-layer contract; mirrors TranscriptSegment shape but is a separate type per D-06 layering)
- `@dataclass class SttTranscription` — `segments: list[SttSegment]`, `language: str`, `language_probability: float`, `duration: float`
- Module docstring forward-discloses 03-02's `decode_audio` Protocol extension (Codex LOW)
- NO faster_whisper / ctranslate2 import (verified by SC-4 boundary test)

### app/models/stt/adapter.py
- `class FasterWhisperAdapter` — `__init__(model_path, device, compute_type)` (pure transform, receives resolved values, does NOT call `current()` / `device_for`), `load()`, `transcribe(...)`, `detect_language(...)`, `unload()`
- `class SttInt8VerificationError(RuntimeError)` — typed error for the fail-loud path
- `_ACCEPTED: dict[str, set[str]]` — D-08 equivalence table: `int8 -> {int8, int8_float16, int8_float32}`, `int8_float16 -> {int8_float16}`, `int8_float32 -> {int8_float32}`, `float16 -> {float16, int8_float16}`
- D-08 int8 verification: after load reads `self._model.model.compute_type`, raises `RuntimeError("int8 verification failed: ...")` on silent fallback; emits structured INFO log line (requested vs loaded)
- transcribe: materializes lazy generator (`list(segments_iter)` — Pitfall 7), maps `Segment{start,end,text,avg_logprob}` -> `SttSegment` with `confidence = math.exp(avg_logprob)` (PROXY, documented)
- detect_language: drops the `all_lang_probs` third element per Protocol
- unload: idempotent `_model = None` (D-03); VRAM-retention `gc.collect()` + `torch.cuda.empty_cache()` deferred until observed (Codex LOW)
- SC-4 boundary statement in module docstring (mirrors manager.py lines 37-39)
- lazy in-body imports (`from faster_whisper import WhisperModel` + `import ctranslate2` inside `load()`, mirroring manager.py lines 311-315)

### app/models/stt/__init__.py
- Re-exports `STTAdapter`, `SttSegment`, `SttTranscription` (eager from protocol.py)
- Re-exports `FasterWhisperAdapter` lazily via `__getattr__` (so package top imports cleanly during RED and does not eagerly load the concrete impl)

### tests/_stt_fake.py
- `class FakeAdapter` — `__init__(segments, language, language_probability, duration, oom_on_call, oom_above_seconds)`, `load`, `transcribe`, `detect_language`, `unload`, `call_count`, `transcribe_calls`
- Two OOM modes for 03-02's full-coverage chunker test: `oom_on_call` (Nth transcribe OOMs) + `oom_above_seconds` (audio longer than threshold OOMs — recursive halving succeeds on sub-threshold pieces)
- Raises `RuntimeError("CUDA failed with error out of memory")` matching the real faster-whisper OOM substring (Pitfall 5)

### tests/conftest.py additions
- `mock_stt_adapter` fixture — patches `faster_whisper.WhisperModel` (mock class with `.model.compute_type` knob, `transcribe` returning `(iter([Segment]), info)`, `detect_language` returning `(lang, prob, {})`), `faster_whisper.audio.decode_audio` (returns 30 s silence array — consumed by 03-02's decode_audio unit test), AND `ctranslate2.get_supported_compute_types` (returns per-device accepted sets — see Deviations)
- `fake_audio_array` fixture — `numpy.zeros(16000 * 30, dtype="float32")` (30 s silence at 16 kHz)
- `mock_ct2_supported_compute_types` helper — standalone patcher for ct2 supported types (mirrors the Phase 2 `mock_hf_hub_download` real-module-import pattern)

### tests/test_stt_adapter.py
- `test_segment_mapping` (TRANS-01) — `Segment{start=1.0,end=3.0,text="hi",avg_logprob=-0.1}` -> `SttSegment{start_s=1.0, end_s=3.0, text="hi", confidence=exp(-0.1)}`
- `test_language_autodetect_recorded` (INGEST-06) — `language=None` records `language="en"`, `language_probability=0.99`
- `test_int8_verification_fails_loud` (D-08 negative) — mock compute_type="float32" while requested="int8_float16" -> `RuntimeError` matching `"int8 verification failed"`
- `test_int8_equivalence_accepted` (D-08 positive) — mock compute_type="int8_float16" while requested="int8" -> `load()` returns normally (no false positive); also requested="int8_float16" + actual="int8_float16" accepted

### tests/test_stt_boundary.py
- `test_import_boundary` (SC-4) — regex `^\s*(from faster_whisper|import faster_whisper|import ctranslate2)` over `app/` yields exactly `["app/models/stt/adapter.py"]`

### pyproject.toml
- Added Phase 3 comment block + `faster-whisper==1.2.1` + `ctranslate2==4.7.2` (D-08 verified-compatible pair) to dependencies
- NO `[project.scripts]` `transcribe` entry (deferred to 03-03 per Codex HIGH)
- NO `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` (deferred to SC-5 checkpoint in 03-03)

## Test Results

- `pytest tests/test_stt_adapter.py tests/test_stt_boundary.py -x` -> 5 passed (GREEN after Task 2; RED after Task 1 as expected)
- `pytest -q` (full suite) -> **193 passed** (188 existing + 5 new, no regressions)

## TDD Gate Compliance

- RED gate commit: `b8b877a test(03-01): add STTAdapter Protocol + Wave 0 stubs + pyproject pins` — tests collected and failed on missing adapter implementation (NOT a collection error from missing fixtures)
- GREEN gate commit: `9af28e9 feat(03-01): implement FasterWhisperAdapter + D-08 int8 verification` — all 5 tests pass
- REFACTOR: no separate refactor commit needed (implementation was already minimal)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Patched ctranslate2.get_supported_compute_types in mock_stt_adapter**
- **Found during:** Task 2 verification (running the GREEN tests)
- **Issue:** The real `ctranslate2.get_supported_compute_types("cuda", 0)` raises `RuntimeError: CUDA driver version is insufficient for CUDA runtime version` on this machine (no matching CUDA runtime). `FasterWhisperAdapter.load()` calls it before the mock `WhisperModel` is constructed, so the 4 adapter tests could not reach the int8 verification path the plan requires them to exercise — a blocking issue preventing task completion.
- **Fix:** Folded a `monkeypatch.setattr(ctranslate2, "get_supported_compute_types", ...)` into the `mock_stt_adapter` fixture (returns `{"int8","int8_float16","float16"}` for cuda, `{"int8","int8_float32","float32"}` for cpu). This is consistent with the plan's `mock_ct2_supported_compute_types` helper (which remains exposed standalone) and with the `mock_hf_hub_download` real-module-import pattern. The adapter's `load()` now sees the patched table and proceeds to construct the mock `WhisperModel`, so the D-08 int8 verification path is actually exercised by the tests.
- **Files modified:** tests/conftest.py
- **Commit:** 9af28e9

No other deviations — the plan executed as written otherwise.

## Known Stubs

None. `FasterWhisperAdapter` is fully wired (no placeholder data, no TODO/FIXME, no empty defaults flowing to any UI). The `decode_audio` seam is forward-disclosed in protocol.py's docstring (03-02 adds it to the Protocol) and pre-patched in `mock_stt_adapter` for 03-02's unit test — that is intentional cross-plan fixture ownership, not a stub.

## Threat Flags

None. The threat model in the plan (T-03-01, T-03-02, T-03-SC) is accepted/mitigated as documented; no new security-relevant surface was introduced beyond what the plan declared (the adapter receives already-resolved values; no untrusted path handling in this plan; the verified faster-whisper==1.2.1 + ctranslate2==4.7.2 pair was flagged OK in RESEARCH Package Legitimacy Audit).

## Self-Check: PASSED

- All 6 created files exist on disk (app/models/stt/{__init__,protocol,adapter}.py, tests/{_stt_fake,test_stt_adapter,test_stt_boundary}.py)
- RED gate commit b8b877a found in git log
- GREEN gate commit 9af28e9 found in git log
- Full suite 193 passed (188 existing + 5 new, no regressions)
- SC-4 boundary grep over app/ matches only app/models/stt/adapter.py