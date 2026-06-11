# Architecture Patterns

**Project:** TranscriptionAndNotes
**Domain:** Local-first video transcription + summarization web app
**Researched:** 2026-06-11
**Overall confidence:** MEDIUM-HIGH (concrete project constraints; ecosystem choices are well-trodden)

## Recommended Architecture

Two-process system, both spawned by a single launcher. The back-end is the system of record; the front-end is a thin client over an HTTP + WebSocket API.

```
+----------------------+         HTTP/WS          +-----------------------------+
|   React Front-end    | <---------------------> |  FastAPI Back-end           |
|  (Vite + React 18)   |                          |                             |
|                      |   POST /jobs             |  +-----------------------+  |
|  - Drop zone         |   GET  /jobs             |  |   API layer (FastAPI) |  |
|  - Job status list   |   WS   /ws/jobs/{id}     |  +----------+------------+  |
|  - Transcript editor |                          |             |               |
|  - Summary viewer    |                          |             v               |
|  - Settings panel    |                          |  +-----------------------+  |
|  - History nav       |                          |  |    Job Orchestrator   |  |
+----------------------+                          |  |  (in-process workers) |  |
                                                  |  +----+---------------+--+  |
                                                  |       |               |     |
                                                  |       v               v     |
                                                  |  +----+----+    +-----+----+|
                                                  |  | STT     |    | Diarize  ||
                                                  |  | Adapter |    | Adapter  ||
                                                  |  +----+----+    +-----+----+|
                                                  |       |               |     |
                                                  |       v               v     |
                                                  |  +----+----+    +-----+----+|
                                                  |  | LLM     |    |  Audio   ||
                                                  |  | Adapter |    |  Ingest  ||
                                                  |  +----+----+    +-----+----+|
                                                  |       |               |     |
                                                  |       +-------+-------+     |
                                                  |               v             |
                                                  |       +---------------+     |
                                                  |       |   Storage     |     |
                                                  |       |  (SQLite +    |     |
                                                  |       |   data/ tree) |     |
                                                  |       +---------------+     |
                                                  |               ^             |
                                                  |       +-------+-------+     |
                                                  |       | GPU / Model  |     |
                                                  |       |  Backend     |     |
                                                  |       |  Abstraction |     |
                                                  |       +---------------+     |
                                                  +-----------------------------+
```

### Process boundaries

| Process | Owns | Talks to | Never does |
|---------|------|----------|------------|
| React (Vite dev / static build) | UI, file drop, transcript editing, speaker renaming, summary viewing, history nav, settings panel | Back-end HTTP + WebSocket | Touch the filesystem, load models, run inference |
| FastAPI back-end | Model loading, all inference, audio download + decode, chunking, job lifecycle, persistence, GPU backend configuration | Front-end over loopback HTTP/WS, YouTube over HTTPS, HuggingFace over HTTPS on first run | Render UI, run a browser |
| OS launcher | Starts both processes, opens browser to `http://localhost:<port>`, ensures the back-end is up before serving the UI | Both | Reimplement either |

