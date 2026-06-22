---
phase: 03-stt-adapter-audio-chunker-standalone-cli
verified: 2026-06-22T17:41:16Z
status: passed
score: 11/11 must-haves verified · SC-5 laptop CUDA half closed by human UAT 2026-06-22
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 10/11 must-haves verified
  gaps_closed: ["SC-5 laptop CUDA half + Open Q1 (CUDA runtime libs)"]
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "On the CUDA laptop, run `ctranslate2.get_supported_compute_types('cuda',0)` and confirm `int8`/`int8_float16` are present (not only `float32`). Then run `transcribe <small-file> --out out.json` and confirm it exits 0 with a valid transcript.json (default compute_type=int8_float16)."
    expected: "CLI runs end-to-end on CUDA; out.json has non-empty segments + detected language; same command as the desktop (no --device flag). If `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12` pip packages were required, record them as a mandatory follow-up to add to pyproject.toml."
    why_human: "Requires the physical CUDA laptop hardware and a real model download; cannot be exercised from the verifier process. Closes SC-5 laptop CUDA half + Open Q1 (CUDA runtime libs)."
    status: passed
    verified_at: 2026-06-22T17:41:16Z
    evidence: "`get_supported_compute_types('cuda',0)` returned {'int8_float16','bfloat16','int8_float32','float32','float16','int8_bfloat16','int8'} — int8 + int8_float16 present; `transcribe <file>` ran end-to-end on CUDA with no --device flag. nvidia-cublas-cu12 / nvidia-cuda-runtime-cu12 NOT required (Open Q1 closed, no pyproject change)."
---

# Phase 03: STT Adapter + Audio Chunker + Standalone CLI Verification Report

**Phase Goal:** A runnable STT pipeline that takes an audio file, transcribes it with faster-whisper, handles long audio via chunking with OOM fallback, and proves the GPU abstraction works on both machines.
**Verified:** 2026-06-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Roadmap Success Criteria are the contract; PLAN must_haves are merged in.

