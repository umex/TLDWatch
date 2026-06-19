# Phase 3: STT Adapter + Audio Chunker + Standalone CLI - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning
**Source:** /gsd-discuss-phase 3 (interactive, default mode). User deferred all four gray areas to Claude's Discretion ("I am not familiar with these things. I will leave that up to you. Maybe you can discuss it with some other agent like codex or gemini if you are not sure. They should be added as reviewers."). Technical facts were grounded against faster-whisper's source/issues/benchmarks via web search before deciding; cross-AI reviewers (codex, gemini) were wired into config to review the plans downstream.

<domain>
## Phase Boundary

A runnable STT pipeline that takes an audio or video file, transcribes it with faster-whisper, handles long audio via chunking with OOM fallback, auto-detects the spoken language, and proves the GPU abstraction works end-to-end through a standalone CLI. Phase 3 is the first phase that actually runs a model for inference (Phase 2 shipped the lifecycle; Phase 3 runs the STT model through it).

In scope (ROADMAP success criteria SC-1..SC-5, requirements INGEST-05, INGEST-06, TRANS-01):
- A `STTAdapter` Protocol — the orchestrator/CLI call the adapter; **nothing outside `app/models/stt` may import `faster-whisper` or `ctranslate2` directly** (SC-4, mirrors Phase 2's `huggingface_hub` boundary check)
- faster-whisper large-v3 int8 adapter, version-pinned, with int8 verification (the loaded model actually runs the chosen compute_type, not a silent float16 fallback)
- Audio chunker: >30 min → windowed chunks with overlap → transcribe each → stitch into one continuous transcript; per-chunk OOM → halve chunk size and retry (SC-2, INGEST-05)
- Language auto-detect from the first 30 s, recorded in `transcript.json` (SC-3, INGEST-06); `--language` force override
- Standalone CLI: file path in → `transcript.json` out, runs on the laptop (CUDA) and the desktop (CPU fallback) with no code changes (SC-1, SC-5)
- Writes `transcript.json` (the existing `Transcript`/`TranscriptSegment` schema) via the Phase 1 atomic-write helper

Out of scope for Phase 3: the job orchestrator/queue/WebSocket (Phase 4 — the CLI is a standalone proof, NOT a job in the queue), local-file upload UI / drag-and-drop (Phase 5), YouTube ingest / yt-dlp (Phase 6), diarization / pyannote (Phase 7), LLM summarization (Phase 8), the settings panel UI (Phase 10). The CLI does not create a `data/jobs/<id>/` job dir — that wiring is Phase 4; Phase 3 writes `transcript.json` to a path.

</domain>

<decisions>
## Implementation Decisions

### Audio decode path
- **D-01:** Use **faster-whisper's built-in PyAV decoder** — pass the file path directly to `transcribe()`; do NOT shell out to a system `ffmpeg` and do NOT add `pydub`/`librosa`. faster-whisper's `decode_audio()` (`faster_whisper/audio.py`) opens the container with PyAV (which **bundles the FFmpeg libraries inside the Python wheel — no system-level FFmpeg install required**), decodes the first audio stream, and resamples to 16 kHz mono float32. **Video containers (MP4/MKV/WebM) work natively** — PyAV decodes the audio stream and ignores the video track, so the CLI's "video file path in" contract is satisfied with zero extra code. `transcribe()` also accepts a raw NumPy array, so the chunker can hand it pre-decoded audio when needed. *(Claude's Discretion — user deferred.)*
  - **Rationale:** A system `ffmpeg` install would violate the laptop's silent-no-install first-run promise (PROJECT.md constraint) and add a Windows PATH burden; the `ffmpeg`-CLI path is ~10–20% faster but decoding is only ~5–10% of total runtime (inference dominates), so the PyAV `gc.collect()` overhead is negligible. PyAV arrives transitively with `faster-whisper` — no new top-level dependency to manage. The `ffmpeg`-CLI fast path is noted as a future optimization, NOT Phase 3.