**Loopback only.** The back-end binds `127.0.0.1`. There is no auth, no LAN exposure, no reverse proxy in v1.

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `app/launcher.py` | Spawn back-end, wait for `/health`, spawn Vite dev or serve static, open browser | OS, both processes |
| `app/api/` (FastAPI routers) | HTTP request/response, schema validation, auth-free loopback binding | Front-end, job orchestrator, storage |
| `app/api/ws.py` | WebSocket endpoint that subscribes a client to one or more job IDs | Front-end, job orchestrator (publish/subscribe) |
| `app/jobs/orchestrator.py` | Single in-process asyncio loop + thread pool; owns the job state machine | API, storage, ingest, adapters |
| `app/jobs/queue.py` | Persistent FIFO queue backed by SQLite; resume on restart | Orchestrator, storage |
| `app/jobs/state.py` | Typed job state machine: `pending -> ingesting -> transcribing -> diarizing -> summarizing -> editing -> done` (plus `failed`, `paused`, `cancelled`) | Orchestrator |
| `app/ingest/local.py` | Copy/drop a user-provided file into the data tree, probe duration, extract audio to 16 kHz mono WAV | Orchestrator, ffmpeg |
| `app/ingest/youtube.py` | Resolve a video or playlist URL with `yt-dlp`, download audio, expand playlists into N jobs | YouTube, ffmpeg |
| `app/audio/chunker.py` | Split long WAVs by VAD-aware silence; produce chunk manifests; reassemble results | Orchestrator, ffmpeg, faster-whisper / whisper.cpp |
| `app/audio/vad.py` | Silero VAD to decide chunk boundaries when the input has natural pauses | chunker |
| `app/models/backend.py` | GPU abstraction: detect CUDA / ROCm / CPU, expose a `Backend` enum and one factory per model | adapters, settings |
| `app/models/stt/` | Whisper adapter. Default: `faster-whisper` (CTranslate2, ROCm+CUDA friendly) with `whisper.cpp` as a fallback for very low VRAM. | GPU backend, chunker |
| `app/models/diarize/` | pyannote.audio adapter, gated behind a HuggingFace token configured on first run | GPU backend |
| `app/models/llm/` | llama-cpp-python adapter (preferred) or Ollama HTTP client. Pure local; no remote calls after model download. | GPU backend, settings |
| `app/models/manager.py` | First-run download, version pinning, SHA verification, lazy load into VRAM, idle unload | settings, adapters |
| `app/storage/db.py` | SQLite for jobs, settings, speaker aliases, edit history; WAL mode | everything persistent |
| `app/storage/fs.py` | Filesystem layout under `data/`: `data/jobs/<id>/source.*`, `audio.wav`, `chunks/`, `transcript.json`, `diarization.json`, `summaries/*.md` | ingest, orchestrator, models |
| `app/summaries/templates.py` | The four built-in prompt templates (meeting, investment, concept, quick recap) — pure data | LLM adapter, orchestrator |
| `app/settings/store.py` | Reads/writes `settings.json`; first-run GPU detection writes initial values | model manager, API |
| `app/realtime/broadcaster.py` | In-memory pub/sub: orchestrator publishes progress events; WebSocket fans out to subscribed clients | orchestrator, WS endpoint |

### Filesystem layout (under the user's data dir, e.g. `~/.local/share/transcriptionandnotes/` on Linux, `%LOCALAPPDATA%\TranscriptionAndNotes\` on Windows)

```
data/
  models/                # downloaded model weights
    stt/faster-whisper-large-v3/
    diarize/pyannote-3.1/
    llm/qwen2.5-7b-instruct-q4_k_m.gguf
  jobs/<job-id>/
    source.ext           # original upload / downloaded media
    audio.wav            # 16 kHz mono PCM, the canonical audio
    chunks/              # chunk_0000.wav, chunk_0001.wav, ...
    chunk_manifest.json
    transcript.json      # segments with start/end/text/speaker
    diarization.json     # raw pyannote output (kept for re-alignment)
    summaries/<type>.md
  cache/yt/              # raw yt-dlp downloads before audio extraction
  logs/                  # rotating job logs
config/
  settings.json          # quality preset, model overrides, GPU backend
  db.sqlite              # WAL-mode SQLite file
```

## Data Flow

The system has three input paths and one long pipeline. The pipeline is a DAG of stages, with persistence and progress events emitted after each stage.

### Three entry points

| Entry | Source | Path |
|-------|--------|------|
| Local file | Drag-and-drop / file picker | `POST /jobs` with `multipart/form-data` |
| Single YouTube URL | Paste in UI | `POST /jobs` with `{"url": "..."}` |
| YouTube playlist URL | Paste in UI | `POST /jobs` with `{"url": "..."}` — expanded server-side into N child jobs sharing a `playlist_id` |

### Pipeline (per job)

```
1. INGEST
   local file  -> copy to data/jobs/<id>/source.ext
   YouTube URL -> yt-dlp downloads to data/cache/yt/
                -> ffmpeg extracts 16 kHz mono WAV -> data/jobs/<id>/audio.wav
   playlist    -> fan out into N child jobs; they go in the queue sequentially by default

2. CHUNK (always; cheap; safe to keep)
   silence-aware split into ~30s chunks
   -> chunk_manifest.json
   if VAD says "one continuous lecture", one chunk is fine

3. STT
   for each chunk: faster-whisper -> segments with start/end/text
   stitched into transcript.json
   progress event: percent_done = chunks_done / chunks_total

4. DIARIZE (optional but default-on)
   pyannote runs on the full audio (not chunks) to get global speaker turns
   if >1 speaker detected:
     align per-chunk segments to speaker turns
     emit transcript.json with speaker labels
   else:
     skip; mark transcript as "no diarization"
   progress event: percent_done

5. SUMMARIZE (per selected template)
   for each summary_type in job.summary_types:
     build prompt from transcript.json + template
     call LLM adapter
     write data/jobs/<id>/summaries/<type>.md
   progress event: percent_done

6. PERSIST + BROADCAST
   mark job as 'done' in SQLite
   emit 'job.done' over WebSocket
   front-end refreshes history view
```