| #   | Truth (SC / must_have) | Status | Evidence |
| --- | --------------------- | ------ | -------- |
| 1 | SC-1: Standalone CLI takes a local file path and writes transcript.json with timestamped segments + detected language | VERIFIED | `app/cli/transcribe.py` main() builds argparse, calls `transcribe_file` + `asyncio.run(atomic_write_json(out_path, transcript.model_dump()))`; entry point `transcribe = "app.cli.transcribe:main"` declared in `pyproject.toml` lines 42-43; `transcribe --help` resolves and prints the help. 03-03 SUMMARY records a real end-to-end run on the CPU desktop: `language=en segments=20 -> out.json`. |
| 2 | SC-2: Long audio (>30 min) is split into chunks with overlap, transcribed, and stitched; if a chunk OOMs, the chunker halves and retries | VERIFIED | `app/models/stt/chunker.py`: `WINDOW_SECONDS=900`, `OVERLAP_SECONDS=30`, `FLOOR_SECONDS=60`, `SINGLE_CALL_THRESHOLD_SECONDS=1800`; `_transcribe_chunk_oom_safe` splits at `mid = len(audio_slice)//2` and recursively transcribes BOTH halves (split-both-halves, not shrink-only). `tests/test_chunker.py::test_oom_halve_covers_full_audio` asserts full-duration coverage; `test_oom_halve_and_retry` + `test_oom_non_oom_runtime_error_reraises` pass. |
| 3 | SC-3: Spoken language auto-detected from first 30 s and recorded | VERIFIED | `chunker.py` line 137: `lang, _prob = adapter.detect_language(audio[: SAMPLE_RATE * 30])` when `language is None`; passed to every chunk; `Transcript.language=lang`. `adapter.py` `transcribe()` records `info.language` / `info.language_probability` on SttTranscription. `tests/test_chunker.py::test_chunked_path_detects_language_on_first_30s` + `tests/test_stt_adapter.py::test_language_autodetect_recorded` pass. |
| 4 | SC-4: STTAdapter Protocol exists; orchestrator code cannot import faster_whisper/whisper.cpp directly | VERIFIED | `app/models/stt/protocol.py` declares `class STTAdapter(Protocol)`. `grep -rE "from faster_whisper\|import faster_whisper\|import ctranslate2" app/` matches only `app/models/stt/adapter.py` (verified — docstring mentions in protocol.py/chunker.py are comment text, not imports). `tests/test_stt_boundary.py::test_import_boundary` + `tests/test_cli_transcribe.py::test_cli_does_not_import_faster_whisper` enforce it. |
| 5 | SC-5 (desktop CPU half): CLI runs to completion on the CPU desktop without code changes | VERIFIED | 03-03 SUMMARY records a real end-to-end run on the CPU desktop: `transcribe test.mp4 --out out.json` → downloaded the full `Systran/faster-whisper-large-v3` snapshot (3.09 GB / 7 files via `snapshot_download`) → `language=en segments=20 -> out.json` with `compute_type=int8`. Device resolved via `device_for(settings.backend, InferenceEngine.FASTER_WHISPER)` from persisted settings → CPU fallback, no `--device` flag. |
| 6 | SC-5 (laptop CUDA half): CLI runs end-to-end on the CUDA laptop (int8_float16 verified) | VERIFIED (human UAT 2026-06-22) | Human-verified on the physical CUDA laptop: `ctranslate2.get_supported_compute_types('cuda',0)` returned `{'int8_float16','bfloat16','int8_float32','float32','float16','int8_bfloat16','int8'}` (int8 + int8_float16 present, NOT only float32); `transcribe <file>` ran end-to-end on CUDA with no `--device` flag (same command as the desktop). Open Q1 closed: `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12` NOT required. Recorded in `03-UAT.md`. |
| 7 | TRANS-01 / must_have: FasterWhisperAdapter.transcribe maps faster-whisper Segment{start,end,text,avg_logprob} → SttSegment{start_s,end_s,text,confidence} | VERIFIED | `adapter.py` lines 156-186: `segments_iter, info = self._model.transcribe(...)`; `materialized = list(segments_iter)` (Pitfall 7); each `seg` mapped with `start_s=float(seg.start)`, `end_s=float(seg.end)`, `text=seg.text.strip()`, `confidence=math.exp(seg.avg_logprob)`. `tests/test_stt_adapter.py::test_segment_mapping` passes. |
| 8 | D-08 must_have: int8 verification fails loud on silent float32 fallback AND accepts int8→int8_float16 CUDA equivalence (positive + negative test) | VERIFIED | `adapter.py` `_ACCEPTED` table (lines 59-64) accepts `int8 → {int8, int8_float16, int8_float32}`; `load()` reads `self._model.model.compute_type` and raises `SttInt8VerificationError("int8 verification failed: ...")` if `actual not in accepted`. `tests/test_stt_adapter.py::test_int8_verification_fails_loud` (negative) + `test_int8_equivalence_accepted` (positive) pass. |
| 9 | INGEST-05 / D-02 must_have: OOM split-both-halves recursive retry covers full audio; non-OOM RuntimeErrors re-raised unchanged | VERIFIED | `chunker.py::_transcribe_chunk_oom_safe` lines 193-256: `_OOM_RE = re.compile(r"out of memory", re.IGNORECASE)`; `if not _OOM_RE.search(str(exc)): raise` (Pitfall 5 guard); on OOM it splits at midpoint and recursively transcribes both halves with right-half offset. `tests/test_chunker.py::test_oom_halve_covers_full_audio` + `test_oom_non_oom_runtime_error_reraises` pass. |
| 10 | CLI bootstrap must_have: load_settings_from_disk + configure BEFORE current(); configure_manager BEFORE get_manager() when unconfigured; `--device auto` valid argparse choice | VERIFIED | `transcribe.py` `_bootstrap_settings()` calls `load_settings_from_disk()` then `configure(settings)` before `current()`; `_get_or_configure_manager` mirrors manager.py 554-567 pattern. `--device` choices include `"auto"` (line 131). `tests/test_cli_transcribe.py::test_bootstrap_settings_runs_before_current` + `test_cli_configures_model_manager_when_unconfigured` + `test_device_auto_is_valid_choice` pass. |
| 11 | CLI must_have: finally-block `adapter.unload()` + raw RuntimeError preserved to stderr; atomic_write_json writes Transcript JSON; V5 path validation (input exists + --out parent exists) | VERIFIED | `transcribe.py` lines 215-246: `try` → `adapter.load()` + `transcribe_file` + `asyncio.run(atomic_write_json(out_path, transcript.model_dump()))`; `except RuntimeError as exc: print(str(exc), file=sys.stderr); return 1`; `finally: if adapter is not None: adapter.unload()`. Path validation lines 172-190 (input exists + parent exists, returns 2 on missing). `tests/test_cli_transcribe.py::test_adapter_unload_on_error` + `test_atomic_write_called` + `test_missing_file_errors` pass. |

