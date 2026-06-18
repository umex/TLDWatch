# Roadmap: TranscriptionAndNotes

## Overview

A local-first web app that turns any video (local file, YouTube URL, or YouTube playlist) into a speaker-aware transcript plus four-shape structured summaries — all on the user's own GPU, with no cloud calls. Build proceeds from the back-end skeleton and storage foundation, through GPU detection and the model manager, into a cheap end-to-end STT spike, then layers the job orchestrator, user-visible features (local file ingest, YouTube, diarization, summarization, editor), and finishes with the settings panel that exposes the levers once the rest of the app is stable.

## Phases

- [x] **Phase 1: Back-end Skeleton + Storage + Data Layout** - FastAPI service, SQLite WAL, per-job filesystem layout, Pydantic schema, OpenAPI surface; the foundation every other component imports. (completed 2026-06-14)
- [ ] **Phase 2: GPU Backend Detection + Model Manager** - First-run CUDA/ROCm/CPU detection, model download with SHA verification, lazy load + idle unload, single-model VRAM discipline.
- [ ] **Phase 3: STT Adapter + Audio Chunker + Standalone CLI** - faster-whisper adapter, long-audio chunker with OOM fallback, language auto-detect, a runnable CLI that proves the GPU abstraction end-to-end.
- [ ] **Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress** - In-process job runner, SQLite-backed queue with restart persistence, state machine with file-as-truth, real-time progress broadcast.
- [ ] **Phase 5: Local File Ingest + History UI + 3-Pane Layout** - Streaming drag-and-drop upload, history list (left pane), transcript view (middle), summary view (right), active-line highlight, no embedded video.
- [ ] **Phase 6: YouTube Ingest + Sequential Playlist Queue** - yt-dlp audio download, single-URL submit, playlist fan-out with pause/resume, timestamp link-out to YouTube.
- [ ] **Phase 7: Diarization Adapter + Speaker Rename Cluster** - pyannote adapter (optional, HF-token-gated), default Person N labels, bulk-rename via chips, per-line reassign, find-and-replace speaker.
- [ ] **Phase 8: LLM Adapter + Four Summary Templates + Multi-Select** - llama-cpp-python adapter, Qwen2.5-Instruct GGUF, four typed schemas (meeting, investment, concept, quick recap), multi-select per job, schema-validate + retry.
- [ ] **Phase 9: Transcript Editor + Find/Replace + Inline Edit Persistence + Export Polish** - Inline text edit, per-line speaker dropdown, find-and-replace text, re-export with edits applied, Markdown export with speaker labels + timestamps.
- [ ] **Phase 10: Settings Panel + Quality Preset + Per-Category Overrides + Diagnostics + First-Run Card** - Settings UI for quality preset, per-category model override, HF token, backend indicator, per-backend smoke test, first-run info card.

## Phase Details

### Phase 1: Back-end Skeleton + Storage + Data Layout

**Goal**: Establish the back-end service skeleton, persistent storage, and per-job filesystem layout that every later component imports.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: HW-01
**Success Criteria** (what must be TRUE):

  1. A FastAPI app boots locally and serves an OpenAPI schema that the React front-end can consume.
  2. SQLite database is created in WAL mode with a versioned schema and idempotent migration path.
  3. A `data/jobs/<job_id>/` directory per job is created on demand and used as the source of truth for stage outputs.
  4. Pydantic models exist for job state, transcript segments, summary outputs, and settings, and are shared between back-end code and the generated TypeScript types.
  5. The back-end has a clean `app.api`, `app.jobs`, `app.storage`, `app.models` boundary; nothing else in the codebase may import a model library directly.

**Plans**: TBD
Plans:
**Wave 1**

- [x] 01-01: FastAPI service + OpenAPI surface

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02: SQLite WAL + schema migrations + Pydantic models

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03: Per-job filesystem layout + file-as-truth conventions

### Phase 2: GPU Backend Detection + Model Manager