### Failure and recovery

- If STT OOMs on a chunk, the orchestrator halves chunk size, restarts the chunk, and emits a `chunk.fallback` event. This is the auto-fallback chunking in the project requirements.
- A playlist `pause` sets a flag in SQLite; the orchestrator stops after the current job finishes and the remaining siblings stay in `pending`. `resume` flips it back.
- A back-end crash mid-job is recovered on restart: jobs in `transcribing`/`summarizing` go back to `pending`; jobs that have `transcript.json` and a `summary_state` resume from the last persisted step rather than re-running it.

### Why an in-process job runner, not Celery/RQ

- One user, one machine, no need for a separate worker process or broker.
- Celery needs Redis or RabbitMQ. RQ needs Redis. The user wants a single-command launch with no extra services.
- A persistent SQLite-backed queue + one Python `ThreadPoolExecutor` (or two — one CPU-bound for STT, one GPU-bound shared with the LLM) is enough. The state machine is the only complexity worth having.
- This also makes the back-end trivially restartable: jobs survive because they're in SQLite, not in memory.

### Why a WebSocket (and not SSE)

- We need bidirectional traffic eventually: the front-end will want to send "cancel this job" or "rename this speaker live" without an extra round trip.
- The browser `EventSource` API is server-push only and has poorer reconnect semantics.
- A single WebSocket per client multiplexing multiple job IDs via the broadcaster is simple and matches the "navigate away, return to status" requirement.

## Patterns to Follow

### Pattern 1: Adapter-per-model

Each model family (STT, diarize, LLM) is wrapped in a small interface. The orchestrator talks to the interface, never to a library directly.

```python
# app/models/stt/base.py
class STTAdapter(Protocol):
    name: str
    def transcribe_chunks(self, manifest: ChunkManifest) -> list[Segment]: ...
    def supports_language_detection(self) -> bool: ...

# app/models/stt/faster_whisper.py
class FasterWhisperAdapter:
    name = "faster-whisper"
    def __init__(self, model_id: str, backend: GpuBackend): ...
```

Swapping Whisper for whisper.cpp, or pyannote for a NeMo diarizer, is a matter of adding a class.

### Pattern 2: GPU backend as data, not branching

`app/models/backend.py` exposes a single `GpuBackend` enum (`CUDA`, `ROCM`, `CPU`) chosen once on first run and stored in `settings.json`. Adapters receive it as a constructor argument and do their own one-time setup (`torch.cuda.set_device`, `CT2_FORCE_CUDA_AMD_TARGET`, llama.cpp `n_gpu_layers`).

```python
class GpuBackend(Enum):
    CUDA = "cuda"
    ROCM = "rocm"
    CPU = "cpu"

def detect() -> GpuBackend:
    if torch.cuda.is_available():
        return GpuBackend.CUDA  # ROCm surfaces as cuda in torch>=2.1
    if "ROCM_PATH" in os.environ or _has_rocm_lib():
        return GpuBackend.ROCM
    return GpuBackend.CPU
```

The key insight: with `torch 2.x`, ROCm is exposed as a CUDA device. `faster-whisper` (CTranslate2) compiles ROCm wheels that work via the same code path as CUDA with an env var. `llama-cpp-python` exposes `n_gpu_layers` and works against either via the same binary when built with the right backend. So the *code* doesn't branch per platform — it branches once on detection and the rest is configuration.

### Pattern 3: Per-job working directory

Every job owns a folder. Stage outputs are real files on disk, not blobs in SQLite. The DB row is the index, the folder is the truth. This makes "re-run only the summary step" and "export the whole job" trivial, and it makes crash recovery obvious: if `transcript.json` exists, the STT stage is done.

