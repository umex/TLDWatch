# Project Research Summary

**Project:** TranscriptionAndNotes
**Domain:** Local-first video transcription + diarization + LLM summarization (Windows, dual GPU: CUDA laptop + ROCm desktop)
**Researched:** 2026-06-11
**Confidence:** MEDIUM (research tools were unavailable for fresh verification; findings grounded in PROJECT.md hardware/decision constraints and well-established ecosystem patterns)

## Executive Summary

This is a local-first, single-user, Windows-only transcription + summarization web app. The product takes video inputs (drag-and-drop, YouTube URL, or YouTube playlist), runs speech-to-text + optional speaker diarization + multi-template LLM summarization, and exports Markdown. The binding hardware constraint is the laptop (NVIDIA RTX 2000 Ada, 8 GB VRAM); the desktop (AMD 6800 XT, 16 GB) opts into larger models via a per-category override, never a separate UX.

The recommended approach is a conventional two-process local app — a FastAPI back-end (Python 3.11, SQLite WAL, in-process job orchestrator, WebSocket progress) and a React + Vite front-end — using the canonical local-ML trio: **faster-whisper** (CTranslate2, int8 quantized) for STT, **pyannote.audio 3.1** for diarization, and **llama-cpp-python** with a Qwen2.5-Instruct GGUF for summarization. All inference runs in one in-process Python worker with single-model-at-a-time VRAM discipline; a persistent SQLite-backed job queue with file-as-truth stage outputs handles restarts.

The key risks are concentrated in three areas: (1) **ROCm on Windows is the canonical "doesn't work the way docs imply" trap** — the desktop GPU path needs an explicit spike in the very first phase, with whisper.cpp + llama.cpp ROCm/HIP Windows builds (or CPU fallback) as the realistic posture; (2) **the 8 GB laptop VRAM budget is tight** — the three models together exceed it, so the orchestrator must enforce sequential load/unload with OOM-aware chunk-fallback rather than "keep all models warm"; (3) **the silent-first-run promise has one honest caveat** — pyannote 3.1 is HuggingFace-gated and requires a token + license accept, so diarization must be opt-in with a non-blocking banner rather than a wizard.

## Key Findings

### Recommended Stack

The local transcription + diarization + LLM stack has converged on a clear three-layer pattern; we use it as-is. STT is **faster-whisper** (CTranslate2-backed Whisper with first-class int8) as the default and **whisper.cpp** as the CPU/ROCm escape hatch. Diarization is **pyannote.audio 3.1** — the only mature turn-key open-source option, but HuggingFace-gated. LLM is **llama-cpp-python** (in-process Python binding for llama.cpp) loading **Qwen2.5-Instruct** GGUF models, sized per quality preset. The "CUDA vs ROCm transparently" requirement is the only genuinely hard part: write the back-end to detect GPU on first run, prefer CUDA when available, and have a *documented* ROCm-on-Windows fallback path (whisper.cpp ROCm build, llama.cpp HIP build, or CPU). Everything else (job queue, YouTube download via yt-dlp, audio extraction via ffmpeg, React UI, SQLite persistence) is commodity tooling.

**Core technologies:**
- **Python 3.11 + FastAPI + Uvicorn** — back-end runtime; async-native WebSocket progress, free OpenAPI schema
- **faster-whisper (CTranslate2)** — STT; int8 quant lets large-v3 fit on 8 GB
- **whisper.cpp** — fallback STT path for ROCm/CPU
- **pyannote.audio 3.1** — diarization; requires HF token + license accept (deferred to non-blocking banner)
- **llama-cpp-python + GGUF (Qwen2.5-Instruct)** — local LLM; in-process, supports CUDA + ROCm + CPU
- **yt-dlp + ffmpeg** — YouTube ingest and audio extraction
- **SQLite (WAL mode) + filesystem-per-job** — job state + per-stage output files
- **React 18 + Vite + TypeScript + TanStack Query** — front-end; SPA, no SSR
- **APScheduler (or thread-pool)** — single-user in-process job runner; no Celery/Redis

### Expected Features

The local-transcription ecosystem has converged on a clear table-stakes set (drag-and-drop, timestamped segments, click-to-seek, job queue with progress, history, Markdown export, language auto-detect, speaker labels, inline edit, pause/resume, persistence, settings). PROJECT.md already commits to all of them.