**Goal**: The system auto-detects CUDA vs ROCm vs CPU on first run, persists the choice, and owns the lifecycle of every local model on disk and in VRAM.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: HW-02, HW-03, HW-04, HW-07, HW-09
**Success Criteria** (what must be TRUE):

  1. First run on the laptop silently writes `settings.json` with `backend: CUDA`; first run on the desktop writes `backend: ROCM` or `CPU` based on a real GPU-burn test, with no user-facing wizard.
  2. Default model set (faster-whisper int8 large-v3 + pyannote + Qwen2.5 7B Q4_K_M) fits within 8 GB laptop VRAM as a planning constraint, with per-model VRAM budget logged on load.
  3. Model manager downloads a model, verifies size and (where available) SHA256, exposes a download log in the UI, and supports resume after crash.
  4. Loading a model blocks if it would push past 85% of available VRAM; unload is explicit on idle, with a "what's currently in VRAM" indicator exposed for diagnostics.
  5. No two models are resident in VRAM concurrently unless the user explicitly opts in via a settings toggle that is hidden by default.

**Plans**: 3 plans

Plans:

**Wave 1**

- [x] 02-01: First-run GPU detect + burn-in test + settings.json write (autonomous; HW-02, HW-03)

**Wave 2** *(blocked on Wave 1 completion; 02-02 and 02-03 run in parallel)*

- [x] 02-02: Model manager (download, verify, lazy load, idle unload, VRAM probe) (autonomous; HW-02, HW-04, HW-07, HW-09)
- [ ] 02-03: ROCm-on-Windows spike (whisper.cpp ROCm build + llama.cpp HIP build, document fallback) (non-autonomous; HW-03)

### Phase 3: STT Adapter + Audio Chunker + Standalone CLI

**Goal**: A runnable STT pipeline that takes an audio file, transcribes it with faster-whisper, handles long audio via chunking with OOM fallback, and proves the GPU abstraction works on both machines.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: INGEST-05, INGEST-06, TRANS-01
**Success Criteria** (what must be TRUE):

  1. A standalone CLI takes a local audio or video file path and writes `transcript.json` with timestamped segments and detected language.
  2. Long audio (>30 min) is split into chunks with overlap, transcribed, and stitched into a single continuous transcript; if a chunk OOMs, the chunker halves the chunk size and retries.
  3. Spoken language is auto-detected from the first 30 s of audio and recorded in the output.
  4. The STT adapter is invoked only through a `STTAdapter` Protocol — the orchestrator code cannot import faster-whisper or whisper.cpp directly.
  5. The CLI runs to completion on both the laptop (CUDA) and the desktop (ROCm or CPU fallback) without code changes.

**Plans**: TBD

Plans:

- [ ] 03-01: STT adapter (faster-whisper int8) + version pin + int8 verification
- [ ] 03-02: Audio chunker (window + overlap, OOM halve-and-retry)
- [ ] 03-03: Standalone CLI (file in, transcript.json out, language detect)

### Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress

**Goal**: The job state machine, persistent queue, and real-time progress broadcast exist as the spine of the app, so every later feature is just "add a stage."
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: JOB-02, JOB-04, JOB-05, JOB-06
**Success Criteria** (what must be TRUE):

  1. Submitting a job returns a job ID; the job moves through `queued → ingesting → transcribing → done` with atomic transitions guarded by stage-output files on disk.
  2. The job queue persists across back-end restarts — queued and in-flight jobs are re-joinable, with the orchestrator inferring the resume point from existing files.
  3. A WebSocket endpoint broadcasts per-job progress events (current stage, percent, ETA) that the front-end can subscribe to.
  4. The user can cancel a queued or running job; cancellation is idempotent and the job's partial files are cleaned up deterministically.
  5. The double-submit problem is handled — a `POST /jobs` with the same idempotency key returns the existing job ID instead of creating a duplicate.

**Plans**: TBD

Plans:

- [ ] 04-01: State machine + file-as-truth transitions
- [ ] 04-02: SQLite-backed queue + restart resume + cancel
- [ ] 04-03: WebSocket progress pub/sub + idempotent submit

### Phase 5: Local File Ingest + History UI + 3-Pane Layout

**Goal**: The user can drag a local video file into the browser, watch it process in the background, and see a working 3-pane layout (history | transcript | summary) — without an embedded video player.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: INGEST-01, JOB-03, UI-01, UI-02, UI-03
**Success Criteria** (what must be TRUE):

  1. Drag-and-drop or file-picker upload streams a multi-gigabyte file to disk without holding it in memory; the back-end writes directly to `data/jobs/<id>/source.ext`.
  2. The main working layout is 3-pane: history (left) | transcript (middle) | summary (right), with no embedded video player anywhere.
  3. Completed jobs appear in the history pane and remain clickable; selecting one loads its transcript and summaries.
  4. The currently active transcript line is highlighted based on scroll position so the user can locate context.
  5. The user can re-open a completed job, see its existing transcript, and re-export it.