### Pattern 4: Settings as a typed store, not a dict

`settings.json` is loaded into a Pydantic model. Quality preset maps to a recommended model triple via a small lookup table; per-category override replaces individual entries. GPU detection writes initial values; the user can change them later.

```python
class QualityPreset(str, Enum):
    SMALL = "small"        # fits 6 GB VRAM
    BALANCED = "balanced"  # fits 8 GB VRAM (laptop default)
    LARGE = "large"        # fits 16 GB VRAM (desktop default)

PRESETS = {
    QualityPreset.BALANCED: Models(
        stt=" Systran/faster-whisper-medium",
        diarize="pyannote/speaker-diarization-3.1",
        llm="qwen2.5-7b-instruct-q4_k_m.gguf",
    ),
    ...
}
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: One huge FastAPI handler that does everything

The temptation is to write `POST /jobs` that downloads, chunks, transcribes, diarizes, and summarizes inline. This blocks the request thread, can't be paused, can't report progress, and can't survive a restart. Keep the API thin; push work into the orchestrator and return a job ID immediately.

### Anti-Pattern 2: Loading all models at boot

On the 8 GB laptop, the LLM at q4_k_m + Whisper medium + pyannote will not all fit. Load on first use, unload when idle (or use a least-recently-used policy on the GPU). The user can opt into "keep all models warm" in settings if they have the VRAM.

### Anti-Pattern 3: Per-platform code branches in adapters

Don't write `if backend == ROCM: use_rocm_specific_code_path()`. With modern PyTorch + CTranslate2 + llama.cpp, the same code works. The right place to vary behavior is at model load time (env vars, device assignment) — not at inference time.

### Anti-Pattern 4: Storing transcripts only in SQLite

Long video transcripts can be megabytes. SQLite is fine for indices and metadata; raw transcript JSON lives in the job's folder. The DB row references the file path. This also makes the user data exportable by copying one folder.

### Anti-Pattern 5: Re-downloading models every time the user changes the quality preset

Model manager caches by content hash. The settings point to model IDs; the manager resolves ID -> local path and downloads only if missing. The user can pre-warm a model from the settings panel.

## Scalability Considerations

This is a single-user local app, so "scalability" mostly means "fits in VRAM and runs without freezing the UI."

| Concern | Single short video | 3-hour video | 20-video playlist |
|---------|--------------------|--------------|-------------------|
| Memory | One model in VRAM at a time; chunked STT | Same — chunking makes memory constant | One job at a time; queue serializes |
| Disk | One folder, ~50 MB transcript | Same — chunks are deleted after stitching | N folders, model weights shared, ~50 MB each |
| UI responsiveness | WebSocket pushes progress | Same | Same; queue shows ETA across siblings |
| GPU utilization | STT saturates the GPU; LLM waits | Same; chunking overlaps with diarize | One job's worth at a time |
| Failure recovery | Re-run the job | Re-run from last persisted stage; chunks reused | Skip completed children, resume pending |

### Concrete VRAM budget for the 8 GB laptop (default `BALANCED` preset)

| Model | Approx VRAM | Notes |
|-------|-------------|-------|
| faster-whisper medium (fp16) | ~5 GB | STT |
| pyannote 3.1 | ~1-2 GB | Diarize, runs after STT, can share |
| qwen2.5-7b q4_k_m (llama.cpp) | ~5-6 GB | LLM, runs after both |
| Headroom | ~2 GB | OS, ffmpeg, browser |

Loading two of the three at once on 8 GB is risky. The orchestrator should run STT, unload, then diarize (or share via the same model manager with an LRU policy). This is a model-manager concern, not an architecture one.

## Suggested Build Order

The build order is driven by what each component *blocks*. The orchestrator and the GPU/backend abstraction are the trunk; everything else is a branch off it.

1. **Back-end skeleton + storage** — FastAPI app, SQLite migrations, settings store, job DB schema, `data/` layout. Nothing useful yet, but it's the only thing every other component imports.
2. **GPU backend detection + model manager** — Detect CUDA/ROCm, write to `settings.json`, verify model directory, stub download. Without this, no model code can run.
3. **STT adapter (faster-whisper) + chunker** — First end-to-end pipeline: file in, transcript out, no diarization, no summary, no WebSocket. This validates the GPU abstraction more cheaply than a full pipeline.
4. **Job orchestrator + persistent queue + WebSocket progress** — Wrap the STT-only pipeline in a job, push progress events, survive a restart. This is the longest single piece because it's the spine of the app.
5. **Local file ingest + history UI** — Drag-and-drop works end-to-end, transcript displays, history list shows the job. This is the first demoable milestone.
6. **YouTube ingest (single video, then playlist)** — Add `yt-dlp` integration, ffmpeg-based audio extraction, playlist fan-out, pause/resume.
7. **Diarization adapter** — Add pyannote, align to existing transcript, emit speaker-labelled segments. UI: speaker chips, bulk rename, per-line reassignment.
8. **LLM adapter + summary templates** — llama-cpp-python + the four built-in templates, multi-select, per-type Markdown files.
9. **Transcript editor + find/replace + export** — Inline editing, speaker find/replace, Markdown export of transcript + summaries.
10. **Settings panel + quality preset + per-category overrides** — Wire the preset table, model swap, GPU backend re-detect. Last because it touches everything; building it last means the rest of the app is stable enough to expose the right controls.

### Why this order

- Steps 1-2 have no dependencies and are necessary for every other step.
- Step 3 is the cheapest possible end-to-end check that the GPU abstraction works on both machines. Doing it before the orchestrator means if Whisper blows up, the failure is in a 200-line script, not a 2000-line system.
- Step 4 turns the working script into the architecture. Once the orchestrator and queue exist, every later feature is "add a stage."
- Steps 5-9 are the user-visible features, ordered by user-value density: upload first (most common case), then YouTube (the second most common), then diarize (the feature that needs the most UI work), then summarize (which depends on the transcript existing), then polish.
- Step 10 is last because it exposes everything to the user; you want the rest of the app to be stable when you give them the levers.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Process split (React + FastAPI) | HIGH | Project requirement; well-trodden pattern |
| In-process queue vs Celery | MEDIUM-HIGH | Right for one user, one machine; would need to revisit if multi-user ever lands |
| SQLite for job state | HIGH | Standard, persistent, no extra service |
| WebSocket vs SSE | MEDIUM-HIGH | WebSocket is the more future-proof pick; SSE would also work |
| GPU abstraction via torch + CTranslate2 + llama.cpp | MEDIUM | The libraries *do* work this way in 2026, but pin the versions and verify both targets in step 3 before committing |
| Chunking + auto-fallback | HIGH | Standard pattern, well-supported by faster-whisper and VAD libraries |
| `yt-dlp` for YouTube ingest | HIGH | De-facto standard; survives YouTube changes better than alternatives |
| Build order | MEDIUM-HIGH | Sensible default; reorder if a specific stage turns out to be much harder than expected |

## Gaps to Address

- **VRAM budgeting for diarize + LLM concurrent load on 8 GB** — needs measurement in step 3 / step 7. May force stricter "one model at a time" semantics in the model manager.
- **First-run UX of model download** — gigabytes of model files; the user needs a clear "downloading 4.2 / 7.8 GB" indicator and the ability to defer it. Not architectural, but a settings-panel concern that overlaps with step 10.
- **HuggingFace token for pyannote** — pyannote 3.1 requires accepting a license and supplying a token. The first-run flow needs to prompt for it once and store it. Affects step 7.
- **Playlist pause semantics** — the project says "user can pause and resume"; the simplest semantics are "finish the current child, then stop" but a "hard stop now" UX is also reasonable. Decide during step 6.
- **Export format** — Markdown is in the requirements; PDF / DOCX are tempting but out of scope unless validated.
- **Concurrency between STT and diarize** — diarize needs the full audio, STT is per-chunk. They could overlap, but the 8 GB machine can't hold both. Decide whether the desktop runs them in parallel.

## Sources

- `faster-whisper` docs: CTranslate2 backend, ROCm and CUDA support via PyTorch device.
- `pyannote.audio` 3.x: speaker diarization pipeline, HuggingFace token gating.
- `llama-cpp-python`: `n_gpu_layers` config, ROCm and CUDA build targets, GGUF model format.
- `yt-dlp`: playlist expansion, audio format selection, postprocessor for audio extraction.
- `Silero VAD`: chunk boundary detection for long-form audio.
- Project context: `.planning/PROJECT.md` (hardware, requirements, key decisions).