**Must have (table stakes):**
- Drag-and-drop / file picker upload
- YouTube URL paste-and-submit
- Timestamped transcript segments with click-to-seek
- Job queue with per-job progress + persistence across restarts
- Speaker labels ("Person 1", "Person 2") with bulk rename + per-line reassignment
- Inline edit of transcript text + find-and-replace speaker
- Markdown export (JSON / SRT / VTT deferred)
- Language auto-detect (Whisper-native)
- Settings panel with quality/model selector

**Should have (differentiators):**
- YouTube playlist input with pause/resume and sequential queueing
- Multi-select summary templates per job (the four: meeting, investment, concept, quick recap)
- Silent GPU auto-detect (CUDA vs ROCm) on first run
- Quality preset (small / balanced / large) auto-selecting model variants
- Per-category model override (transcription / diarization / LLM)
- Auto-chunking with OOM fallback for long videos
- Side-by-side video + transcript + summary view
- Re-export from history with edits applied

**Defer (v2+):**
- SRT / VTT export, custom summary templates, RAG "ask the video" chat, chapter markers, auto-translation, per-segment confidence scores, plugin / extension API, backup integration, mobile breakpoints beyond "doesn't break"

**Explicitly anti-features (do not build):** cloud sync / accounts, multi-user / auth / LAN exposure, mobile / responsive phone UI, live streaming transcription, translation, custom summary templates (v1), in-app video editor, public sharing, mobile app, telephony/meeting bots, AI chat with transcript, social share cards, webcam/mic recording, template marketplace, plugin API, auto-publish to Notion/Obsidian, per-machine separate UX, first-run setup wizard, speaker-count input, auto-punctuation beautification, per-segment confidence in v1, multi-language transcript, auto-upload backup, telemetry, auto-update, email notifications, TTS, SRT/VTT subtitle files.

### Architecture Approach

Two-process system, both spawned by a single launcher. The back-end is the system of record (FastAPI + in-process job orchestrator + persistent SQLite queue + per-job working directory on disk); the front-end is a thin client over HTTP + WebSocket. The pipeline is a DAG: ingest → chunk → STT → (optional) diarize → summarize (one pass per selected template) → persist + broadcast. The orchestrator pushes progress events through an in-memory pub/sub that the WebSocket fans out. The GPU is abstracted as a single `GpuBackend` enum (`CUDA` / `ROCM` / `CPU`) chosen once on first run, written to `settings.json`, and never branched on at inference time. Models load on first use, unload when idle; single-model-at-a-time VRAM discipline is enforced by the model manager. State machine transitions are atomic against the on-disk file (`transcript.json` exists = STT done).

**Major components:**
1. **FastAPI back-end (app/api + app/jobs/orchestrator.py + app/jobs/queue.py)** — thin HTTP/WS API delegates to a single in-process asyncio loop + thread pool; owns the job state machine
2. **Adapters per model (app/models/stt, /diarize, /llm)** — `STTAdapter`, diarize adapter, LLM adapter behind small Protocols; the orchestrator never imports a library directly
3. **Model manager (app/models/manager.py + app/models/backend.py)** — first-run download, version pinning, SHA verification, lazy load into VRAM, idle unload; GPU backend detection
4. **Storage (app/storage/db.py + app/storage/fs.py)** — SQLite WAL for jobs/settings/aliases; filesystem-per-job for stage outputs (file-as-truth crash recovery)
5. **React front-end (Vite + React 18 + TanStack Query)** — drop zone, job status list, transcript editor, summary viewer, history nav, settings panel; reads job state via REST, live progress via WebSocket

### Critical Pitfalls

1. **ROCm on Windows is broken in subtle ways** — the official PyTorch ROCm wheel is not distributed for Windows for consumer Radeon; community HIP-on-Windows builds are partial. Symptoms include silent CPU fallback (30x slower), DLL load failures, or a torch wheel that imports but every kernel hits the CPU path. *Avoid by:* first-run GPU-burn test that writes the *active* backend (CUDA / ROCm-active / CPU-fell-back) to `settings.json` and surfaces it; Settings → Diagnostics panel runs a per-backend test and reports measured tokens/sec; the desktop ROCm path uses whisper.cpp ROCm build for STT and llama.cpp ROCm/HIP build for LLM (PyTorch ROCm on Windows is not a target); diarize on the desktop runs on CPU or is disabled with a banner.