**Score:** 11/11 truths verified (SC-5 laptop CUDA half closed by human UAT on 2026-06-22)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `app/models/stt/protocol.py` | STTAdapter Protocol + SttTranscription + SttSegment (D-06) | VERIFIED | `class STTAdapter(Protocol)` with `load`/`transcribe`/`detect_language`/`decode_audio`/`unload`; dataclasses present; module docstring carries SC-4 boundary statement. |
| `app/models/stt/adapter.py` | FasterWhisperAdapter — single faster_whisper/ctranslate2 import site + D-08 int8 verification | VERIFIED | Lazy imports inside `load()` + `decode_audio()` only; `_ACCEPTED` table + `SttInt8VerificationError`; SC-4 grep confirms only this file imports the packages. |
| `app/models/stt/__init__.py` | package re-exports | VERIFIED | Re-exports via `__getattr__` lazy import of `FasterWhisperAdapter`; STTAdapter/SttSegment/SttTranscription at module top. |
| `app/models/stt/chunker.py` | transcribe_file + chunker constants + OOM split-both-halves + overlap-dedupe | VERIFIED | `def transcribe_file` + `_transcribe_chunk_oom_safe` + 5 constants; `_OOM_RE` regex; recursive split-both-halves. |
| `app/cli/transcribe.py` | argparse CLI + main + bootstrap + device resolution + atomic write + finally unload | VERIFIED | `def main`, `_bootstrap_settings`, `_get_or_configure_manager`, `_default_compute_type`, `_build_parser`; finally-block unload + raw-error preservation present. |
| `app/cli/__init__.py` | package init | VERIFIED | Empty package init exists. |
| `pyproject.toml` | `[project.scripts] transcribe` + faster-whisper/ctranslate2 pins | VERIFIED | Lines 34-35 pins; lines 42-43 `[project.scripts] transcribe = "app.cli.transcribe:main"`. |
| `tests/_stt_fake.py` | FakeAdapter with oom_on_call + oom_above_seconds | VERIFIED (referenced) | Consumed by passing chunker tests; `oom_above_seconds` exercised by `test_oom_halve_covers_full_audio`. |
| `tests/test_stt_adapter.py` | 5 behavior cases incl. positive + negative int8 tests | VERIFIED | 5 tests pass. |
| `tests/test_stt_boundary.py` | SC-4 forbidden-import boundary gate | VERIFIED | `test_import_boundary` passes. |
| `tests/test_chunker.py` | 7 INGEST-05 cases incl. full-coverage OOM | VERIFIED | 7 tests pass. |
| `tests/test_cli_transcribe.py` | 14 CLI cases incl. bootstrap ordering + unload-on-error | VERIFIED | 14 tests pass. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `app/models/stt/adapter.py` | `faster_whisper.WhisperModel` | lazy in-body import inside `FasterWhisperAdapter.load()` | WIRED | line 105: `from faster_whisper import WhisperModel` inside `load()` method body. |
| `app/models/stt/adapter.py` | `ctranslate2.models.Whisper.compute_type` | `self._model.model.compute_type` after load | WIRED | line 124: `actual = self._model.model.compute_type`. |
| `app/models/stt/chunker.py` | `app/models/stt/protocol.py` | `from app.models.stt.protocol import STTAdapter` | WIRED | chunker.py line 61. |
| `app/models/stt/chunker.py` | `app/models/transcript.py` | `from app.models.transcript import Transcript, TranscriptSegment` | WIRED | chunker.py line 62; Transcript assembled at lines 127 + 190. |
| `app/models/stt/chunker.py` | `adapter.decode_audio` | Protocol method | WIRED | chunker.py line 105: `audio = adapter.decode_audio(audio_path)`. |
| `app/cli/transcribe.py` | `app/models/stt/chunker.py` | `from app.models.stt.chunker import transcribe_file` | WIRED | transcribe.py line 54; called at line 226. |
| `app/cli/transcribe.py` | `app/models/backend.py` | `device_for(settings.backend, InferenceEngine.FASTER_WHISPER)` | WIRED | transcribe.py line 202. |
| `app/cli/transcribe.py` | `app/settings/service.py` | `load_settings_from_disk` + `configure` before `current` | WIRED | transcribe.py lines 87 + 94 + 198. |
| `app/cli/transcribe.py` | `app/models/manager.py` | `configure_manager(ModelManager(settings))` before `get_manager()` | WIRED | transcribe.py lines 108-112; called from `_get_or_configure_manager` at line 209. |
| `app/cli/transcribe.py` | `app/storage/atomic.py` | `asyncio.run(atomic_write_json(out_path, transcript.model_dump()))` | WIRED | transcribe.py line 229. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `transcribe.py` → `transcript` | `transcript.language`, `transcript.segments` | `transcribe_file(adapter, file_path, ...)` → `adapter.transcribe` → faster-whisper `info.language` / `segments_iter` | Yes — real end-to-end run on CPU desktop produced `language=en segments=20` from a real 3.09 GB `large-v3` snapshot download | FLOWING |
| `chunker.py` → `merged` | `TranscriptSegment` list | `adapter.decode_audio(path)` → numpy array → per-chunk `adapter.transcribe` → offset + dedupe | Yes — real audio decode via PyAV through the Protocol seam; segment offset + dedupe exercised by 7 chunker tests incl. full-coverage OOM | FLOWING |
| `adapter.py` → `SttTranscription` | `segments`, `language`, `duration` | faster-whisper `self._model.transcribe(...)` → `info` + `segments_iter` materialized via `list()` | Yes — D-08 verification reads `self._model.model.compute_type` after load (real CT2 path); segment mapping exercised by `test_segment_mapping` | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| CLI entry point resolves after `pip install -e .` | `transcribe --help` | Prints argparse help with `--device {auto,cuda,cpu,rocm}` and all 7 args | PASS |
| SC-4 boundary grep over `app/` | `grep -rE "from faster_whisper\|import faster_whisper\|import ctranslate2" app/` | Only `app/models/stt/adapter.py` (plus comment-text matches in protocol.py/chunker.py docstrings — not actual imports) | PASS |
| Phase 03 test subset green | `pytest tests/test_stt_adapter.py tests/test_stt_boundary.py tests/test_chunker.py tests/test_cli_transcribe.py -q` | 29 passed in 2.76s | PASS |
| Full suite regression | `pytest -q` | 220 passed in 113.70s | PASS |
| `[project.scripts]` declared in pyproject | `grep "transcribe =" pyproject.toml` | `transcribe = "app.cli.transcribe:main"` at line 43 | PASS |