**Plans**: TBD

Plans:

- [ ] 05-01: Streaming upload endpoint + back-end ingest stage
- [ ] 05-02: React app shell + 3-pane layout + drop zone
- [ ] 05-03: History list + job detail view + active-line highlight

### Phase 6: YouTube Ingest + Sequential Playlist Queue

**Goal**: The user can submit a single YouTube URL or a playlist URL; the app downloads the audio locally, processes it from scratch, and links timestamps back out to YouTube.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: INGEST-02, INGEST-03, INGEST-04, JOB-01, TRANS-08
**Success Criteria** (what must be TRUE):

  1. Submitting a single YouTube video URL causes the app to download audio locally and process it from scratch — YouTube auto-captions are never used as the transcript source.
  2. Submitting a YouTube playlist URL fans the playlist out into a sequential queue of child jobs; children run one at a time in submission order.
  3. The user can pause a running playlist queue; pause finishes the current child, then stops; resume picks up at the next child.
  4. For YouTube jobs, every transcript timestamp is rendered as a link that opens YouTube at `?t=<seconds>` in a new tab.
  5. yt-dlp's state for age-gated, region-locked, or partially unavailable videos is handled gracefully — the child job fails with a clear reason, the playlist continues with the remaining children, and the UI shows the failure.

**Plans**: TBD

Plans:

- [ ] 06-01: yt-dlp integration + audio extraction + format pin
- [ ] 06-02: YouTube URL submit + timestamp link-out
- [ ] 06-03: Playlist fan-out + sequential queue + pause/resume

### Phase 7: Diarization Adapter + Speaker Rename Cluster

**Goal**: Speaker-diarized transcripts are produced when multiple speakers are detected, with "Person 1" / "Person 2" labels by default and rich rename controls on top of the transcript.
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: TRANS-02, TRANS-03, TRANS-04, TRANS-05, TRANS-07
**Success Criteria** (what must be TRUE):

  1. When the diarization adapter detects more than one speaker, transcript segments carry a `speaker` label and the default values are "Person 1", "Person 2", ... in first-appearance order.
  2. A speaker chip bar at the top of the transcript shows each distinct speaker; clicking a chip and entering a name bulk-renames that speaker across the entire transcript.
  3. A find-and-replace speaker control lets the user replace one speaker label with another across the whole transcript.
  4. Each transcript line exposes a per-line speaker dropdown so the user can reassign a mislabeled segment without re-running diarization.
  5. Diarization is opt-in and disabled by default; the UI shows a non-blocking banner "Speaker labels are disabled. Add a HuggingFace token in Settings to enable." with a one-click link to the token field, and jobs without a token complete successfully without speaker labels.

**Plans**: TBD

Plans:

- [ ] 07-01: pyannote adapter + HF token gating + non-blocking banner
- [ ] 07-02: Speaker chip bar + bulk rename
- [ ] 07-03: Per-line speaker reassign + find-and-replace speaker

### Phase 8: LLM Adapter + Four Summary Templates + Multi-Select

**Goal**: Users can multi-select from four built-in summary templates per job, and the local LLM produces structured outputs that match each template's typed schema.
**Mode:** mvp
**Depends on**: Phase 7
**Requirements**: SUM-01, SUM-02, SUM-03, SUM-04
**Success Criteria** (what must be TRUE):

  1. The job submission UI exposes four built-in summary templates — meeting (action items, decisions, brief recap), investment (pros, cons, tickers, thesis), concept (concepts taught, how-to steps, glossary), quick recap (2-3 sentence TL;DR) — and the user can select zero, one, or many.
  2. Each template has a typed schema (sections with named fields) that the back-end validates the LLM output against; failures trigger at most 2 retries with a "you missed section X" follow-up prompt.
  3. The LLM adapter loads via `LLMAdapter` Protocol; llama-cpp-python and the GGUF model are never imported outside `app/models/llm`.
  4. The default model set fits the 8 GB laptop budget; the desktop can opt into a larger model via a per-category override in settings (Phase 10) without code changes.
  5. Summary output is rendered in the right-hand pane as structured, typed fields (not raw prose), and persists with the job so re-opening shows the same structured view.

