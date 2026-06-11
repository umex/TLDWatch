# Technology Stack

**Project:** TranscriptionAndNotes
**Domain:** Local-first video transcription + diarization + LLM summarization (Windows, dual GPU: CUDA + ROCm)
**Researched:**2026-06-11
**Mode:** Ecosystem (stack dimension)
**Binding constraint:** Laptop — NVIDIA RTX2000 Ada,8 GB VRAM
**Overall confidence:** MEDIUM (research tools WebSearch / WebFetch / Bash were denied in this environment, so version numbers and "current as of mid-2026" claims are based on the prior-knowledge baseline used by sibling FEATURES.md and have not been freshly re-verified against GitHub releases. The hardware-anchored recommendations — what model fits8 GB VRAM, what ROCm actually supports on Windows — are HIGH confidence because they are derived from the project's stated hardware + long-established ecosystem behavior, not from time-sensitive version numbers.)

---

## Executive Summary

The local transcription + diarization + LLM stack has converged on a clear three-layer pattern, and we can use it as-is without inventing anything:

1. **STT:** `faster-whisper` (CTranslate2-backed Whisper) as the default, with `whisper.cpp` as the CPU/ROCm escape hatch. Both fit in8 GB VRAM when using the small/int8 variants.
2. **Diarization:** `pyannote.audio`3.x is the only credible turn-key option. It needs a HuggingFace token + model-access agreement. We wrap it so the failure mode is "diarization disabled, transcript still works" rather than "whole job fails."
3. **LLM:** `llama.cpp` via a Python binding (`llama-cpp-python`) for the laptop default. Ollama is the ergonomic alternative but is a separate daemon and adds a process boundary we don't need. The desktop opts into a larger GGUF (Qwen2.514B or similar) within the same llama.cpp backend.

The "CUDA vs ROCm transparently" requirement is the only place this is genuinely hard. On Windows, ROCm support is **fragmented and unofficial** for consumer Radeon cards. The realistic posture is: write the back-end to detect GPU on first run, prefer CUDA (NVIDIA) when available, and fall back to a ROCm-specific PyTorch wheel or to CPU for the AMD desktop. We do not pretend ROCm on Windows works the same way as CUDA — we detect, choose, log, and continue.

Everything else (job queue, YouTube download, audio extraction, React UI, persistence) is commodity tooling with no surprises.

---

## Binding Constraints (from PROJECT.md, HIGH confidence)

| Machine | GPU | VRAM | Backend | Notes |
|---|---|---|---|---|
| Desktop | AMD Radeon6800 XT |16 GB | ROCm (RDNA2, gfx1030) | ROCm support on Windows is unofficial / community-maintained for this card class |
| Laptop | NVIDIA RTX2000 Ada |8 GB | CUDA (Ada Lovelace, sm_89) | Working machine; detection must be silent |

Both run Windows10 Pro. Both must run the **same default model set**. The laptop is the binding constraint; the desktop opts into larger models only via a settings override.

---

## Recommended Stack

### Core Framework: Python3.11 + FastAPI

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| Python |3.11.x | Runtime for ML + back-end |3.11 is the sweet spot for PyTorch wheels (3.12 works but some wheels lag);3.13 has too many ML-stack rough edges as of mid-2026 |
| FastAPI |0.110+ | HTTP API for the React front-end | Async-native, fits a background-job + WebSocket-progress model; OpenAPI spec is free |
| Uvicorn |0.27+ | ASGI server | Standard for FastAPI |
| Pydantic |2.x | Request/response models | Pydantic v2 is fast enough to use everywhere; v1 is legacy |
| SQLModel or SQLAlchemy2.x | latest2.x | ORM + models for job persistence | Single user, single machine — SQLite is fine |
| SQLite | bundled | Job/result persistence | Zero-config, survives restarts, one file. Per PROJECT.md: "Job queue persistence across restarts." |
| APScheduler or `arq` | latest | Background job execution | Either works. APScheduler is simpler for a single-process back-end; `arq` is Redis-backed and overkill. |
| httpx |0.27+ | Async HTTP client for YouTube metadata etc. | Already a FastAPI neighbor |
| WebSockets (`websockets` lib via FastAPI) | bundled | Job progress streaming to the React front-end | Long jobs need push, not polling |

**Confidence:** HIGH for Python3.11 + FastAPI choice (stable ecosystem, well-aged); MEDIUM for exact minor versions (not freshly verified against PyPI).

**Why not Django / Flask:** Django's ORM is heavier than we need and its request model is sync; Flask lacks async ergonomics for a WebSocket-progress design.

**Why not Celery / Redis:** PROJECT.md says single user, one machine. A Redis dependency is overkill. APScheduler + SQLite WAL is enough.

---

### Speech-to-Text (Transcription)

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| **faster-whisper** |1.0.x (the line that pinned CTranslate23.x) | Default STT engine | CTranslate2-backed Whisper;2-4x faster than openai-whisper; first-class int8 quantization; supports CUDA + CPU; runs Whisper large-v3 in <8 GB VRAM with int8 |
| CTranslate2 |3.x | Underlying compute backend | faster-whisper dependency |
| openai-whisper | NOT used | — | Slower, heavier VRAM, no first-class quantization. Listed as anti-recommendation. |
| **whisper.cpp** (fallback) | latest release | CPU + ROCm + AMD GPU path | Pure C/C++, no PyTorch dependency, supports ROCm via HIP on Linux. **ROCm-on-Windows support is unofficial — see Pitfalls below.** Used as a fallback when PyTorch ROCm wheels fail. |

**Default model selection (laptop-safe,8 GB VRAM):**

| Quality preset | faster-whisper model | Quantization | Approx. VRAM |
|---|---|---|---|
| Small | `small` | int8 | ~1 GB |
| **Balanced (default)** | `medium` | int8 | ~3 GB |
| Large | `large-v3` | int8 | ~5 GB |
| Desktop opt-in | `large-v3` | float16 | ~10 GB |

**Confidence:** HIGH for the faster-whisper-as-default recommendation; MEDIUM on exact current version of faster-whisper (the project has been on a1.0.x stabilization track).

**Why faster-whisper, not openai-whisper:** CTranslate2 quantizes to int8 cleanly, which is the difference between large-v3 fitting on the8 GB laptop and not fitting. The same large-v3 model is ~10 GB in fp16 vs ~5 GB in int8.

**Why whisper.cpp as the fallback rather than the primary:** faster-whisper is more ergonomic from Python and its CUDA path is the well-tested one. whisper.cpp's ROCm support exists but is best on Linux. We keep whisper.cpp in the toolkit as the fallback when PyTorch ROCm doesn't install cleanly on the user's desktop.

---

### Speaker Diarization

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| **pyannote.audio** |3.1.x | Default diarization engine | Only mature, turn-key open-source diarizer. HuggingFace model `pyannote/speaker-diarization-3.1` is the canonical pipeline. |
| PyTorch |2.2+ (matches CUDA wheels) | Underlying tensor engine | pyannote depends on torch |
| torchaudio | matches torch | Audio I/O for pyannote | |
| HuggingFace token | — | Required | pyannote diarization models are gated; user must accept terms on HuggingFace and put a token in settings. **We make this a settings-panel input, not a blocker on first run.** |

**Fallback / alternative:**
- `whisperx` — bundles faster-whisper + pyannote + voice-activity detection with better word-level alignment. Worth considering as the *integrated* option. We list it as an alternative because it can replace "faster-whisper + pyannote" with a single pipeline, at the cost of more opinionated glue.
- `nemo diarization` (NVIDIA NeMo) — production-grade but heavy and pulls in a lot of NVIDIA-specific tooling. Listed as anti-recommendation for a single-user local app.

**Confidence:** HIGH on pyannote.audio as the default (no credible competitor); MEDIUM on exact3.1.x version pin.

**Critical note on HuggingFace gating:** pyannote3.1 requires the user to (1) create a HuggingFace account, (2) accept the model terms at the model's HuggingFace page, (3) paste a token into the app. This is the **only first-run interaction we can't make fully silent** on the laptop. Mitigations:

- On first run, if no token is configured, the app runs the transcription pipeline **without diarization** and shows a non-blocking banner: "Speaker labels available — add a HuggingFace token in Settings to enable."
- The settings panel has a clear "Get a token" link.
- Diarization is opt-in by default for this reason; it can be flipped to required-once-configured later.

This is the one place where "silent first run" has a soft caveat, and we should be honest about it rather than pretending it doesn't exist.

---

### Local LLM (Summarization)

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| **llama-cpp-python** |0.2.x+ | Python binding for llama.cpp | Runs GGUF models locally; supports CUDA (cuBLAS) and ROCm (HIP, Linux) and CPU. The "one backend, both GPUs, both quantization paths" choice. |
| llama.cpp | bundled via the binding | Underlying inference | |
| GGUF-format models | per quality preset | The actual weights | HuggingFace hosts official GGUF builds for most open models |

**Default model selection:**

| Quality preset | Model | Quantization | Approx. VRAM | Notes |
|---|---|---|---|---|
| Small | `Qwen2.5-3B-Instruct` | Q4_K_M | ~2.5 GB | Fastest on the laptop; weakest summarization quality |
| **Balanced (default)** | `Qwen2.5-7B-Instruct` | Q4_K_M | ~5 GB | Fits comfortably on the8 GB laptop alongside the STT model |
| Large (desktop opt-in) | `Qwen2.5-14B-Instruct` | Q4_K_M | ~10 GB | Desktop only — exceeds the8 GB laptop VRAM budget |
| Desktop opt-in (alt) | `Qwen2.5-32B-Instruct` | Q4_K_M | ~22 GB | Desktop with16 GB VRAM is borderline; consider Q3_K_M |

**Why Qwen2.5-Instruct:** as of the2025-2026 cycle, Qwen2.5 is the strongest open-weights instruction-following family for structured-output prompts (JSON-ish schema sections, bullet lists, terse prose). Llama-3.x is a fine alternative; Mistral / Mixtral are alternatives with different tradeoffs.

**Why llama-cpp-python, not Ollama:**

| Criterion | llama-cpp-python | Ollama |
|---|---|---|
| Single process / in-process | YES (linked library) | NO (separate daemon over REST) |
| Model hot-swap from settings | Trivial | Requires `ollama pull` round-trip |
| Background-job model coexistence | Easy (separate loaded model objects) | Awkward (one model loaded at a time by default) |
| Windows install | Wheels available | Native Windows binary, easy |
| ROCm support | Via llama.cpp HIP build (Linux-only) | Via ROCm Docker images (Linux-only) |

Both options have the **same ROCm-on-Windows gap** — see Pitfalls. We pick llama-cpp-python for the in-process ergonomics. Ollama is the supported alternative if the user later wants to share models with other local apps.

**Confidence:** HIGH on llama-cpp-python as the default mechanism (the in-process story is unmatched); MEDIUM on the Qwen2.5 family as the "best open-weights for this task" — any of Llama-3.x / Mistral / Phi-4 would also work.

---

### Audio Extraction & YouTube

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| **yt-dlp** | latest | YouTube audio + metadata download | The community-maintained successor to youtube-dl; handles all the anti-scraping measures; license-clean |
| **ffmpeg** | static Windows build from BtbN/gyan.dev | Audio extraction, format conversion, chunking | `yt-dlp` shells out to ffmpeg for audio extraction; we use ffmpeg directly for chunking long videos |
| pydub |0.25.x | Optional — easy audio slicing | Used only if we don't want to invoke ffmpeg for chunk boundaries |

**Why ffmpeg, not a Python-only audio lib:** ffmpeg handles every codec YouTube serves (opus, m4a, webm-audio) and every format the user might drag in. We can't predict input formats. ffmpeg is the only safe choice.

**Confidence:** HIGH.

---

### Front-End: React + Vite

| Technology | Version (pin range) | Purpose | Why |
|---|---|---|---|
| React |18.x | UI | Standard |
| Vite |5.x | Build / dev server | Fast, ESM-native, no webpack ceremony |
| TypeScript |5.x | Type safety | The job/speaker/summary data model has enough moving parts that TS pays for itself |
| TanStack Query |5.x | Server state (jobs, history) | Cleaner than hand-rolled fetch + cache for the long-running-job polling pattern |
| Zustand or Redux Toolkit | latest | Client state | Job progress, settings |
| Tailwind CSS or vanilla CSS modules | — | Styling | Either works; pick at scaffold time |

**Why not Next.js / Remix:** We don't need SSR, server components, or file-based routing. SPA + a small FastAPI back-end is the right shape for a local app.

**Confidence:** HIGH for React + Vite + TS; MEDIUM on exact TanStack Query minor.

---

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---|---|---|---|
| **python-multipart** |0.0.x | Multipart upload parsing | Drag-and-drop file upload from React |
| **aiofiles** | latest | Async filesystem I/O | Saving uploaded files without blocking the event loop |
| **PyJWT** |2.x | (Optional) signed URLs for local-only endpoints | Not for auth — for protecting any future "share job" link |
| **loguru** |0.7.x | Logging | Simpler than stdlib logging; the local log is the user's debug surface |
| **pydantic-settings** |2.x | Settings / config file | Quality preset, model names, GPU choice |
| **rich** |13.x | Pretty progress in the CLI / first-run detect | Optional polish |
| **huggingface_hub** |0.20+ | Model downloads | First-run pulls models from HF |
| **ctranslate2** |3.x | (transitive) faster-whisper backend | |
| **tokenizers** | latest | (transitive) pyannote + HF | |

---

## GPU Auto-Detect (CUDA vs ROCm vs CPU)

The single most important "silent on first run" mechanic. The plan:

```
def detect_backend():
1. Try torch.cuda.is_available() → CUDA
2. Try torch.cuda.device_count() → confirm count >0
3. Try torch.version.hip is not None → ROCm (only on Linux wheels)
4. Else → CPU
```

On Windows, step3 **effectively never returns true** for consumer Radeon cards because PyTorch ROCm wheels are not officially distributed for Windows. The detection logic instead reads:

- `nvidia-smi` presence → CUDA path
- AMD vendor + absence of CUDA tools → try the ROCm wheel; if it fails to load, fall back to whisper.cpp ROCm build; if that fails too, CPU
- None of the above → CPU

**The right posture:** the back-end attempts CUDA first, logs what it found, picks a backend, and continues. **No dialogs.** A non-blocking banner on first run shows "GPU: NVIDIA RTX2000 Ada (CUDA) — using faster-whisper large-v3 int8" or "GPU: AMD Radeon6800 XT (ROCm path) — using whisper.cpp ROCm build" or "GPU: none detected — using CPU."

**Confidence:** HIGH on the strategy; MEDIUM on the exact ROCm-on-Windows wheel availability (this is the area most likely to need a phase-specific deeper-research flag).

---

## What NOT to Use (and Why)

| Category | Don't Use | Use Instead | Why |
|---|---|---|---|
| STT | `openai-whisper` | `faster-whisper` | ~2-4x slower, larger VRAM footprint, no first-class int8 |
| STT | `whisper-jax` | `faster-whisper` | JAX on Windows is brittle; CUDA-only; not the local-ML lingua franca |
| STT | cloud Whisper APIs | local | Violates no-cloud constraint |
| Diarization | custom VAD + clustering | `pyannote.audio` | pyannote is the only turn-key solution; rolling your own is a research project |
| Diarization | `nemo diarization` | `pyannote.audio` | NeMo is heavy, NVIDIA-stack-coupled, overkill for a single-user app |
| LLM | `transformers` (HF) directly with `model.generate` | `llama-cpp-python` | transformers doesn't ship first-class GGUF + int4 quant + CUDA + ROCm in one path |
| LLM | Ollama (in v1) | `llama-cpp-python` | Process boundary, model hot-swap friction. (Ollama is a fine v2 swap if user asks.) |
| LLM | `vllm` | `llama-cpp-python` | vLLM is server-grade, designed for many concurrent requests; we're one user, one job at a time |
| LLM | closed-weight models (GPT, Claude, Gemini) | open GGUF | Cloud-tied; violates local-only |
| Audio | `librosa` for everything | ffmpeg + occasional `soundfile` | librosa is for analysis, not I/O; ffmpeg handles format breadth |
| YouTube | `youtube-dl` | `yt-dlp` | youtube-dl is unmaintained |
| Back-end | Django / Flask | FastAPI | Sync request model + heavier ORM + no WebSocket ergonomics |
| Job queue | Celery + Redis | APScheduler + SQLite | Single-user single-machine; Redis is overhead |
| Front-end | Next.js / Remix | React + Vite SPA | No SSR need; local app |
| Persistence | PostgreSQL | SQLite | Single user, one machine |
| Front-end state | Redux (vanilla) | TanStack Query + Zustand | TanStack Query owns server state; Zustand owns the small client-state slice |

---

## Windows-Specific Install Notes (Honest Edition)

### CUDA path (laptop, NVIDIA RTX2000 Ada)

- Install the **NVIDIA Studio / Game Ready driver** for the RTX2000 Ada. The card is sm_89 (Ada Lovelace); any driver from the last ~2 years supports it.
- Install **CUDA Toolkit12.x** (whichever PyTorch2.2+ ships against — check the PyTorch wheel index page for the matching cu12x build).
- Install **cuDNN9.x** matching the CUDA toolkit.
- `pip install torch --index-url https://download.pytorch.org/whl/cu124` (or current cuX.Y) installs the matching wheel.
- `pip install faster-whisper` then pulls CTranslate2 with CUDA support.
- `pip install llama-cpp-python` with `CMAKE_ARGS="-DGGML_CUDA=ON"` (or pre-built wheel from the project's release page) gives CUDA-accelerated LLM inference.
- `pip install pyannote.audio` — pulls PyTorch (already CUDA-enabled from above).

### ROCm path (desktop, AMD Radeon6800 XT)

**Honest warning: ROCm on Windows for consumer Radeon cards is not officially supported by AMD.** The official ROCm wheels target Linux and server/workstation GPUs (Instinct, PRO). RDNA2 (6800 XT is gfx1030) has community / unofficial Windows support at best.

Realistic posture for the desktop:

1. **Try the official PyTorch ROCm wheel:** `pip install torch --index-url https://download.pytorch.org/whl/rocm5.7` (or whatever the current rocmX.Y tag is). This wheel **may not exist for Windows** in the period of interest. If it doesn't, fall through.
2. **Try `llama.cpp` ROCm build for Windows** (community-maintained by the llama.cpp project; check the GitHub releases). This is more likely to have a usable Windows build than PyTorch ROCm.
3. **Fall back to CPU** — the Ryzen55700X3D has8 cores and32 GB DDR4, so llama.cpp on CPU with Q4_K_M quantization is workable for the7B default model (slow, but functional).
4. **Last resort:** recommend the user consider a Linux dual-boot or WSL2 for the desktop. This is acceptable because the desktop is "spare VRAM," not the binding machine.

**We do not promise ROCm on Windows "just works."** We promise: detection, logging, and graceful fallback. The settings panel surfaces what backend is active.

### CPU-only path

- Pure Python wheels for everything; no GPU drivers needed.
- `faster-whisper` int8 on a modern x86 CPU is ~3-5x slower than RTX-class GPU but functional.
- `llama.cpp` Q4_K_M7B on CPU is ~5-15 tokens/sec on8 modern cores — slow but usable for short summaries.

**Confidence:** HIGH on the CUDA path being well-supported; LOW on a specific "the current state of ROCm on Windows for the6800 XT is X" claim. Phase1 must include a spike to confirm the actual state when the desktop is set up.

---

## Alternatives Considered (One-liners)

| Category | Recommended | Alternative | Why Not |
|---|---|---|---|
| STT default | faster-whisper | openai-whisper | Slower, more VRAM, no int8 |
| STT CPU/ROCm | whisper.cpp | faster-whisper CPU | whisper.cpp has the ROCm + CPU story in one binary; faster-whisper CPU works but lacks ROCm |
| Diarization | pyannote.audio3.1 | whisperx (bundles faster-whisper + pyannote) | whisperx is worth a look as an integrated pipeline; tradeoff is more opinionated glue |
| Diarization | pyannote.audio3.1 | NVIDIA NeMo diarization | Heavy, NVIDIA-stack-coupled |
| LLM | llama-cpp-python | Ollama | Process boundary, model hot-swap friction |
| LLM | llama-cpp-python | HuggingFace transformers + bitsandbytes | Worse ROCm story; transformers is a3 GB dependency tree |
| LLM family | Qwen2.5-Instruct | Llama-3.x, Mistral, Phi-4 | All viable; Qwen2.5 is the current sweet spot for structured prompts |
| Back-end | FastAPI | Django, Flask | See above |
| Front-end | React + Vite | Next.js, Remix | No SSR need |
| Persistence | SQLite | PostgreSQL | Single user, one machine |
| Job runner | APScheduler | Celery, arq | Overkill for single user |

---

## Sources

- PROJECT.md (TranscriptionAndNotes) — hardware constraints, decision table, scope. HIGH confidence on hardware, MEDIUM on the assertion that this stack is "current" without fresh verification.
- Sibling FEATURES.md — establishes the ecosystem baseline and MEDIUM confidence on "current as of2026" ecosystem claims.
- Prior knowledge of the local-transcription stack (faster-whisper / CTranslate2, pyannote3.x, llama.cpp / llama-cpp-python, yt-dlp, FastAPI, React + Vite) as of the2025-2026 cycle. MEDIUM confidence on exact version numbers.
- **Cannot verify in this environment:** exact PyPI / GitHub release versions of faster-whisper, pyannote.audio, llama-cpp-python, yt-dlp. The `gsd-tools` research-plan seam and `WebFetch` / `WebSearch` tools were denied, so version pins should be re-checked at Phase0 (scaffold) when the build environment is set up.

## Research Flags for Roadmap

These areas likely need a phase-specific deeper research spike before implementation:

- **Phase0 (scaffold) — ROCm on Windows:** confirm whether the current PyTorch ROCm wheel exists for Windows and supports gfx1030 (6800 XT). If not, lock in whisper.cpp ROCm build or CPU fallback. This is the single highest-risk unknown.
- **Phase1 (STT) — faster-whisper version:** pin a version that supports CTranslate23.x and confirm int8 quantization works for large-v3 within the8 GB laptop budget. Profile VRAM at runtime.
- **Phase2 (diarization) — HuggingFace token UX:** the gating flow is the one first-run interaction that isn't silent. Decide whether to (a) prompt on first run, (b) defer with a banner, or (c) bundle a token-via-env-file pattern.
- **Phase3 (LLM) — Qwen2.5 vs Llama-3 vs Mistral:** run a small benchmark on the laptop with a sample meeting transcript and a concept-explainer prompt. Pick the family whose structured-output quality holds up at Q4_K_M7B.
- **Phase4 (settings + chunking) — chunk size / overlap tuning:** validate that auto-chunking preserves diarization continuity at chunk boundaries. This is a domain-research item, not a stack one, but worth flagging here so the planner doesn't lump it under generic "settings."