### Probe Execution

SKIPPED — no `scripts/*/tests/probe-*.sh` probes declared for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| INGEST-05 | 03-02-PLAN | App handles long videos by chunking audio automatically, with fallback when a single-shot job would OOM | SATISFIED | `chunker.py` windowed split + OOM split-both-halves recursive retry; 7 chunker tests incl. `test_oom_halve_covers_full_audio` pass. REQUIREMENTS.md marks Complete. |
| INGEST-06 | 03-01-PLAN, 03-03-PLAN | App auto-detects the spoken language from the audio | SATISFIED | `adapter.transcribe(language=None)` records `info.language`; chunker detects on first 30 s and propagates to all chunks; `test_language_autodetect_recorded` + `test_chunked_path_detects_language_on_first_30s` pass. REQUIREMENTS.md marks Complete. |
| TRANS-01 | 03-01-PLAN, 03-03-PLAN | App produces a transcript with timestamps for the entire video | SATISFIED | CLI writes `Transcript` JSON via `atomic_write_json`; `SttSegment{start_s,end_s,text,confidence}` mapped from faster-whisper; real desktop run produced 20 timestamped segments. REQUIREMENTS.md marks Complete. |

No orphaned requirements — all three IDs declared in PLAN frontmatter appear in REQUIREMENTS.md mapped to Phase 3, and all three are covered by verified artifacts.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `app/cli/transcribe.py` | 236-240, 210 | `except RuntimeError` only — `ModelManagerError`/`ModelGatedError`/`ModelIntegrityError`/`OSError` from `ensure_downloaded` + `atomic_write_json` escape as tracebacks (CR-01 + WR-08) | Warning | Failure-path quality defect; on a gated-repo or SHA-mismatch the user sees a stack trace instead of a clean exit-1 stderr line. Does NOT block the runnable slice on the default non-gated `Systran/faster-whisper-large-v3` repo (desktop CPU half verified end-to-end). Tracked in `03-REVIEW.md` as follow-up. |
| `app/cli/transcribe.py` | 210, 229 | Two `asyncio.run` calls in one CLI invocation (WR-07) | Info | Works today; minor refactor opportunity. |
| `app/cli/transcribe.py` | 131, 199-204 | `--device rocm` accepted but CT2 has no ROCm device string (WR-02) | Warning | `--device rocm` will raise at load time. Memory note says ROCm is best-effort CPU fallback; CLI should remap `rocm` → `cpu` or drop the choice. Default `--device auto` path is unaffected. |
| `app/models/manager.py` | 456-458 | Snapshot fast-path trusts `config.json` presence with no wholeness check (WR-01) | Warning | Corrupt-snapshot risk on interrupted downloads; self-healing absent. Not exercised by the suite (mocked). |
| `app/models/stt/chunker.py` | 168, 180 | Overlap-dedupe uses theoretical `chunk_start + chunk_seconds` not actual last-segment end (WR-03) | Info | Standard heuristic; can over-drop on sparse audio. Documented in docstring as heuristic. |
| `app/models/stt/chunker.py` | 144, 168 | `prev_chunk_end = 0.0` can drop chunk-0 segments with tiny negative `start_s` (WR-05) | Info | Edge-case correctness; FakeAdapter tests cannot catch (fake emits starts ≥ 0). |
| `app/models/manager.py` | 378-427, 492-507 | `os.environ["HF_HUB_DISABLE_XET"]` mutation unsafe under concurrent downloads (WR-04) | Warning | Race between concurrent downloads; single-CLI path unaffected. |
| `app/models/manager.py` | 201-211 | `_get_token` swallows all exceptions and returns None (WR-06) | Info | Transient settings-reload errors silently strip token; CLI path is unaffected (settings bootstrapped before call). |