2. **VRAM exhaustion from concurrent models on the 8 GB laptop** — Whisper medium int8 (~3 GB) + pyannote (~1-2 GB) + Qwen2.5-7B Q4_K_M (~5-6 GB) totals 9-11 GB, exceeding the 8 GB budget. *Avoid by:* explicit lifecycle in the model manager (STT loads, transcribes, unloads; same for diarize and LLM); opt-in "keep all models warm" toggle hidden behind a VRAM-availability check, default off; VRAM probing on model load refuses to load the next model if it would push past 85% of available; `chunk.fallback` event on STT OOM halves chunk size and retries; "what's currently in VRAM" indicator in the UI.

3. **HuggingFace-gated pyannote model treated as a normal dependency** — `Pipeline.from_pretrained` returns 401; the user sees a generic error. *Avoid by:* diarization is **optional and disabled by default** until a token is in settings; non-blocking UI banner: "Speaker labels are disabled. Add a HuggingFace token in Settings to enable."; one-click "Get a token" link + paste field + "Test token" button in settings; invalid token shows "Token rejected — speaker labels disabled" and the job continues without diarization; token stored in `settings.json` (or a separate `secrets.json`), not in SQLite.

4. **First-run model download silently fails or stalls** — 4-7 GB of weights, flaky Wi-Fi, antivirus quarantine of `.gguf`/`.pt` files, HF rate-limits, paths with spaces — leads to hangs, partial completion, or corrupt files. *Avoid by:* model manager verifies each file (size, optional SHA256) after download; persistent download log exposed in the UI ("downloading faster-whisper large-v3: 412 MB / 1.5 GB, ETA 3 min"); download paths live under a directory with no spaces (`%LOCALAPPDATA%\TranscriptionAndNotes\Models\`); resume-on-crash (partial files kept); "Verify all models" button in settings; first-run flow lets the user **defer** model download (use Small preset to skip the 7B LLM download).

5. **Long-audio pipeline OOMs despite "chunking"** — chunking solves "input too long" not "model context too long"; pyannote runs on the *full* audio for global speaker turns and is the real OOM trigger on 3+ hour audio. *Avoid by:* sliding-window diarize for very long audio (process in 5-10 min windows with overlap, stitch turns); auto-fallback rule: if audio > N minutes (default 90), switch to long-audio diarize strategy; orchestrator releases GPU memory between STT and Diarize (`torch.cuda.empty_cache()` + explicit model unload) so pyannote gets a fresh budget; "skip diarize for jobs longer than 4 hours" soft-warning.

6. **LLM structured outputs are flaky on long transcripts** — on a 200k-token meeting, the local 7B Q4_K_M loses section structure, hallucinates tickers, outputs the prompt back partially, refuses on "PII" pattern. *Avoid by:* four templates ship as typed schemas the back-end validates; LLM is told "section names must be exactly these strings"; a post-validator checks output and re-prompts with "you missed section X" follow-up, bounded to 2 retries; for long transcripts, chunked summarization (per-section summary, then synthesize); templates unit-tested in CI against a battery of sample transcripts; low LLM temperature (0.1-0.2); opt-in "schema-strict" mode using llama.cpp GBNF grammar constraints.

7. **Front-end and back-end disagree on job IDs, speaker labels, and stage names** — progress events disappear, rename works in UI but export says "Person 1", job ID mismatch on reconnect. *Avoid by:* shared schema (OpenAPI spec generated from Pydantic models, TypeScript types generated via `openapi-typescript`); WebSocket reconnection replays missed events or re-fetches job state; idempotency key on `POST /jobs` (double-submit returns the existing job ID); no optimistic UI for jobs (wait for server confirmation); version string on the WebSocket protocol.

8. **Drag-and-drop of a multi-gigabyte video file hits browser or server limits** — default FastAPI `python-multipart` reads into memory; a 4 GB MP4 OOMs the worker or times out. *Avoid by:* streaming upload with FastAPI (`Request.stream()` writes directly to `data/jobs/<id>/source.ext`; never hold the full file in memory); front-end uses `fetch` with `ReadableStream` body for true streaming upload with progress events; pre-upload UI check shows "this will take a few minutes to upload, leave the tab open" for > 2 GB files.

9. **Job-queue state on disk is the source of truth, but the schema evolves** — schema migrations break old jobs, crash mid-state-machine leaves a job in `transcribing` and the orchestrator must decide resume/re-run/fail, playlist children reference a parent that no longer exists. *Avoid by:* state machine transitions are atomic against files (a job moves to `transcribed` only if `transcript.json` exists; the file is truth, the DB row is index); idempotent schema migrations with a `schema_version` table; resume logic scans `data/jobs/<id>/` for stage-output files and infers resume point; "stale" detector auto-resets jobs with no recent stage output; crash-safe writes use `.tmp` + fsync + rename.

10. **"Just works on both machines" turns into a per-machine configuration nightmare** — laptop is easy (CUDA, 8 GB); desktop is painful (whisper.cpp ROCm + llama.cpp ROCm/HIP + pyannote on CPU); two paths with different model files and quantization options. *Avoid by:* first-run info card shows what is active per model category with a "Test" button; settings panel has a "Backend: CUDA / ROCm / CPU" indicator; diagnostics page runs per-backend smoke test; default model set is `BALANCED` (fits 8 GB laptop); desktop user can opt into `LARGE` with explicit "designed for the 8 GB laptop; will use ~10 GB VRAM on the desktop" warning.

## Implications for Roadmap

The suggested phase structure follows ARCHITECTURE.md's build order, which is driven by dependencies: back-end skeleton + storage first (everything imports it), then GPU detection + model manager (no model code can run without it), then the cheapest end-to-end STT pipeline (validates GPU abstraction before the orchestrator wraps it), then the orchestrator + queue + WebSocket (the spine), then user-visible features ordered by user-value density, then settings last (touches everything; build when the rest is stable). A 10-phase structure is the right shape for a project of this complexity.

### Phase Ordering Rationale

- **Phases 1-2 are dependency-foundational**: every other component imports them. The GPU-detection spike in Phase 2 is the single highest-risk unknown (ROCm on Windows in mid-2026) and must be confirmed before any model work.
- **Phase 3 is the cheapest end-to-end GPU check**: a 200-line STT CLI validates the GPU abstraction on both machines before the orchestrator wraps it. If Whisper blows up on the desktop, the failure is isolated.
- **Phase 4 turns the working script into the architecture**: once the orchestrator + queue + WebSocket exist, every later feature is "add a stage." This is the longest single piece and the spine of the app.
- **Phases 5-9 are user-visible features, ordered by user-value density**: drag-and-drop + history (most common case) → YouTube (second most common) → diarize (most UI work) → summarize (the headline differentiator, but depends on transcript existing) → editor polish.
- **Phase 10 is last because it exposes everything to the user**: you want the rest of the app to be stable when you give them the levers. First-run diagnostics card + per-backend smoke test are part of the spec, not polish.
- **VRAM discipline is enforced across all phases, but the temptation peaks in Phase 8** (LLM loads after diarize on a tight 8 GB budget) and Phase 2 (where the lifecycle pattern is set).
- **The HF token UX is the only "silent first run" caveat that must be honestly surfaced** — built in Phase 7 (the actual pyannote integration) but the banner is part of the v1 experience from day one.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (GPU detection + model manager):** ROCm on Windows for the 6800 XT in mid-2026 — confirm whether PyTorch ROCm wheel exists for Windows and supports gfx1030; if not, lock in whisper.cpp ROCm build + llama.cpp ROCm/HIP build, or document CPU fallback. Single highest-risk unknown.
- **Phase 3 (STT + chunker):** faster-whisper version pin + int8 quantization verification for large-v3 within 8 GB laptop budget; profile VRAM at runtime; chunk size / overlap tuning for diarization continuity.
- **Phase 6 (YouTube ingest):** yt-dlp's current state for playlists with age-gated or region-locked videos; format selector pin for audio-only.
- **Phase 7 (Diarize):** pyannote "expected N speakers" mode exact knob + reliability; long-audio diarize strategy (sliding-window vs two-pass with smaller variant).
- **Phase 8 (LLM + templates):** Qwen2.5 vs Llama-3 vs Mistral benchmark on the laptop with sample meeting + concept-explainer prompts; prototype GBNF grammars for the four templates to confirm they can be expressed.

Phases with well-documented patterns (skip /gsd-plan-phase --research-phase):
- **Phase 1 (back-end skeleton + storage):** standard FastAPI + SQLite + Pydantic patterns; no exotic decisions.
- **Phase 4 (orchestrator + queue + WebSocket):** standard FastAPI WebSocket + SQLite WAL pub/sub; state machine is the only design decision and it is well-scoped.
- **Phase 5 (local file ingest + history UI):** standard drag-and-drop + streaming upload + react-dropzone; well-trodden.
- **Phase 9 (transcript editor + export):** standard React editor + PATCH endpoints; pattern is clear.
- **Phase 10 (settings panel):** standard Pydantic settings + React form patterns; the *content* (per-backend smoke test, content-hash model manager) is the work, not the research.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Hardware-anchored recommendations are HIGH; exact version pins are MEDIUM. Pin versions in Phase 0 / Phase 2 when the build env is set up. |
| Features | MEDIUM-HIGH | Table-stakes grounded in PROJECT.md commitments; anti-features extend PROJECT.md with high-confidence adjacent patterns. Competitive landscape claims are MEDIUM. |
| Architecture | MEDIUM-HIGH | Two-process split is project requirement; SQLite WAL is standard; WebSocket vs SSE is a clear pick; GPU abstraction is well-trodden 2026 path. Build order is sensible but reorderable. |
| Pitfalls | MEDIUM-HIGH | Pitfall shapes are well-known and HIGH confidence. ROCm-on-Windows specifics are LOW confidence — must be re-verified in Phase 2. |

**Overall confidence:** MEDIUM (with HIGH confidence on shapes and LOW on time-sensitive ROCm specifics).

### Gaps to Address

- **The actual state of ROCm on Windows for the 6800 XT in mid-2026** — cannot be verified in this research environment. Phase 2 is the first thing the project does on the desktop.
- **Current faster-whisper / pyannote / llama-cpp-python version pins** — confirm in Phase 2 against PyPI / GitHub releases.
- **VRAM budgeting for diarize + LLM concurrent load on 8 GB** — needs measurement in Phase 3 / Phase 7.
- **pyannote "expected N speakers" mode** — exists in pyannote's API; exact knob name and reliability needs Phase-7 verification.
- **llama.cpp GBNF grammar constraints for the four templates** — prototype in Phase 8 to confirm all four templates can be expressed as grammars.
- **Browser's actual streaming-upload support** — fetch with `ReadableStream` body; verify in Phase 5.
- **Whether yt-dlp's mid-2026 state handles playlists with age-gated or region-locked videos** — Phase-6 spike.
- **HuggingFace rate-limits on first-run download** — handle retry gracefully.
- **Playlist pause semantics** — "finish current child, then stop" — decide during Phase 6.
- **Concurrency between STT and diarize on the desktop** — probably sequential-by-default with opt-in parallel.

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` (TranscriptionAndNotes) — hardware, requirements, key decisions, two-machine constraint
- `.planning/research/STACK.md` — technology stack recommendations and rationale
- `.planning/research/FEATURES.md` — feature landscape, table stakes, differentiators, anti-features
- `.planning/research/ARCHITECTURE.md` — two-process architecture, component boundaries, data flow, build order
- `.planning/research/PITFALLS.md` — 30 pitfalls with phase ownership, prevention, detection

### Secondary (MEDIUM confidence)
- Prior knowledge of the local-transcription ecosystem (faster-whisper / CTranslate2, pyannote.audio 3.x, llama.cpp / llama-cpp-python, yt-dlp, Silero VAD, FastAPI, React + Vite)
- Established known-failure-modes for the local-transcription stack
- Two-codebase integration patterns (OpenAPI → TypeScript, WebSocket reconnection with replay)

### Tertiary (LOW confidence — needs validation)
- Exact PyPI / GitHub release versions of faster-whisper, pyannote.audio, llama-cpp-python, yt-dlp (pin in Phase 0 / Phase 2)
- The current state of ROCm-on-Windows community wheels for the 6800 XT in mid-2026 (verify in Phase 2 spike)
- Recent (2026) yt-dlp issues with playlists / age-gated / region-locked videos (verify in Phase 6)
- The exact knob name and reliability of pyannote's "expected N speakers" mode (verify in Phase 7)
- Whether the four summary templates can be expressed as llama.cpp GBNF grammars (prototype in Phase 8)
- The file-size threshold where the browser switches from streaming to buffering on `fetch` with `ReadableStream` body (verify in Phase 5)

---
*Research completed: 2026-06-11*
*Ready for roadmap: yes*