### Chunking strategy
- **D-02:** Build a **coarse windowed chunker ON TOP of faster-whisper's internal 30 s sliding-window segmentation** — do NOT replace faster-whisper's internal handling and do NOT skip the chunker. faster-whisper already transcribes long files internally (30 s sliding window + timestamp tokens + optional Silero VAD); our chunker is the **VRAM-ceiling safety valve + the deterministic retry knob** that SC-2/INGEST-05 mandate. *(Claude's Discretion — user deferred.)*
  - **Trigger:** ≤30 min → a single `transcribe()` call (no chunking). **>30 min → chunked** (SC-2's ">30 min" threshold).
  - **Chunking:** split the decoded audio into ~15-min windows with ~30 s overlap; transcribe each window via the adapter; **stitch** by offsetting each chunk's segment `start_s`/`end_s` by the chunk's start offset and trimming the overlap region to its midpoint (no duplicated text, continuous timestamps).
  - **OOM halve-and-retry:** catch the CTranslate2/cuda OOM exception per chunk; halve that chunk's size and retry it, down to a floor (e.g. 1 min). This composes cleanly with faster-whisper's internal 30 s window — each chunk is just shorter audio handed to `transcribe()`.
  - **VAD:** `vad_filter=True` to drop silence and reduce processed audio (lower VRAM, fewer garbage segments).
  - **Rationale:** SC-2 + INGEST-05 lock "chunks with overlap, transcribed, stitched, OOM → halve and retry" as a success criterion — it is not optional. faster-whisper's internal windowing handles inference-within-a-chunk; the chunker handles whole-file VRAM safety and gives the retry mechanism the success criterion requires. Manual non-30 s `chunk_length` tuning against faster-whisper's feature extractor is explicitly avoided (it causes shape errors per the upstream issues).

### CLI shape & output
- **D-03:** Ship a **`console_scripts` entry point named `transcribe`** in `pyproject.toml` (`[project.scripts]`), backed by `app/cli/transcribe.py` (or `app/cli.py`). *(Claude's Discretion — user deferred.)*
  - **Args:** positional `<file>`; `--preset {small,balanced,large}` (default `balanced`); `--device {cuda,cpu,rocm}` (default: auto — read persisted `settings.backend` and resolve via `device_for(backend, InferenceEngine.FASTER_WHISPER)`); `--language <code>` (force; default auto-detect from first 30 s per SC-3); `--compute-type {int8,int8_float16,float16,int8_float32}` (override the backend default from D-04); `--out <path>` (default `<input>.transcript.json`); `--verbose`.
  - **Output:** writes the `Transcript` JSON via the Phase 1 atomic-write helper to `--out`; prints a one-line summary to stdout (detected language, segment count, total duration). **Does NOT create a `data/jobs/<id>/` job dir** — the job system is Phase 4; the CLI is a standalone proof.
  - **Protocol seam:** the CLI is a **thin caller of `STTAdapter`** — it never imports `faster-whisper`/`ctranslate2` directly (SC-4). This is the end-to-end proof that the GPU abstraction works: the same CLI runs on the laptop (CUDA) and the desktop (CPU fallback) with no code changes (SC-5) because device resolution goes through `device_for`.
  - **Rationale:** SC-1 demands a "standalone CLI" — a `console_scripts` entry point is the most runnable form (available after `pip install -e .`, which is already the project's install step). A `python -m app.cli ...` form would also work and may be kept as an alias, but the entry point is the headline. Decoupling from the job dir keeps Phase 3 honest about its scope.

### Compute type per backend
- **D-04:** Default `compute_type` = **`int8_float16` on CUDA**, **`int8` on CPU** (and on ROCm, since CTranslate2 has no ROCm backend — the ROCm branch routes through the CPU path). Expose `--compute-type` to override. *(Claude's Discretion — user deferred; grounded in the upstream benchmark.)*
  - **Rationale (grounded):** faster-whisper's own benchmark (RTX 3070 Ti 8 GB, large-v2): `int8` = **2926 MB** VRAM vs `float16` = 4525 MB (~35% less), with <0.1% WER difference and near-equivalent speed. Real-world large-v3 + `int8_float16` on CUDA reports ~2 GB VRAM constant and ~11× realtime. `int8_float16` is the documented recommendation for CUDA with ≤8 GB VRAM — it fits the 8 GB RTX 2000 Ada laptop with large headroom. `int8` is the documented best choice for CPU (matches the 02-03 spike's CPU `compute_type='int8'` verdict).
  - **Fallback:** if `int8_float16` produces empty/garbage transcriptions on a specific GPU (a known cuDNN bug on some older cards, upstream issue #440), the user can pass `--compute-type int8_float32` (more stable, slightly slower). This is the escape hatch, not the default.

### GPU path (locked this session — supersedes 02-03-SPIKE §5 #5)
- **D-05:** **CUDA laptop is the primary target; the desktop's CPU fallback is acceptable and NOT a blocker.** Keep the device pluggable — the adapter accepts `device: Literal['cuda','cpu','rocm']` and resolves through `device_for`, so a future successful TheRock ROCm install flips the desktop to GPU with no adapter rewrite. **Phase 3 does NOT schedule or wait on a ROCm re-spike**; the 02-03 spike's "schedule a re-spike before treating ROCm unavailable" is superseded by the user's 2026-06-19 decision that RX 6800 ROCm is best-effort and must not block the roadmap. The RX 6800 is RDNA2 / non-CUDA-capable; CTranslate2 (faster-whisper) has no ROCm/DirectML/Vulkan path, so STT on the desktop stays CPU until a whisper.cpp HIP adapter is added (a future, separate decision — not Phase 3).

### STTAdapter Protocol & boundary
- **D-06:** Define a `STTAdapter` Protocol (`transcribe(audio_or_path, language=None, ...) -> Transcript`-shaped result) in `app/models/stt`. **`faster-whisper` and `ctranslate2` are imported ONLY inside `app/models/stt`** — the CLI, the chunker, and (later) the Phase 4 orchestrator depend on the Protocol, never the package. Boundary check: `grep -rE 'from faster_whisper|import faster_whisper|import ctranslate2' app/` matches only `app/models/stt`. This mirrors Phase 2's `huggingface_hub` boundary (manager.py + hf_token.py) and satisfies SC-4. Device resolution goes through `device_for(backend, InferenceEngine.FASTER_WHISPER)` (the seam Phase 2 already shipped in `app/models/backend.py`).

### Language auto-detect
- **D-07:** Use **faster-whisper's native language detection** — when `language=None`, faster-whisper auto-detects from the audio (it detects on the first segment by default); record the detected language in `Transcript.language`. The `--language` CLI flag forces a language and skips detect. For the chunked path, detect on the first 30 s (SC-3's "first 30 s" wording) and pass the detected language to every chunk so the whole transcript is one language. *(Claude's Discretion — user deferred; faster-whisper's native detect is the obvious, no-extra-dep choice.)*

### Version pin & int8 verification (plan 03-01)
- **D-08:** Pin `faster-whisper` and `ctranslate2` to mutually-compatible versions in `pyproject.toml` (the researcher/planner determines the exact pins; the constraint is CT2 version ↔ faster-whisper version ↔ int8 support compatibility). **int8 verification** = a check that the loaded model actually runs the chosen `compute_type` (query the model's compute type after load; fail loud if it silently fell back to float16) — this is the "settings says CUDA/int8 but jobs run float16" analogue of Phase 2's Pitfall 12. *(Claude's Discretion — user deferred.)*

### Cross-AI review (user-requested)
- **D-09:** The user explicitly asked that other AIs (codex, gemini) review the work. `review.default_reviewers` is now `["codex","gemini"]` in the GSD config (codex was already a default; gemini was added 2026-06-19). **Downstream instruction:** run a cross-AI review pass on the Phase 3 plans after `/gsd-plan-phase 3` (and on the implementation after execution) — e.g. `/gsd-review` with the configured defaults or `--all` — so codex + gemini weigh in on the STT adapter + chunker design before/after it ships. They fire when those runtimes are installed and detected on the machine; if only one is present, that one reviews. This is a standing preference for the rest of the project, not just Phase 3.

### Carried forward from earlier phases (locked — not re-asked)
- **Phase 1 D-04:** atomic writes (`<name>.tmp` → fsync → `os.replace`) — `transcript.json` writes inherit this via `app/storage/atomic.py`.
- **Phase 1 D-11/D-12:** `transcript.json` is the file-as-truth stage output; `current_stage='transcribed'` ↔ `transcript.json` exists.
- **Phase 1 D-15:** `Transcript`/`TranscriptSegment` are lax-for-output/internal-storage (deserialising existing files must not fail on a future field); new fields added later must be optional.
- **Phase 2:** STT model = `Systran/faster-whisper-large-v3` (BALANCED), loaded via `ModelManager.load(ModelCategory.STT)`; the `device_for(backend, InferenceEngine.FASTER_WHISPER)` seam in `app/models/backend.py` resolves the device; the on-demand download path (02-04, `asyncio.to_thread` offload + classic non-Xet resume) is what pulls the model the first time the CLI/adapter needs it.
- **02-03-SPIKE:** desktop = CPU fallback (`device='cpu'`, `compute_type='int8'`); RX 6800 is RDNA2 / non-CUDA; CTranslate2 has no ROCm path. (The spike's "schedule a re-spike" clause is superseded by D-05.)

### Claude's Discretion
All four gray areas (D-01 decode, D-02 chunking, D-03 CLI, D-04 compute type) plus D-07 (language detect) and D-08 (pin/verify) were deferred by the user and assigned to Claude with a recorded rationale each. D-05 (GPU path) was a user decision this session. D-09 (cross-AI reviewers) was a user request.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher/planner/executor) MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — hardware constraints (8 GB laptop VRAM budget = the constraint; RTX 2000 Ada CUDA laptop is the primary target; RX 6800 XT desktop is the headroom/secondary box), silent-no-install first-run promise (drives D-01: no system ffmpeg), no-telemetry, single-user no-auth, back-end is the only thing that touches models + filesystem
- `.planning/REQUIREMENTS.md` — Phase 3 owns `INGEST-05` (long-video chunking + OOM fallback), `INGEST-06` (language auto-detect), `TRANS-01` (timestamped transcript). Traceability table lines 132–140.
- `.planning/ROADMAP.md` — Phase 3 goal, mode (mvp), success criteria SC-1..SC-5, plans 03-01/03-02/03-03
- `.planning/STATE.md` — "Blockers/Concerns": Phase 3 faster-whisper + int8 version pins, VRAM profile on 8 GB laptop (D-04 answers this with int8_float16)

### Prior phase context
- `.planning/phases/02-gpu-backend-detection-model-manager/02-CONTEXT.md` — D-02 (just-in-time download at stage start), D-03 (explicit unload), the model manager load path, the device seam
- `.planning/phases/02-gpu-backend-detection-model-manager/02-03-SPIKE.md` — ROCM_FALLBACK_TO_CPU verdict; desktop CPU STT (`device='cpu'`, `compute_type='int8'`); RDNA2 non-CUDA; CTranslate2 has no ROCm path. §5 "What Phase 3 must do" — **read items 1–4 and 6 as locked; item 5 (schedule a re-spike) is superseded by D-05.**
- `.planning/phases/01-back-end-skeleton-storage-data-layout/01-CONTEXT.md` — D-04 atomic writes, D-11/D-12 file-as-truth + transcript.json stage mapping, D-15 lax-output models

### Existing code (the seams Phase 3 plugs into)
- `app/models/transcript.py` — `Transcript` / `TranscriptSegment` (the output schema the adapter writes)
- `app/models/backend.py` — `device_for(backend, InferenceEngine)` (the device-resolution seam; `InferenceEngine.FASTER_WHISPER` → `"cuda"` on CUDA/CPU, `-1`-style for llama-cpp is a different engine)
- `app/models/manager.py` — `ModelManager.load(ModelCategory.STT)` + `ensure_downloaded` (the on-demand, thread-offloaded, classic-resume download path)
- `app/models/registry.py` — `balanced.stt` / `small.stt` / `large.stt` specs (`Systran/faster-whisper-large-v3` / `faster-whisper-small`)
- `app/models/diagnostics.py` — `InferenceEngine`, `ModelCategory`, `GpuBackend` enums
- `app/storage/atomic.py` — the atomic-write helper for `transcript.json`
- `pyproject.toml` — the dependency policy (faster-whisper/ctranslate2/torch are deliberately absent and "arrive in their own phases (3, 8, 7)"; Phase 3 adds faster-whisper + pins)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/models/transcript.py` — `Transcript`/`TranscriptSegment` already exist with the exact fields STT needs (`start_s`, `end_s`, `text`, `speaker=None`, `confidence=None`); the adapter populates `start_s`/`end_s`/`text`/`confidence` and leaves `speaker=None` for Phase 7 diarization.
- `app/models/backend.py` `device_for(backend, InferenceEngine.FASTER_WHISPER)` — returns `"cuda"` for CUDA/ROCm (HIP via torch.cuda) and `"cpu"` for CPU. The adapter calls this instead of hardcoding a device.
- `app/models/manager.py` — `get_manager()` / `configure_manager()` + `load(ModelCategory.STT)` + `ensure_downloaded`. The CLI/adapter loads the STT model through this; the 02-04 thread-offloaded download path means the first run pulls the model without freezing anything.
- `app/storage/atomic.py` — `transcript.json` writes go through this (Phase 1 D-04).
- `tests/conftest.py` — `tmp_data_dir` + `app_under_test` + mocked-seams pattern; Phase 3 STT tests mock `faster_whisper.WhisperModel` (no real GPU / no real model download in CI).

### Established Patterns
- **Package boundary check** (Phase 2): `grep -rE 'from faster_whisper|import ctranslate2' app/` must match only `app/models/stt`. Mirrors the `huggingface_hub` boundary (manager.py + hf_token.py only).
- **Lazy in-body imports** (Phase 2): `faster_whisper` / `ctranslate2` / `torch` are imported inside function bodies, not at module top, so a CPU-only test env does not crash on import.
- **Atomic writes** (Phase 1 D-04): every on-disk mutation, including `transcript.json`.
- **Lax output models** (Phase 1 D-15): `Transcript` deserialisation stays lax so a future field doesn't break a stale reader.

### Integration Points
- New modules Phase 3 CREATES: `app/models/stt/__init__.py` (or `app/models/stt.py`) — `STTAdapter` Protocol + the faster-whisper implementation + `transcribe()`; `app/models/stt/chunker.py` (or `app/stt/chunker.py`) — the windowed chunker + OOM halve-and-retry + stitch; `app/cli/transcribe.py` — the CLI entry point. `pyproject.toml` gains `faster-whisper` + `ctranslate2` pins and a `[project.scripts]` `transcribe` entry.
- Downstream: Phase 4 orchestrator calls `STTAdapter` (never faster-whisper) as the `transcribing` stage; Phase 7 diarization reads `transcript.json` and fills `speaker`; Phase 5/6 UI renders the segments.

</code_context>

<specifics>
## Specific Ideas

- **Laptop silence is non-negotiable** (PROJECT.md, carried from Phase 2): the CLI on the RTX 2000 Ada must not require any system dependency install (no system ffmpeg) — D-01 PyAV-in-the-wheel is the direct consequence.
- **The CLI is the GPU-abstraction proof** (SC-5): the same `transcribe <file>` command works on the laptop (CUDA, int8_float16) and the desktop (CPU fallback, int8) with no code changes and no per-machine flags, because device + compute_type resolve from the persisted `settings.backend` via `device_for`. This is the end-to-end demonstration that Phase 2's backend abstraction actually carries through to inference.
- **User is non-technical on the ML specifics** and explicitly invited cross-AI review (D-09): codex + gemini are configured as default reviewers and should be run on the Phase 3 plans + implementation. Do not treat Claude's D-01..D-08 as above review — they are the starting position the reviewers should pressure-test.
- **int8 is the load-bearing OOM defense** (grounded): `int8_float16` on CUDA + the chunker's halve-and-retry are a two-layer OOM strategy. The chunker exists because SC-2 mandates it, but the compute_type is what actually keeps a 2–3 hour video from OOMing on 8 GB in the first place.

</specifics>

<deferred>
## Deferred Ideas

- **`ffmpeg`-CLI decode fast path** — ~10–20% faster decode than PyAV but requires a system ffmpeg install; violates the silent-no-install laptop constraint. Future optimization only if decode ever shows up in profiling (it is ~5–10% of runtime today).
- **whisper.cpp HIP adapter for the RX 6800** — the only way STT leaves CPU on the desktop (CTranslate2 has no ROCm path). A future, separate decision; NOT Phase 3. The device seam (D-06) keeps this flip possible without an adapter rewrite.
- **ROCm re-spike (TheRock dated-alpha wheel, Python 3.11 venv)** — superseded by D-05; the user does not want it to block the roadmap. Re-open only if the user explicitly wants to invest in the desktop GPU path.
- **Prefetch the STT model at job-submit** — Phase 4 follow-up (carried from Phase 2 D-02); Phase 3's CLI loads just-in-time like everything else.
- **Streaming/real-time transcription** — explicitly out of scope (PROJECT.md); input is always a finished file.
- **Per-chunk progress broadcast over WebSocket** — Phase 4 (WebSocket progress); the Phase 3 CLI prints a stdout summary only.

</deferred>

---

*Phase: 3-STT Adapter + Audio Chunker + Standalone CLI*
*Context gathered: 2026-06-19 via /gsd-discuss-phase (interactive, default mode; all gray areas deferred to Claude's Discretion, grounded via web search; cross-AI reviewers codex+gemini wired in per user request)*