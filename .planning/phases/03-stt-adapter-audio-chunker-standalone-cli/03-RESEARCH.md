# Phase 3: STT Adapter + Audio Chunker + Standalone CLI - Research

**Researched:** 2026-06-19
**Domain:** STT inference (faster-whisper / CTranslate2), audio chunking + OOM retry, Python CLI packaging
**Confidence:** HIGH (core API facts verified against the installed faster-whisper 1.2.1 / ctranslate2 4.7.2 source; version + CUDA-runtime facts verified via PyPI + official CT2 docs + upstream issues)

## Summary

Phase 3 is the first phase that actually runs a model for inference. It plugs into the Phase 2 seams: `device_for(backend, InferenceEngine.FASTER_WHISPER)` for device resolution, `ModelManager.ensure_downloaded` / `load(ModelCategory.STT)` for the on-demand download + VRAM reservation, and the existing `Transcript` / `TranscriptSegment` schema + `atomic_write_json` for output. The genuinely uncertain facts the planner needs are all API-shaped and I verified them directly against the installed package source rather than relying on training memory:

- **faster-whisper `transcribe()` accepts a file path OR a NumPy array** (`audio: Union[str, BinaryIO, numpy.ndarray]`), and its `decode_audio()` opens the container with **PyAV which bundles the FFmpeg libs inside the wheel** (no system ffmpeg) and decodes the first audio stream (`audio=0`) to 16 kHz mono float32 — D-01 is confirmed exactly as written, including video-container audio decoding. `[VERIFIED: faster_whisper/audio.py + __init__.py source, installed v1.2.1]`
- **int8 verification is real and cheap**: `ctranslate2.models.Whisper` exposes a `compute_type` property (verified present on the class) AND `ctranslate2.get_supported_compute_types(device, device_index)` returns the set the hardware actually supports. The fail-loud check is: after `WhisperModel(...)`, assert `self._model.model.compute_type` equals the requested compute_type (or an accepted equivalent — see Pitfall 3). `[VERIFIED: ctranslate2 4.7.2 introspection]`
- **The CUDA OOM exception is a plain `RuntimeError` with message `"CUDA failed with error out of memory"`**, raised from `self.model.generate(...)` inside `generate_with_fallback`. The chunker's halve-and-retry catches `RuntimeError` and matches the message — there is no dedicated `CT2OutOfMemoryError` class. `[CITED: github.com/SYSTRAN/faster-whisper/issues/442]`
- **The `int8_float16` empty-transcription bug (issue #440) is confined to GTX 1650/1660 series GPUs with older cuDNN**, NOT the RTX 2000 Ada laptop (Ada / compute capability 8.9, cuDNN 9 bundled in the CT2 wheel). D-04's `int8_float32` escape hatch is the documented workaround and stays as `--compute-type`. `[CITED: github.com/SYSTRAN/faster-whisper/issues/440]`

**One load-bearing gap the planner MUST address:** the CTranslate2 win_amd64 wheel is built with `CUDA_DYNAMIC_LOADING=ON` — it bundles `cudnn64_9.dll` and `libiomp5md.dll` but **NOT** `cublas64_12.dll` / `cudart12.dll`. On the laptop, the CUDA runtime libs must come from somewhere (a system CUDA 12.x toolkit, OR the `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` pip packages, OR a torch+cu124 wheel). Phase 3 deliberately does NOT install torch, so the CUDA-runtime-lib source for the laptop is an open question (see Open Questions Q1). This does not affect the desktop (CPU fallback needs no CUDA libs).

**Primary recommendation:** Pin `faster-whisper==1.2.1` + `ctranslate2==4.7.2` (the pair verified installed and importing cleanly on this machine, cp312-win_amd64, satisfying `faster-whisper`'s `ctranslate2>=4.0,<5` constraint). Import both ONLY inside `app/models/stt/`. Verify int8 by reading `self._model.model.compute_type` after load. Catch `RuntimeError` with an "out of memory" message match for the halve-and-retry. Use argparse (stdlib) for the CLI — the project ships no CLI lib yet and D-17 is stdlib-first.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Use faster-whisper's built-in PyAV decoder — pass the file path directly to `transcribe()`; do NOT shell out to a system `ffmpeg` and do NOT add `pydub`/`librosa`. PyAV bundles FFmpeg in the wheel; video containers work natively (audio stream decoded, video track ignored). `transcribe()` also accepts a raw NumPy array, so the chunker can hand it pre-decoded audio.
- **D-02:** Coarse windowed chunker ON TOP of faster-whisper's internal 30 s sliding window. ≤30 min → single `transcribe()`. >30 min → ~15-min windows + ~30 s overlap + stitch (offset timestamps, trim overlap to midpoint). Per-chunk OOM → catch CTranslate2/cuda OOM, halve chunk, retry down to ~1 min floor. `vad_filter=True`.
- **D-03:** `console_scripts` entry point named `transcribe` in `pyproject.toml` `[project.scripts]`, backed by `app/cli/transcribe.py`. Args: positional `<file>`; `--preset {small,balanced,large}` (default `balanced`); `--device {cuda,cpu,rocm}` (default auto via `device_for(backend, InferenceEngine.FASTER_WHISPER)` from persisted `settings.backend`); `--language` (force; default auto-detect first 30 s); `--compute-type {int8,int8_float16,float16,int8_float32}` (override backend default); `--out <path>` (default `<input>.transcript.json`); `--verbose`. Atomic-write `Transcript` JSON. NOT a job dir (Phase 4). Thin caller of `STTAdapter` (never imports faster-whisper — SC-4).
- **D-04:** Default `compute_type` = `int8_float16` on CUDA, `int8` on CPU (and ROCm→CPU path; CTranslate2 has no ROCm). `--compute-type` override. `int8_float32` escape hatch for the int8_float16 empty-transcription bug.
- **D-05:** CUDA laptop primary; desktop CPU fallback acceptable, NOT a blocker. Device pluggable `Literal['cuda','cpu','rocm']`. NO Phase 3 ROCm re-spike prerequisite; supersedes 02-03-SPIKE §5 #5.
- **D-06:** `STTAdapter` Protocol in `app/models/stt`. `faster-whisper` and `ctranslate2` imported ONLY inside `app/models/stt`. Boundary check: `grep -rE 'from faster_whisper|import faster_whisper|import ctranslate2' app/` matches only `app/models/stt`. Mirrors Phase 2 `huggingface_hub` boundary. Device via `device_for(backend, InferenceEngine.FASTER_WHISPER)`.
- **D-07:** faster-whisper native language detection (`language=None` auto-detects). Record in `Transcript.language`. `--language` forces + skips detect. Chunked path detects on first 30 s and passes to all chunks.
- **D-08:** Pin `faster-whisper` + `ctranslate2` to compatible versions (researcher determines exact pins). int8 verification = assert loaded model runs chosen `compute_type` (fail loud on silent float16 fallback — analogue of Phase 2 Pitfall 12).
- **D-09:** codex + gemini are default cross-AI reviewers downstream.

### Claude's Discretion
All four gray areas (D-01 decode, D-02 chunking, D-03 CLI, D-04 compute type) plus D-07 (language detect) and D-08 (pin/verify) were deferred by the user to Claude with a recorded rationale each.

### Deferred Ideas (OUT OF SCOPE)
- `ffmpeg`-CLI decode fast path (violates silent-no-install laptop constraint; future optimization).
- whisper.cpp HIP adapter for the RX 6800 (only path to GPU STT on the desktop; future, separate decision).
- ROCm re-spike (TheRock dated-alpha wheel) — superseded by D-05.
- Prefetch the STT model at job-submit (Phase 4 follow-up).
- Streaming/real-time transcription (out of scope per PROJECT.md).
- Per-chunk progress broadcast over WebSocket (Phase 4).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-05 | App handles long videos by chunking audio automatically, with fallback when a single-shot job would OOM | Chunker design (D-02): ≤30 min single `transcribe()`; >30 min ~15-min windows + 30 s overlap; stitch via Segment.start/end offset + midpoint overlap trim; OOM `RuntimeError` catch → halve chunk → retry to ~1 min floor. OOM exception confirmed `RuntimeError: CUDA failed with error out of memory`. |
| INGEST-06 | App auto-detects the spoken language from the audio | `language=None` auto-detects on the first 30 s (faster-whisper transcribe.py docstring + `detect_language(audio, ...)` standalone method returns `(lang, probability, all_lang_probs)`); record in `Transcript.language`; `--language` force override. |
| TRANS-01 | App produces a transcript with timestamps for the entire video | `Segment` dataclass has `start: float`, `end: float`, `text: str` (+ `avg_logprob` → confidence, `no_speech_prob`); map to `TranscriptSegment(start_s, end_s, text, confidence)`; write `Transcript` JSON via `atomic_write_json`. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists in the working directory. No `.claude/skills/` or `.agents/skills/` directory exists. The governing constraints come from `.planning/PROJECT.md` via the CONTEXT canonical refs:

- **Silent-no-install first-run (laptop):** no system-level dependency installs — D-01 PyAV-in-the-wheel is the direct consequence. ⚠️ The CT2 CUDA-runtime-lib gap (Q1) is the one place this constraint is at risk; the planner must resolve it with pip-installable `nvidia-*-cu12` packages or confirm a system CUDA toolkit is present on the laptop.
- **No telemetry, single-user no-auth, back-end is the only thing that touches models + filesystem.**
- **8 GB laptop VRAM budget** — `int8_float16` (D-04) keeps large-v3 at ~2 GB constant (grounded in the upstream benchmark: int8 = 2926 MB vs float16 = 4525 MB, ~35% less, <0.1% WER diff).
- **GSD config:** `workflow.nyquist_validation = true` → include `## Validation Architecture`. `commit_docs = true`. `review.default_reviewers = ["codex","gemini"]` (D-09).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Audio decode (PyAV) | Local I/O (in-process) | — | `faster_whisper.audio.decode_audio` runs in the CLI process; PyAV bundles FFmpeg libs. No external service. |
| STT inference (faster-whisper / CTranslate2) | Local compute (in-process) | — | Runs on the GPU/CPU in the CLI process; no API tier. The `STTAdapter` Protocol is the in-process seam. |
| Device + compute_type resolution | App config (`app.models.backend`, `app.settings`) | — | `device_for(backend, InferenceEngine.FASTER_WHISPER)` + `settings.backend` + `settings.quality_preset` resolve device + compute_type; the adapter receives resolved values, never imports torch/backend detection. |
| Model download + VRAM reservation | `app.models.manager` (Phase 2) | — | `ModelManager.ensure_downloaded` + `load(ModelCategory.STT)` already shipped; the adapter loads weights into the reserved slot. |
| Chunking + OOM retry + stitch | `app.models.stt.chunker` (new) | — | Pure-Python over the adapter Protocol; no GPU/IO tier of its own. |
| Transcript persistence | `app.storage.atomic` (Phase 1) | — | `atomic_write_json` writes `transcript.json` (D-04 Phase 1). |
| CLI entry + arg parsing | `app.cli.transcribe` (new) | — | argparse (stdlib); thin caller of the adapter via the Protocol. |
| Job orchestration / queue / WebSocket | — (Phase 4) | — | Explicitly OUT of scope for Phase 3; the CLI is a standalone proof, NOT a job. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `faster-whisper` | `1.2.1` (pin) | Whisper STT via CTranslate2; PyAV decode; native language detect; VAD | The project's locked STT engine (D-01..D-08). 1.2.1 is the current latest and the version verified installed + importing on this machine. `[VERIFIED: pip index versions + installed source]` |
| `ctranslate2` | `4.7.2` (pin) | The inference engine faster-whisper calls into; exposes `compute_type` property + `get_supported_compute_types` | Required by faster-whisper 1.2.1 (`ctranslate2>=4.0,<5`). 4.7.2 verified installed; bundles `cudnn64_9.dll` + `libiomp5md.dll` in the win_amd64 wheel. `[VERIFIED: faster-whisper 1.2.1 Requires-Dist + CT2 RECORD]` |
| `av` (PyAV) | (transitive, via faster-whisper) | Audio container decode; bundles FFmpeg libs in the wheel | The D-01 no-system-ffmpeg mechanism. Pulled by faster-whisper's `av` requirement; do NOT pin separately unless a conflict appears. `[CITED: faster_whisper/audio.py header comment]` |
| `argparse` | stdlib | CLI arg parsing | D-17 stdlib-first; the project ships no CLI lib. `[ASSUMED]` (stable stdlib, no verification needed) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | (transitive, via faster-whisper/ctranslate2) | Audio array handoff to `transcribe()` / `detect_language()` when pre-decoding for the chunker | Only if the chunker decodes once and passes arrays (alternative: pass the file path per chunk). `[ASSUMED]` |
| `onnxruntime` | (transitive, via faster-whisper) | Silero VAD backend | Pulled by faster-whisper for `vad_filter=True`; no direct use. `[ASSUMED]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `argparse` | `typer` / `click` | Typer/click add a dep for nicer help; D-17 stdlib-first + YAGNI wins. The CLI has ~7 args — argparse handles it cleanly. |
| `ctranslate2==4.7.2` | `ctranslate2==4.8.0` (latest) | 4.8.0 also satisfies faster-whisper's `>=4.0,<5`. 4.7.2 is verified installed + working on this desktop; pin to the verified pair unless the laptop needs a 4.8.0 fix. `[ASSUMED]` |
| file-path-per-chunk `transcribe()` | pre-decode once → pass NumPy array per chunk | One `decode_audio` call vs N PyAV opens; decoding is ~5–10% of runtime so either is fine. Pre-decode avoids repeated `gc.collect()` overhead and gives the chunker the exact array to slice. Recommended: pre-decode once, slice the array, pass slices. `[ASSUMED]` |
| `BatchedInferencePipeline` | plain `WhisperModel.transcribe` | Batched is faster but uses MORE VRAM (int8 batched=4500 MB vs non-batched=2926 MB) — wrong direction for an 8 GB laptop with a chunker already defending VRAM. Out of scope for Phase 3; noted as a future throughput optimization. `[CITED: github.com/SYSTRAN/faster-whisper README benchmark]` |

**Installation:**
```bash
pip install "faster-whisper==1.2.1" "ctranslate2==4.7.2"
# On the CUDA laptop, also ensure the CUDA 12.x runtime libs are findable:
pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12   # see Open Questions Q1
```

**Version verification (run this session):**
```bash
$ pip index versions faster-whisper
faster-whisper (1.2.1)   # latest == 1.2.1   [VERIFIED]
$ pip index versions ctranslate2
ctranslate2 (4.8.0)      # latest 4.8.0; pinned to 4.7.2 (installed, verified working)
$ python -c "import faster_whisper, ctranslate2; print(faster_whisper.__version__, ctranslate2.__version__)"
1.2.1 4.7.2              # [VERIFIED on this desktop, cp312-win_amd64]
```

## Package Legitimacy Audit

> The `gsd-tools query package-legitimacy` seam was not on PATH in this environment, so the gate was run manually via registry + source-repo verification. Both packages are flagship, high-download, long-maintained projects.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `faster-whisper` | PyPI | ~5 yrs (1.0.0 2023) | millions/wk | github.com/SYSTRAN/faster-whisper | OK | Approved |
| `ctranslate2` | PyPI | ~7 yrs (4.x line) | millions/wk | github.com/OpenNMT/CTranslate2 | OK | Approved |
| `av` (PyAV) | PyPI | ~10 yrs | millions/wk | github.com/PyAV-Org/PyAV | OK | Approved (transitive) |
| `nvidia-cublas-cu12` | PyPI | NVIDIA official | millions/wk | pypi.nvidia.com | OK | Approved (CUDA-laptop only; Q1) `[ASSUMED]` |
| `nvidia-cuda-runtime-cu12` | PyPI | NVIDIA official | millions/wk | pypi.nvidia.com | OK | Approved (CUDA-laptop only; Q1) `[ASSUMED]` |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious [SUS]:** none

*The `nvidia-*-cu12` packages are tagged `[ASSUMED]` because I did not run `pip view` on them this session (they are not installed on this desktop). The planner should add a `checkpoint:human-verify` before adding them to pyproject, OR confirm the laptop already has a system CUDA 12.x toolkit on PATH (which makes them unnecessary).*

## Architecture Patterns

### System Architecture Diagram

```
                ┌─────────────────────────────────────────────────────────────┐
                │  CLI entry: `transcribe <file> --preset --device --language │
                │              --compute-type --out --verbose`                │
                │  (app/cli/transcribe.py — argparse, thin caller, SC-4)      │
                └───────────────────────────┬─────────────────────────────────┘
                                            │ resolve device + compute_type
                                            ▼
                ┌────────────────────────────────────────────────────────────┐
                │  settings.backend ──► device_for(backend, FASTER_WHISPER)   │
                │  ──► device ('cuda' | 'cpu')                                │
                │  compute_type default: int8_float16 (CUDA) / int8 (CPU)    │
                │  (D-04; --compute-type override wins)                      │
                └───────────────────────────┬────────────────────────────────┘
                                            │
                                            ▼
              ┌─────────────────────────────────────────────────────────────┐
              │  Chunker (app/models/stt/chunker.py)                        │
              │  decode_audio(file) once → numpy array (PyAV, 16k mono)     │
              │  if duration <= 30 min:  single adapter.transcribe()        │
              │  else:  ~15-min windows + 30 s overlap                       │
              │    for each chunk:                                          │
              │      try adapter.transcribe(slice, language=lang)           │
              │      except RuntimeError("out of memory"):                  │
              │         halve chunk size → retry (floor ~1 min)              │
              │  stitch: offset segment.start_s/end_s by chunk start;        │
              │  trim overlap region to midpoint                            │
              │  language: detect on first 30 s (chunked path) → pass to all │
              └───────────────────────────┬─────────────────────────────────┘
                                          │ STTAdapter Protocol (D-06)
                                          ▼
              ┌─────────────────────────────────────────────────────────────┐
              │  FasterWhisperAdapter (app/models/stt/adapter.py)           │
              │  *** ONLY HERE: import faster_whisper / ctranslate2 ***     │
              │  ModelManager.ensure_downloaded(STT spec) → model_path      │
              │  WhisperModel(model_path, device, compute_type)             │
              │  VERIFY: assert model.model.compute_type == requested        │
              │           (D-08 fail-loud int8 verification)                │
              │  transcribe(audio, language, vad_filter=True)               │
              │    → map Segment{start,end,text,avg_logprob}                │
              │      → TranscriptSegment{start_s,end_s,text,confidence}     │
              │  detect_language(audio_30s) → (lang, prob)                  │
              └───────────────────────────┬─────────────────────────────────┘
                                          │ SttTranscription (Protocol result)
                                          ▼
              ┌─────────────────────────────────────────────────────────────┐
              │  Transcript (app/models/transcript.py — existing)           │
              │  atomic_write_json(out, transcript.model_dump())            │
              │  stdout summary: language, segment count, duration          │
              └─────────────────────────────────────────────────────────────┘
```

Trace the primary use case (SC-1): `transcribe video.mp4` → resolve device from `settings.backend` → chunker decodes via PyAV → ≤30 min so single `adapter.transcribe()` → adapter loads WhisperModel (int8_float16 on laptop CUDA), verifies `compute_type`, returns segments → chunker maps to `Transcript` → `atomic_write_json` writes `video.mp4.transcript.json` → stdout summary. Same command on the desktop resolves `device='cpu'`, `compute_type='int8'`, no code change (SC-5).

### Recommended Project Structure
```
app/models/stt/
├── __init__.py          # Re-exports STTAdapter Protocol + SttTranscription + FasterWhisperAdapter
├── protocol.py          # STTAdapter Protocol + SttTranscription / SttSegment result types
├── adapter.py           # FasterWhisperAdapter — THE ONLY faster_whisper/ctranslate2 import site
└── chunker.py           # windowed chunker + OOM halve-and-retry + stitch (pure Python, Protocol-only)
app/cli/
├── __init__.py
└── transcribe.py        # argparse CLI + console_scripts entry point `transcribe`
```

The boundary check target: `grep -rE "from faster_whisper|import faster_whisper|import ctranslate2" app/` matches ONLY files under `app/models/stt/adapter.py` (the single implementation file). `protocol.py` and `chunker.py` import NEITHER — they depend on the Protocol only. The CLI imports neither — it depends on the chunker + adapter factory.

### Pattern 1: Lazy in-body import (the Phase 2 boundary pattern, mirrored)
**What:** `faster_whisper` and `ctranslate2` are imported inside function bodies / methods in `app/models/stt/adapter.py`, NOT at module top. The Protocol module and chunker never import them.
**When to use:** Always, for any GPU/ML package in this project.
**Example:**
```python
# app/models/stt/protocol.py — NO faster_whisper import here
from __future__ import annotations
from typing import Protocol
import numpy as np
from app.models.transcript import TranscriptSegment

class SttTranscription:  # dataclass
    segments: list[TranscriptSegment]
    language: str
    language_probability: float
    duration: float

class STTAdapter(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: "str | np.ndarray", language: str | None = None,
                   vad_filter: bool = True) -> SttTranscription: ...
    def detect_language(self, audio: "np.ndarray") -> tuple[str, float]: ...
    def unload(self) -> None: ...
```
```python
# app/models/stt/adapter.py — THE ONLY import site
class FasterWhisperAdapter:
    def __init__(self, model_path: str, device: str, compute_type: str) -> None:
        self._model_path = model_path
        self._device = device
        self._compute_type = compute_type
        self._model = None  # loaded lazily

    def load(self) -> None:
        from faster_whisper import WhisperModel  # lazy in-body import
        self._model = WhisperModel(self._model_path, device=self._device,
                                    compute_type=self._compute_type)
        # D-08 int8 verification — fail loud on silent fallback
        actual = self._model.model.compute_type  # ctranslate2.models.Whisper.compute_type
        if not self._compute_type_ok(actual):
            raise RuntimeError(
                f"int8 verification failed: requested compute_type="
                f"{self._compute_type!r} but loaded={actual!r} "
                f"(silent fallback — analogue of Phase 2 Pitfall 12)"
            )
```

### Pattern 2: int8 verification (D-08)
**What:** After `WhisperModel(...)`, read `self._model.model.compute_type` (the inner `ctranslate2.models.Whisper` exposes a `compute_type` property — verified present on the class) and assert it matches the request, OR is an accepted equivalent per the fallback table.
**When to use:** Every adapter load. This is the "settings says CUDA/int8 but jobs run float16" analogue of Phase 2 Pitfall 12.
**Equivalence rule (Pitfall 3):** faster-whisper models are saved in float16. Post CT2 v3.18, requesting `int8` on a float16-saved model resolves to `int8_float16` on CUDA (storage stays float16, compute int8). On CPU, `get_supported_compute_types('cpu',0)` returns `{'int8','int8_float32','float32'}` — float16 is NOT supported, so `int8` on CPU loads as `int8` (with float32 storage). The verification must accept the documented equivalence, not just exact string match:
```python
_ACCEPTED = {
    "int8":           {"int8", "int8_float16", "int8_float32"},
    "int8_float16":   {"int8_float16"},
    "int8_float32":   {"int8_float32"},
    "float16":        {"float16", "int8_float16"},  # CT2 may upcast
}
```
Source of the equivalence: `[CITED: opennmt.net/CTranslate2/quantization.html]` + `[VERIFIED: ctranslate2.get_supported_compute_types('cpu',0) == {'int8','int8_float32','float32'}]`.

### Pattern 3: OOM halve-and-retry (D-02)
**What:** Wrap each chunk's `adapter.transcribe()` in a try/except that catches `RuntimeError`, matches `"out of memory"` in the message (case-insensitive), halves the chunk, and retries down to a ~1 min floor.
**When to use:** Every chunked transcribe call (>30 min files).
**Example:**
```python
import re
_OOM_RE = re.compile(r"out of memory", re.IGNORECASE)
FLOOR_SECONDS = 60

def _transcribe_chunk_oom_safe(adapter, audio_slice, language, chunk_s):
    while chunk_s >= FLOOR_SECONDS:
        try:
            return adapter.transcribe(audio_slice, language=language, vad_filter=True)
        except RuntimeError as exc:
            if not _OOM_RE.search(str(exc)):
                raise  # not an OOM — propagate
            chunk_s //= 2
            audio_slice = audio_slice[: chunk_s * SAMPLE_RATE]
            continue
    # below the floor — last attempt, let it raise
    return adapter.transcribe(audio_slice, language=language, vad_filter=True)
```
Source of the exception shape: `[CITED: github.com/SYSTRAN/faster-whisper/issues/442]` — `RuntimeError: CUDA failed with error out of memory` raised from `self.model.generate(...)` in `generate_with_fallback`.

### Pattern 4: Stitch with offset + midpoint overlap trim (D-02)
**What:** Each chunk's `Segment.start`/`end` are relative to the chunk; add the chunk's absolute start offset. The overlap region between consecutive chunks is trimmed to its midpoint so no text is duplicated and timestamps are continuous.
**When to use:** The >30 min chunked path.
**Example:**
```python
# chunk i starts at offset_i (seconds), overlap o = 30 s
# segments in chunk i have start/end relative to offset_i
for seg in chunk_segments:
    out_start = seg.start + offset_i
    out_end   = seg.end   + offset_i
    # drop segments fully inside the overlap region already covered by chunk i-1's midpoint
    if out_end <= prev_midpoint:
        continue
    if out_start < prev_midpoint:
        out_start = prev_midpoint  # trim overlap to midpoint
    merged.append(TranscriptSegment(start_s=out_start, end_s=out_end,
                                    text=seg.text, confidence=...))
```

### Anti-Patterns to Avoid
- **Setting faster-whisper's `chunk_length` parameter manually (non-30 s):** causes feature-extractor shape errors per upstream issues; D-02 explicitly avoids it. The chunker slices the audio ARRAY, then calls `transcribe()` with its default 30 s internal window. `[CITED: faster-whisper issues on chunk_length shape errors]`
- **Importing `faster_whisper` / `ctranslate2` outside `app/models/stt/adapter.py`:** breaks SC-4 + the Phase 2 boundary discipline. The chunker and CLI depend on the Protocol, never the package.
- **Using `BatchedInferencePipeline` for Phase 3:** it raises VRAM (int8 batched=4500 MB vs 2926 MB non-batched) — wrong direction for an 8 GB laptop. Future throughput optimization only.
- **Treating `int8` request == `int8` loaded as a literal string match:** the float16-saved-model + CT2 v3.18+ behavior means `int8` on CUDA loads as `int8_float16`. The verification must accept the documented equivalence (Pitfall 3) or it will false-positive on every CUDA load.
- **Catching bare `RuntimeError` for OOM without a message match:** CT2 raises `RuntimeError` for many non-OOM reasons (flash-attention dtype, cuBLAS version mismatches). Match the `"out of memory"` substring so non-OOM errors propagate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Audio decode (any container → 16 kHz mono float32) | ffmpeg subprocess / pydub / librosa | `faster_whisper.audio.decode_audio` (PyAV) | PyAV bundles FFmpeg in the wheel (silent-install); handles MP4/MKV/WebM audio streams natively. `[VERIFIED: faster_whisper/audio.py]` |
| 30 s sliding-window segmentation + timestamp tokens | Custom windowing | faster-whisper's internal `transcribe()` (default `chunk_length=30`) | The model's internal windowing IS the segmentation; the chunker is only a VRAM safety valve on top. `[CITED: faster-whisper README]` |
| VAD (silence dropping) | Energy-threshold / webrtcvad | `vad_filter=True` (Silero VAD, bundled via onnxruntime) | Reduces processed audio → lower VRAM + fewer garbage segments; D-02 locks it on. `[CITED: faster-whisper README VAD section]` |
| Language detection | Custom classifier | faster-whisper `language=None` / `detect_language(audio)` | Native Whisper language tokens; returns `(lang, probability, all_lang_probs)`. `[VERIFIED: transcribe.py + detect_language signature]` |
| OOM detection | VRAM polling / pre-allocation | Catch `RuntimeError` with `"out of memory"` message | The exception IS the signal; cheaper + more reliable than polling. `[CITED: issue #442]` |
| int8 verification | Heuristic / log scraping | `model.model.compute_type` property + `get_supported_compute_types` | CT2 exposes the loaded compute_type directly. `[VERIFIED: ctranslate2 4.7.2 introspection]` |
| Atomic transcript.json write | Custom fsync/rename | `app.storage.atomic.atomic_write_json` (Phase 1 D-04) | Already shipped, already retried for Windows file locks. |

**Key insight:** faster-whisper + CTranslate2 already solve decode, segmentation, VAD, language detect, and int8 quantization. Phase 3's job is the adapter Protocol + the coarse chunker + the CLI — NOT re-implementing any of those.

## Common Pitfalls

### Pitfall 1: CUDA runtime libs not bundled in the CT2 wheel (LAPTOP BLOCKER)
**What goes wrong:** On the laptop, `WhisperModel(..., device="cuda")` raises `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded` (or silently falls back to CPU, defeating the whole GPU-abstraction proof).
**Why it happens:** CT2 win_amd64 wheels are built with `CUDA_DYNAMIC_LOADING=ON`; they bundle `cudnn64_9.dll` + `libiomp5md.dll` but NOT `cublas64_12.dll` / `cudart12.dll`. Phase 3 does NOT install torch (which would otherwise bring the CUDA libs via a +cu124 wheel).
**How to avoid:** The planner MUST either (a) add `nvidia-cublas-cu12` + `nvidia-cuda-runtime-cu12` pip deps and ensure their DLLs are findable by CT2 (add their `lib` dirs to `os.environ["PATH"]` at adapter import time, or copy DLLs next to `ctranslate2.dll`), OR (b) confirm the laptop already has a system CUDA 12.x toolkit on PATH. This is the single biggest threat to the silent-no-install laptop promise.
**Warning signs:** `RuntimeError` mentioning `cublas64_*.dll` / `cudart64_*.dll` / `Library ... not found`; or `compute_type` silently reading `float32` on a CUDA device (fallback). `[CITED: opennmt.net/CTranslate2/installation.html + github.com/OpenNMT/CTranslate2/issues/1084]`

### Pitfall 2: `int8` request loads as `int8_float16` on CUDA (false-positive verification failure)
**What goes wrong:** The D-08 verification `assert model.model.compute_type == "int8"` fails on every CUDA load even though int8 IS in use.
**Why it happens:** faster-whisper models are saved in float16; post CT2 v3.18, requesting `int8` on a float16-saved model resolves to `int8_float16` on CUDA (storage float16, compute int8).
**How to avoid:** Verify against an accepted-equivalence set, not a literal string (Pattern 2). On CPU, `int8` loads as `int8` (float16 unsupported → float32 storage).
**Warning signs:** Verification passes on the desktop (CPU) but fails on the laptop (CUDA) for the same `--compute-type int8` request. `[CITED: github.com/SYSTRAN/faster-whisper/issues/440]`

### Pitfall 3: Silent float16→float32 fallback on low-compute-capability GPUs
**What goes wrong:** A `compute_type` request silently downgrades to `float32` and the int8 VRAM budget math is wrong.
**Why it happens:** CT2's quantization fallback table: on GPU Compute Capability ≤ 6.0, everything falls back to float32; on 6.2, int8 variants fall back to float32.
**How to avoid:** The RTX 2000 Ada laptop is CC 8.9 — NOT affected. But the verification (Pattern 2) catches it anyway: if `model.model.compute_type` reads `float32` when `int8_float16` was requested, fail loud. Also call `ctranslate2.get_supported_compute_types(device, 0)` at adapter init to log what the hardware supports.
**Warning signs:** `compute_type` reads `float32` after load; VRAM usage higher than the int8 benchmark (2926 MB). `[CITED: opennmt.net/CTranslate2/quantization.html]`

### Pitfall 4: `int8_float16` empty transcription on GTX 1650/1660 + old cuDNN
**What goes wrong:** The model runs but produces empty/garbage output (repeated "Compression ratio threshold is not met" / "No speech threshold is met").
**Why it happens:** A bug in older cuDNN libs on GTX 1650/1660 series GPUs with `int8_float16`.
**How to avoid:** The RTX 2000 Ada laptop is NOT affected (Ada + cuDNN 9 bundled in CT2 4.7.2). D-04's `--compute-type int8_float32` is the escape hatch if a future GPU hits it. Do NOT make `int8_float32` the default — it is slightly slower.
**Warning signs:** Empty segments on CUDA with `int8_float16`; switching to `int8_float32` fixes it. `[CITED: github.com/SYSTRAN/faster-whisper/issues/440]`

### Pitfall 5: Catching bare `RuntimeError` swallows non-OOM errors
**What goes wrong:** A flash-attention dtype error or cuBLAS version mismatch gets treated as OOM, the chunker halves forever, and the real error is hidden.
**Why it happens:** CT2 raises `RuntimeError` for many conditions, not just OOM.
**How to avoid:** Match `"out of memory"` (case-insensitive) in the message before treating as OOM; re-raise everything else (Pattern 3).
**Warning signs:** Chunk size dropping to the floor without a real OOM; the real exception type buried in a retry loop. `[CITED: github.com/OpenNMT/CTranslate2/issues/1682]`

### Pitfall 6: faster-whisper `Segment` is a dataclass, NOT a namedtuple
**What goes wrong:** Code doing `Segment._fields` or `segment._asdict()` (old API) breaks.
**Why it happens:** `Segment` was a namedtuple in older faster-whisper; in 1.2.1 it is a `@dataclass` with a deprecated `_asdict()` shim.
**How to avoid:** Access fields as attributes (`seg.start`, `seg.end`, `seg.text`, `seg.avg_logprob`); use `dataclasses.asdict(seg)` if you need a dict. `[VERIFIED: faster_whisper/transcribe.py line 48]`

### Pitfall 7: The segments generator is lazy — `transcribe()` returns an iterator
**What goes wrong:** `segments, info = model.transcribe(...)` returns immediately; nothing is transcribed until the generator is consumed. A test that asserts segment count right after the call sees nothing.
**How to avoid:** `segments = list(segments)` to materialize, or iterate to completion. The adapter should materialize inside `transcribe()` and return a `SttTranscription` with a concrete `list[TranscriptSegment]`. `[CITED: faster-whisper README]`

### Pitfall 8: `condition_on_previous_text=True` can cascade hallucinations on long audio
**What goes wrong:** On long files, a bad early segment conditions later segments into repeating garbage ("! ! ! ..." loops), which also spikes VRAM.
**How to avoid:** Consider `condition_on_previous_text=False` for the chunked path (each chunk is independent anyway after stitching). Worth a planner decision; the default `True` is fine for ≤30 min. The chunker's per-chunk calls reset conditioning naturally if you do not pass `initial_prompt` across chunks. `[CITED: faster-whisper issue #1221]`

### Pitfall 9: Python interpreter mismatch
**What goes wrong:** `pyproject.toml` says `requires-python = ">=3.11"` but the only interpreter on this machine is Python 3.12.5 (no `.venv`). The verified CT2 wheel tag is `cp312-cp312-win_amd64`.
**Why it happens:** The project never pinned a concrete interpreter / venv.
**How to avoid:** Confirm with the user whether the target is 3.11 or 3.12. CT2 publishes both `cp311` and `cp312` win_amd64 wheels, so either works; just be consistent. The pin (`faster-whisper==1.2.1`, `ctranslate2==4.7.2`) is interpreter-agnostic within 3.11/3.12. `[VERIFIED: pyproject.toml requires-python + `python --version` = 3.12.5]`

## Code Examples

### WhisperModel load + int8 verification (the core adapter operation)
```python
# Source: verified against faster_whisper 1.2.1 + ctranslate2 4.7.2 installed source
from faster_whisper import WhisperModel
import ctranslate2

# Log what the hardware actually supports (informs the verification)
supported = ctranslate2.get_supported_compute_types(device, 0)
self._log.info("CT2 supported compute_types on %s: %s", device, supported)

self._model = WhisperModel(
    model_path,                 # from ModelManager.ensure_downloaded (Phase 2)
    device=device,              # from device_for(backend, FASTER_WHISPER) — "cuda" or "cpu"
    compute_type=compute_type,  # int8_float16 (CUDA) / int8 (CPU) per D-04
)

# D-08 int8 verification — the ctranslate2.models.Whisper inside WhisperModel
actual = self._model.model.compute_type   # property, verified present
if actual not in _ACCEPTED[compute_type]:
    raise RuntimeError(
        f"int8 verification failed: requested={compute_type!r} loaded={actual!r} "
        f"supported={supported} (silent fallback — Phase 2 Pitfall 12 analogue)"
    )
```
`[VERIFIED: ctranslate2.models.Whisper.compute_type present + get_supported_compute_types('cpu',0) == {'int8','int8_float32','float32'}]`

### Transcribe + language detect (D-01, D-07)
```python
# Source: faster_whisper/transcribe.py transcribe() signature (verified)
# audio accepts a file path OR a numpy array — D-01
segments_iter, info = self._model.transcribe(
    audio,                  # str path | np.ndarray (16 kHz mono float32)
    language=language,      # None → auto-detect on first 30 s (D-07); "en" → force
    vad_filter=True,        # D-02
    # chunk_length left at default 30 (Pitfall: do NOT set a non-30 value)
)
segments = list(segments_iter)   # materialize the lazy generator (Pitfall 7)

# info.language, info.language_probability, info.duration (verified TranscriptionInfo fields)
# Segment fields (verified): start, end, text, avg_logprob, no_speech_prob, ...
transcript_segments = [
    TranscriptSegment(
        start_s=seg.start,
        end_s=seg.end,
        text=seg.text.strip(),
        confidence=math.exp(seg.avg_logprob),   # logprob → [0,1] probability
    )
    for seg in segments
]
```

### Standalone language detect on the first 30 s (chunked path, D-07)
```python
# Source: WhisperModel.detect_language signature (verified)
# audio_30s = the first 30 s of the decoded array (or a slice)
lang, prob, all_lang_probs = self._model.detect_language(
    audio_30s, vad_filter=True
)
# pass `lang` to every chunk's transcribe(language=lang) so the whole
# transcript is one language (D-07).
```

### CLI entry point (D-03)
```python
# pyproject.toml
[project.scripts]
transcribe = "app.cli.transcribe:main"
```
```python
# app/cli/transcribe.py — thin caller, NEVER imports faster_whisper (SC-4)
import argparse, sys
from pathlib import Path
from app.models.backend import device_for
from app.models.diagnostics import InferenceEngine, QualityPreset
from app.models.stt import FasterWhisperAdapter        # the factory lives in the stt package
from app.models.stt.chunker import transcribe_file
from app.models.transcript import Transcript
from app.settings.service import current
from app.storage.atomic import atomic_write_json

def main() -> int:
    p = argparse.ArgumentParser(prog="transcribe")
    p.add_argument("file")
    p.add_argument("--preset", choices=["small","balanced","large"], default="balanced")
    p.add_argument("--device", choices=["cuda","cpu","rocm"], default="auto")
    p.add_argument("--language", default=None)
    p.add_argument("--compute-type",
                   choices=["int8","int8_float16","float16","int8_float32"], default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    settings = current()
    device = (args.device if args.device != "auto"
              else device_for(settings.backend, InferenceEngine.FASTER_WHISPER))
    compute_type = args.compute_type or _default_compute_type(device)  # D-04
    out_path = Path(args.out) if args.out else Path(args.file).with_suffix(".transcript.json")

    transcript = transcribe_file(args.file, preset=args.preset, device=device,
                                 compute_type=compute_type, language=args.language)
    import asyncio
    asyncio.run(atomic_write_json(out_path, transcript.model_dump()))
    print(f"language={transcript.language} segments={len(transcript.segments)} "
          f"duration={...}s -> {out_path}")
    return 0
```
`[CITED: Python packaging console_scripts + argparse stdlib]` `[ASSUMED: exact asyncio/atomic_write_json wiring — atomic_write_json is async per Phase 1]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `int8` always meant `int8_float32` | `int8` resolves based on saved model dtype (float16-saved → `int8_float16` on CUDA) | CT2 v3.18.0 (2023) | The verification must accept equivalence, not literal match (Pitfall 2). `[CITED: issue #440]` |
| CT2 pip wheels CUDA 11 only | CT2 pip wheels CUDA 12.x (dynamic loading) | CT2 v4.0.0 | The win_amd64 wheel does not bundle cublas/cudart — Pitfall 1. `[CITED: issue #1250 + installation.html]` |
| `Segment` namedtuple | `Segment` dataclass | faster-whisper 1.x | Use attribute access / `dataclasses.asdict`; avoid `_fields` (Pitfall 6). `[VERIFIED]` |
| plain `WhisperModel.transcribe` | `BatchedInferencePipeline` drop-in for throughput | faster-whisper 1.x | Faster but MORE VRAM — out of scope for Phase 3's 8 GB laptop (Alternative table). |

**Deprecated/outdated:**
- `Segment._asdict()`: deprecated, use `dataclasses.asdict(Segment)`. `[VERIFIED: transcribe.py line 61]`
- CT2 CUDA 11 wheels: superseded by CUDA 12 wheels (v4.0.0+). `[CITED: installation.html]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `nvidia-cublas-cu12` + `nvidia-cuda-runtime-cu12` are the right pip packages to provide `cublas64_12.dll` / `cudart12.dll` on the laptop, and they are findable by CT2's dynamic loader. | Pitfall 1 / Open Q1 | If the laptop already has a system CUDA toolkit, these are unnecessary (harmless). If CT2 cannot find the pip-provided DLLs, the laptop silently falls back to CPU and SC-5's "runs on CUDA" half fails. Needs `checkpoint:human-verify`. |
| A2 | `ctranslate2==4.7.2` works equally well on the laptop (CUDA, cp311 or cp312) as it does on this desktop (CPU, cp312). | Standard Stack | The wheel is platform-tagged; a cp311 laptop would need the cp311 wheel (exists on PyPI). Low risk. |
| A3 | `argparse` is the right CLI choice (stdlib-first, D-17). | Standard Stack | Typer/click would be heavier; if the CLI grows complex in Phase 4 a migration is cheap. Low risk. |
| A4 | Pre-decoding the audio once and passing NumPy array slices to `transcribe()` is preferable to re-passing the file path per chunk. | Alternatives | Either works (transcribe accepts both). Pre-decode avoids repeated PyAV `gc.collect()`. Low risk. |
| A5 | `math.exp(seg.avg_logprob)` is an acceptable confidence proxy for `TranscriptSegment.confidence`. | Code Examples | avg_logprob is a log-probability; exp() maps it to [0,1]. The exact confidence semantics are not standardized; this is a reasonable proxy. Low risk. |
| A6 | The desktop this research ran on is the RX 6800 CPU-fallback box, and the laptop is a separate CUDA machine not inspected here. | Environment | If the laptop's CUDA toolkit / driver state differs, Pitfall 1's resolution changes. Needs `checkpoint:human-verify`. |

**If this table is empty:** N/A — six assumptions flagged. The two load-bearing ones (A1, A6) both reduce to: **the planner must add a `checkpoint:human-verify` task that confirms the laptop's CUDA runtime libs are findable by CT2 before declaring SC-5 done.**

## Open Questions

1. **CUDA runtime libs on the laptop (BLOCKER for SC-5's CUDA half)**
   - What we know: CT2 4.7.2 win_amd64 bundles cuDNN 9 but NOT cublas/cudart (dynamic loading). Phase 3 does NOT install torch.
   - What's unclear: does the laptop already have a system CUDA 12.x toolkit on PATH, or do we need `nvidia-cublas-cu12` + `nvidia-cuda-runtime-cu12` pip packages? If pip packages, are their DLLs findable by CT2's dynamic loader on Windows (PATH / copied next to ctranslate2.dll)?
   - Recommendation: planner adds a `checkpoint:human-verify` task BEFORE the SC-5 acceptance test — "on the laptop, run `python -c \"import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda',0))\"` and confirm `int8`/`int8_float16` are present (not just `float32`)". If they are missing, add the `nvidia-*-cu12` pip deps + a PATH-shim in the adapter. This is the single biggest threat to the silent-no-install laptop promise and to SC-5.

2. **Target Python interpreter (3.11 vs 3.12)**
   - What we know: `pyproject` says `>=3.11`; the only interpreter on this machine is 3.12.5; no `.venv`. CT2 has both cp311 and cp312 win_amd64 wheels.
   - What's unclear: which interpreter the laptop / desktop actually run the CLI with.
   - Recommendation: confirm with the user; pin a `.python-version` or document the venv in Wave 0. Either interpreter works with the recommended pins.

3. **`condition_on_previous_text` for the chunked path (Pitfall 8)**
   - What we know: default `True` can cascade hallucinations on long audio; the chunked path calls `transcribe()` per chunk so conditioning resets naturally if no `initial_prompt` is passed across chunks.
   - What's unclear: whether to set `condition_on_previous_text=False` explicitly for chunked calls, or pass the last chunk's final text as `initial_prompt` for continuity.
   - Recommendation: set `condition_on_previous_text=False` for chunked calls (each chunk is independent after stitching) — simpler + lower VRAM + avoids hallucination cascades. Leave `True` for the ≤30 min single-call path. Planner makes the call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | project | ✓ (3.12.5 on this box) | 3.12.5 | 3.11 also supported by CT2 wheels |
| `faster-whisper` | STT adapter | ✓ (installed, this box) | 1.2.1 | pin to 1.2.1 |
| `ctranslate2` | STT adapter | ✓ (installed, this box) | 4.7.2 | pin to 4.7.2 (4.8.0 latest, also compatible) |
| `av` (PyAV) | audio decode (D-01) | ✓ (transitive via faster-whisper) | — | none (D-01 locks it) |
| `numpy` | array handoff | ✓ (transitive) | — | — |
| `onnxruntime` | Silero VAD | ✓ (transitive via faster-whisper) | — | `vad_filter=False` (not recommended) |
| CUDA 12.x runtime libs (cublas, cudart) | CT2 on the LAPTOP | ✗ NOT bundled in CT2 wheel | — | `nvidia-cublas-cu12` + `nvidia-cuda-runtime-cu12` pip packages OR system CUDA toolkit (Q1) |
| cuDNN | CT2 (conv layers) | ✓ bundled in CT2 wheel | 9 (`cudnn64_9.dll`) | — |
| NVIDIA GPU driver | laptop CUDA | ✓ (assumed, laptop is the primary target) | — | CPU fallback (D-05) |
| `huggingface_hub` | model download (Phase 2 seam) | ✓ | >=0.25 | — |

**Missing dependencies with no fallback:**
- CUDA 12.x runtime libs on the laptop — if neither a system CUDA toolkit nor the `nvidia-*-cu12` pip packages are available, the laptop cannot run CUDA inference and SC-5's CUDA half fails. Resolution deferred to `checkpoint:human-verify` (Open Q1). The desktop (CPU fallback) is unaffected.

**Missing dependencies with fallback:**
- None on the desktop (CPU path needs only what faster-whisper/ctranslate2 bundle).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8 + pytest-asyncio (asyncio_mode=auto) + pytest-mock |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths=["tests"]) |
| Quick run command | `pytest tests/test_stt_*.py tests/test_chunker.py tests/test_cli_transcribe.py -x` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-05 | ≤30 min single transcribe; >30 min chunked + overlap + stitch | unit (fake adapter) | `pytest tests/test_chunker.py::test_short_audio_single_call -x` | ❌ Wave 0 |
| INGEST-05 | OOM → halve chunk → retry to floor | unit (fake adapter raising RuntimeError) | `pytest tests/test_chunker.py::test_oom_halve_and_retry -x` | ❌ Wave 0 |
| INGEST-05 | Stitch offsets timestamps; trims overlap to midpoint | unit (deterministic fake segments) | `pytest tests/test_chunker.py::test_stitch_offset_and_overlap_trim -x` | ❌ Wave 0 |
| INGEST-06 | `language=None` records detected language in Transcript | unit (fake adapter detect_language) | `pytest tests/test_stt_adapter.py::test_language_autodetect_recorded -x` | ❌ Wave 0 |
| INGEST-06 | `--language` forces + skips detect | unit + CLI smoke | `pytest tests/test_cli_transcribe.py::test_language_force_skips_detect -x` | ❌ Wave 0 |
| TRANS-01 | Segment.start/end/text map to TranscriptSegment; atomic write | unit | `pytest tests/test_stt_adapter.py::test_segment_mapping -x` | ❌ Wave 0 |
| SC-4 | `grep -rE "from faster_whisper\|import ctranslate2" app/` matches only `app/models/stt/adapter.py` | unit (boundary check test) | `pytest tests/test_stt_boundary.py::test_import_boundary -x` | ❌ Wave 0 |
| D-08 | int8 verification fails loud on silent float16 fallback | unit (mock compute_type property) | `pytest tests/test_stt_adapter.py::test_int8_verification_fails_loud -x` | ❌ Wave 0 |
| D-04 | compute_type default int8_float16 (CUDA) / int8 (CPU) | unit | `pytest tests/test_cli_transcribe.py::test_default_compute_type_per_device -x` | ❌ Wave 0 |
| SC-5 | CLI resolves device from settings.backend via device_for (no per-machine flags) | unit (mock settings) | `pytest tests/test_cli_transcribe.py::test_device_resolution_from_settings -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_stt_*.py tests/test_chunker.py tests/test_cli_transcribe.py -x` (fast, mocked adapter — no GPU, no model download)
- **Per wave merge:** `pytest` (full suite, ~188 existing tests + new)
- **Phase gate:** Full suite green before `/gsd-verify-work`; the SC-5 "runs on both machines" half is a `checkpoint:human-verify` (real CUDA laptop + real CPU desktop), not automatable in CI.

### Wave 0 Gaps
- [ ] `tests/test_stt_adapter.py` — mock `faster_whisper.WhisperModel` (mirror the `mock_hf_hub_download` pattern: patch the lazy import seam); covers REQ INGEST-06, TRANS-01, D-08
- [ ] `tests/test_chunker.py` — a `FakeAdapter` implementing `STTAdapter` Protocol that yields deterministic segments / raises `RuntimeError("...out of memory...")` on demand; covers REQ INGEST-05 (no real audio, no real GPU)
- [ ] `tests/test_cli_transcribe.py` — argparse + `monkeypatch` `current().backend` + `device_for`; covers SC-5, D-04
- [ ] `tests/test_stt_boundary.py` — grep the `app/` tree for forbidden imports (SC-4)
- [ ] `tests/conftest.py` additions: a `mock_stt_adapter` fixture (a `MagicMock` implementing the Protocol) + a `fake_audio_array` fixture (a small numpy array) — no framework install needed (pytest already present)
- [ ] A `FakeAdapter` in `tests/_stt_fake.py` (shared by chunker + CLI tests) implementing the Protocol with deterministic segment generation + OOM-on-demand

*(No framework install needed — pytest + pytest-asyncio + pytest-mock already in `dev` deps.)*

**Test-seam guidance (the key to testing without a GPU / model download):**
- Mock `faster_whisper.WhisperModel` at the lazy import point inside `adapter.py` (mirror the `mock_hf_hub_download` conftest pattern — patch the attribute on the real `faster_whisper` module after forcing its import, OR patch `sys.modules['faster_whisper']` with a `MagicMock` BEFORE the adapter imports it).
- The chunker + CLI tests use a `FakeAdapter` that implements the `STTAdapter` Protocol directly — they never touch faster-whisper. This is exactly why the Protocol exists (D-06): the chunker/CLI are testable without the package.
- The int8-verification test mocks the `model.model.compute_type` property to return `float32` and asserts a `RuntimeError` is raised.
- The boundary-check test runs the actual `grep -rE` command and asserts the only matching file is `app/models/stt/adapter.py`.

## Security Domain

> `security_enforcement` is not set in `.planning/config.json` (absent = enabled), but Phase 3 is a local-only CLI with no network surface beyond the Phase 2 huggingface_hub model download (already audited in Phase 2). No new attack surface is introduced. A lite ASVS pass:

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | local single-user, no auth (PROJECT.md) |
| V3 Session Management | no | CLI, no sessions |
| V4 Access Control | no | local file path arg; the CLI reads `<file>` and writes `<out>` — no privilege boundary |
| V5 Input Validation | yes | argparse validates `--preset`/`--device`/`--compute-type` choices; the `<file>` path must be validated (exists, is readable) before decode; `--out` path must be writable. `Path.is_absolute()` / `Path.exists()` checks. |
| V6 Cryptography | no | no crypto in Phase 3 |

### Known Threat Patterns for the STT CLI stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `<file>` / `--out` | Tampering | The CLI is local single-user; still, validate paths are within expected roots if a future Phase 4 job dir is introduced. For Phase 3, `Path.resolve()` + `exists()` checks suffice. |
| Malicious audio file triggering a PyAV/FFmpeg parser bug | Tampering | PyAV bundles a fixed FFmpeg build; `decode_audio` already wraps `av.error.InvalidDataError` and skips invalid frames. Input is user-supplied local files (trusted). |
| Model file tampering on disk | Tampering | Phase 2's SHA256 verify path (`ModelManager.verify`) — STT specs currently have `expected_sha256=None` (deferred); not a Phase 3 regression. |

## Sources

### Primary (HIGH confidence)
- `faster_whisper/audio.py` (installed v1.2.1) — PyAV decode, `decode_audio(input_file: str | BinaryIO)`, bundles FFmpeg, `audio=0` first stream, 16 kHz mono, `gc.collect()`. `[VERIFIED]`
- `faster_whisper/transcribe.py` (installed v1.2.1) — `WhisperModel.__init__` + `transcribe` signature (`audio: Union[str, BinaryIO, numpy.ndarray]`, `language`, `vad_filter`, `chunk_length`), `Segment` dataclass fields (start/end/text/avg_logprob/no_speech_prob), `TranscriptionInfo` (language/language_probability/duration), `detect_language` signature, `self.model = ctranslate2.models.Whisper(..., compute_type=...)`. `[VERIFIED]`
- `ctranslate2` 4.7.2 introspection — `ctranslate2.models.Whisper.compute_type` property present; `get_supported_compute_types('cpu',0) == {'int8','int8_float32','float32'}`; `faster-whisper 1.2.1 Requires-Dist: ctranslate2>=4.0,<5`; CT2 wheel RECORD bundles `cudnn64_9.dll` + `libiomp5md.dll` only (no cublas/cudart). `[VERIFIED]`
- `pip index versions` — faster-whisper latest 1.2.1; ctranslate2 latest 4.8.0 (4.7.2 pinned). `[VERIFIED]`
- Project codebase — `app/models/backend.py` (`device_for`), `app/models/transcript.py`, `app/models/manager.py` (`ensure_downloaded`/`load`), `app/models/registry.py`, `app/storage/atomic.py`, `app/settings/service.py` (`current()`), `app/models/diagnostics.py`, `tests/conftest.py`. `[VERIFIED]`

### Secondary (MEDIUM confidence)
- [opennmt.net/CTranslate2/quantization.html](https://opennmt.net/CTranslate2/quantization.html) — silent-fallback table by compute capability; int8 → float32 on CC ≤ 6.0. `[CITED]`
- [opennmt.net/CTranslate2/installation.html](https://opennmt.net/CTranslate2/installation.html) — CUDA 12.x requirement; dynamic loading; cuDNN for conv models. `[CITED]`
- [github.com/SYSTRAN/faster-whisper/issues/442](https://github.com/SYSTRAN/faster-whisper/issues/442) — `RuntimeError: CUDA failed with error out of memory` from `self.model.generate(...)`. `[CITED]`
- [github.com/SYSTRAN/faster-whisper/issues/440](https://github.com/SYSTRAN/faster-whisper/issues/440) — int8_float16 empty-transcription cuDNN bug, GTX 1650/1660 only; `int8_float32` workaround; int8→int8_float16 post CT2 v3.18. `[CITED]`
- [github.com/SYSTRAN/faster-whisper/issues/1086](https://github.com/SYSTRAN/faster-whisper/issues/1086) — torch↔CT2 version compatibility table (not binding in Phase 3 since no torch). `[CITED]`
- [github.com/OpenNMT/CTranslate2/issues/1084](https://github.com/OpenNMT/CTranslate2/issues/1084) — Windows `cublas64_12.dll not found` DLL-load failure. `[CITED]`
- [github.com/SYSTRAN/faster-whisper README](https://github.com/SYSTRAN/faster-whisper) — compute_type/VRAM benchmark (int8 2926 MB vs float16 4525 MB), VAD, BatchedInferencePipeline. `[CITED]`

### Tertiary (LOW confidence)
- `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` as the CUDA-runtime-lib source on the laptop — not verified this session (not installed on this desktop). `[ASSUMED]` → Open Q1 / `checkpoint:human-verify`.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — faster-whisper 1.2.1 + ctranslate2 4.7.2 verified installed + importing + API introspected on this machine; the only LOW item is the laptop CUDA-runtime-lib source (Q1).
- Architecture: HIGH — the adapter Protocol / chunker / CLI shape is grounded in the verified faster-whisper API + the existing Phase 1/2 seams read from the codebase.
- Pitfalls: HIGH — every pitfall is sourced from an upstream issue, the CT2 docs, or the installed source; Pitfall 1 (CUDA libs) is the one with an unresolved resolution path (Q1).
- int8 verification (D-08): HIGH — `model.model.compute_type` property + `get_supported_compute_types` verified present; the equivalence rule is sourced from issue #440 + the quantization docs + the verified CPU supported-types set.

**Research date:** 2026-06-19
**Valid until:** 2026-07-19 (30 days — stable stack; faster-whisper/CT2 release cadence is slow)