**Plans**: TBD

Plans:

- [ ] 08-01: llama-cpp-python adapter + Qwen2.5 GGUF + VRAM discipline
- [ ] 08-02: Four typed schemas + validators + retry loop
- [ ] 08-03: LLM benchmark on laptop + GBNF grammar prototypes (one per template)

### Phase 9: Transcript Editor + Find/Replace + Inline Edit Persistence + Export Polish

**Goal**: Users can polish transcripts inline, search and replace text, and export the transcript plus selected summaries to Markdown with speaker labels and timestamps.
**Mode:** mvp
**Depends on**: Phase 8
**Requirements**: TRANS-06, EXPORT-01, EXPORT-02, EXPORT-03
**Success Criteria** (what must be TRUE):

  1. Any transcript line's text can be edited inline; the change persists to the back-end (PATCH endpoint) and survives a refresh or re-open from history.
  2. A find-and-replace text control lets the user rewrite a string across the whole transcript with a single action.
  3. Markdown export of a job produces a single `.md` file containing the transcript (with speaker labels and timestamps) followed by the selected summaries rendered as their typed sections.
  4. Re-exporting from history applies the current edits — the export reflects the latest state, not the original transcription output.
  5. Edits to transcripts do not break speaker assignment, timestamp ordering, or downstream re-summarization if the user later re-runs the summary stage.

**Plans**: TBD

Plans:

- [ ] 09-01: Inline transcript edit + PATCH persistence
- [ ] 09-02: Find-and-replace text + per-line speaker dropdown UX polish
- [ ] 09-03: Markdown export (transcript + summaries, edits applied)

### Phase 10: Settings Panel + Quality Preset + Per-Category Overrides + Diagnostics + First-Run Card

**Goal**: A settings panel that exposes quality preset, per-category model overrides, the HF token, backend indicator, and per-backend diagnostics — built last so the rest of the app is stable when the user gets the levers.
**Mode:** mvp
**Depends on**: Phase 9
**Requirements**: HW-05, HW-06, HW-08
**Success Criteria** (what must be TRUE):

  1. The settings panel exposes a "quality preset" (small / balanced / large); choosing a preset auto-picks compatible model variants per category and writes the result to `settings.json`.
  2. The user can override the model selection per category (transcription / diarization / LLM) from the settings panel; overrides win over the preset and are persisted.
  3. A first-run card appears once on a fresh install showing the active GPU backend, the default model set, and a "Test" button per category that runs a smoke test and reports measured tokens/sec.
  4. The user can opt into a larger model on the 16 GB desktop; the opt-in shows a warning that the default set is designed for the 8 GB laptop and the larger set will use ~10 GB VRAM on the desktop.
  5. The HF token field in settings accepts a pasted token, has a "Test token" button, and an invalid token shows "Token rejected — speaker labels disabled" without blocking the rest of the app.

**Plans**: TBD

Plans:

- [ ] 10-01: Quality preset + per-category override UI + persistence
- [ ] 10-02: First-run info card + per-backend smoke test + "what's in VRAM" indicator
- [ ] 10-03: HF token field + test + opt-in larger model warning

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Back-end Skeleton + Storage + Data Layout | 3/3 | Complete   | 2026-06-14 |
| 2. GPU Backend Detection + Model Manager | 0/3 | Planned (3 plans) | - |
| 3. STT Adapter + Audio Chunker + Standalone CLI | 0/3 | Not started | - |
| 4. Job Orchestrator + Persistent Queue + WebSocket Progress | 0/3 | Not started | - |
| 5. Local File Ingest + History UI + 3-Pane Layout | 0/3 | Not started | - |
| 6. YouTube Ingest + Sequential Playlist Queue | 0/3 | Not started | - |
| 7. Diarization Adapter + Speaker Rename Cluster | 0/3 | Not started | - |
| 8. LLM Adapter + Four Summary Templates + Multi-Select | 0/3 | Not started | - |
| 9. Transcript Editor + Find/Replace + Inline Edit Persistence + Export Polish | 0/3 | Not started | - |
| 10. Settings Panel + Quality Preset + Per-Category Overrides + Diagnostics + First-Run Card | 0/3 | Not started | - |

**Coverage:** 38/38 v1 requirements mapped
**Granularity:** standard
**Mode:** mvp

---
*Roadmap created: 2026-06-11*
