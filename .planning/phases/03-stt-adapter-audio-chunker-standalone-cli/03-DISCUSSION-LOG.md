# Phase 3: STT Adapter + Audio Chunker + Standalone CLI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19
**Phase:** 3-STT Adapter + Audio Chunker + Standalone CLI
**Areas discussed:** Audio decode path, Chunking strategy, CLI shape & output, Compute type per backend (all deferred to Claude's Discretion by the user)

---

## How the discussion went

The user was presented four phase-specific gray areas via AskUserQuestion (multiSelect): audio decode path, chunking strategy, CLI shape & output, compute type per backend. The user declined to pick any and instead deferred all four to Claude, explicitly inviting cross-AI review:

> "i am not familiar with these things. I will leave that up to you. Maybe you can discuss it with some other agent like codex or gemini if you are not sure. They should be added as reviewers."

In response, Claude (a) grounded the two genuinely-uncertain technical facts (faster-whisper decode path; long-audio chunking + compute_type) against faster-whisper's source, issues, and official benchmark via web search, (b) made all four decisions with recorded rationale, (c) wired codex + gemini into `review.default_reviewers` so they review the plans/implementation downstream, and (d) recorded the user's prior same-session GPU-priority decision (CUDA laptop primary, RX 6800 non-blocking) as D-05, which supersedes the 02-03 spike's "schedule a re-spike" clause.

## Audio decode path

| Option | Description | Selected |
|--------|-------------|----------|
| faster-whisper built-in PyAV (pass file path) | PyAV bundles FFmpeg in the wheel; no system ffmpeg; decodes video audio streams natively; decode is ~5–10% of runtime | ✓ |
| ffmpeg subprocess → wav | ~10–20% faster decode but requires a system ffmpeg install (violates silent-no-install laptop promise) | |
| pydub / librosa | Extra Python deps; same system-ffmpeg issue for most formats | |

**User's choice:** Deferred to Claude.
**Notes:** Claude chose PyAV (D-01). A system ffmpeg install would break the laptop's silent-no-install first-run promise and add a Windows PATH burden; the speed gain is negligible because inference dominates. ffmpeg-CLI fast path deferred to a future optimization.

## Chunking strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Coarse windowed chunker on top of faster-whisper's internal 30 s window | >30 min → ~15-min windows + overlap + stitch + per-chunk OOM halve-and-retry; ≤30 min single-shot | ✓ |
| Trust faster-whisper internal only + OOM halve-and-retry | No own chunker; rely on the internal 30 s sliding window | |

**User's choice:** Deferred to Claude.
**Notes:** Claude chose the coarse chunker (D-02). SC-2 + INGEST-05 lock "chunks with overlap, stitched, OOM → halve and retry" as a success criterion — it is not optional, so "trust internal only" was not actually viable. The chunker composes with faster-whisper's internal windowing (each chunk is just shorter audio handed to `transcribe()`); VAD filter on.

## CLI shape & output

| Option | Description | Selected |
|--------|-------------|----------|
| console_scripts entry point `transcribe` | `pip install -e .` exposes `transcribe <file>`; args for preset/device/language/out/compute-type; writes transcript.json to --out | ✓ |
| `python -m app.cli transcribe <file>` | Module form; always works without an install step | |

**User's choice:** Deferred to Claude.
**Notes:** Claude chose the entry point (D-03) as the headline "standalone CLI" SC-1 demands, with the module form kept as an alias. The CLI is a thin caller of `STTAdapter` (never imports faster-whisper — SC-4) and does NOT create a job dir (job system is Phase 4). Device + compute_type resolve from persisted settings so the same command runs on laptop CUDA and desktop CPU with no code changes (SC-5).

## Compute type per backend

| Option | Description | Selected |
|--------|-------------|----------|
| int8_float16 on CUDA, int8 on CPU | ~2–3 GB VRAM on CUDA large-v3, <0.1% WER loss, near-fp16 speed; int8 best on CPU | ✓ |
| float16 on CUDA | Fastest on modern GPUs but ~4.5 GB VRAM (less headroom on 8 GB) | |
| int8 everywhere | Smallest VRAM; slower on CUDA than int8_float16 | |

**User's choice:** Deferred to Claude.
**Notes:** Claude chose int8_float16 / int8 (D-04), grounded in faster-whisper's own benchmark (int8 = 2926 MB vs float16 = 4525 MB on RTX 3070 Ti 8 GB, <0.1% WER difference). Matches the 02-03 spike's CPU `int8` verdict. `--compute-type int8_float32` is the escape hatch for the known int8_float16 empty-transcription bug on some older GPUs.

## Claude's Discretion

All four gray areas (D-01 decode, D-02 chunking, D-03 CLI, D-04 compute type) plus D-07 (language detect) and D-08 (version pin / int8 verification) were deferred by the user and decided by Claude with a recorded rationale each, grounded against upstream sources where the facts were uncertain. D-05 (GPU path: CUDA primary, RX 6800 non-blocking) was a user decision made earlier in the same session. D-09 (codex + gemini as default reviewers) was a user request, actioned in config.

## Deferred Ideas

- ffmpeg-CLI decode fast path — future optimization only if decode shows up in profiling.
- whisper.cpp HIP adapter for the RX 6800 — the only way STT leaves CPU on the desktop; a future, separate decision.
- ROCm re-spike — superseded by D-05; re-open only if the user explicitly invests in the desktop GPU path.
- Prefetch STT model at job-submit — Phase 4 follow-up.
- Streaming/real-time transcription — out of scope (PROJECT.md).
- Per-chunk WebSocket progress — Phase 4.