No `TBD`/`FIXME`/`XXX` debt markers without issue references in any Phase 3 source file. No empty/stub returns flowing to user-visible output.

### Gaps Summary

No gaps remain. The runnable STT pipeline is wired end-to-end and exercised on both machines: a real CPU desktop run (3.09 GB snapshot, 20 segments, `language=en`) AND a real CUDA laptop run (human UAT 2026-06-22 — int8/int8_float16 compute types present, end-to-end transcribe succeeded with no `--device` flag). SC-1, SC-2, SC-3, SC-4, SC-5 are all fully verified. TRANS-01, INGEST-05, INGEST-06 are satisfied. Open Q1 (CUDA runtime libs) is closed: `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12` were NOT required.

The CLI's narrow `except RuntimeError` (CR-01) and the other review warnings are failure-path / quality defects tracked in `03-REVIEW.md` for a follow-up; they do not impede the runnable slice on the default non-gated STT repo and do not block the phase goal.

### Human Verification Required

1. **SC-5 laptop CUDA half + Open Q1 (CUDA runtime libs)** — **PASSED (2026-06-22)**

   **Test:** On the CUDA laptop, run `python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda',0))"` and confirm `int8`/`int8_float16` are present (NOT only `float32`). Then run `transcribe <small-file> --out out.json` with no `--device` flag.
   **Expected:** CLI runs end-to-end on CUDA with default `compute_type=int8_float16`; `out.json` has non-empty segments + detected language; same command as the desktop (no per-machine flags). If `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12` pip packages were required, record them as a mandatory follow-up to add to `pyproject.toml` (Codex HIGH: not a silent-first-run risk).
   **Why human:** Requires the physical CUDA laptop hardware and a real model download; cannot be exercised from the verifier process. Closes Open Q1.
   **Result:** PASSED. `get_supported_compute_types('cuda',0)` returned `{'int8_float16','bfloat16','int8_float32','float32','float16','int8_bfloat16','int8'}` (int8 + int8_float16 present). `transcribe <file>` ran end-to-end on CUDA with no `--device` flag. `nvidia-*-cu12` packages NOT required — Open Q1 closed with no `pyproject.toml` change. Recorded in `03-UAT.md`.

### Verdict

**Status: passed.** 11/11 must-haves verified. The automated checks (code inspection, boundary grep, 29 phase tests, 220-test full suite, `transcribe --help` smoke check, real end-to-end CPU desktop run recorded in 03-03 SUMMARY) all pass, AND the deferred SC-5 laptop CUDA half is now closed by human UAT (2026-06-22): CUDA compute types include int8/int8_float16 and `transcribe` ran end-to-end on the laptop with no `--device` flag. The phase goal — a runnable STT pipeline with the GPU abstraction seam proven on BOTH machines — is achieved.

**Next command:** `/gsd-secure-phase 03` (security review, required before advancing per `workflow.security_enforcement=true`), then `/gsd-plan-phase 04` to plan the next phase. The CR-01 / review warnings in `03-REVIEW.md` remain a non-blocking follow-up.

---

_Verified: 2026-06-22 (human UAT closed SC-5 laptop CUDA half)_
_Verifier: Claude (gsd-verifier) + human UAT_