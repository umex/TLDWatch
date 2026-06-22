# Requirements: TranscriptionAndNotes

**Defined:** 2026-06-11
**Core Value:** Drop in any video and get a clean, speaker-aware transcript plus summaries shaped for the content type — without it ever leaving the machine.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Ingest

- [ ] **INGEST-01**: User can submit a local video file via drag-and-drop in the browser
- [ ] **INGEST-02**: User can submit a single YouTube video URL
- [ ] **INGEST-03**: User can submit a YouTube playlist URL
- [ ] **INGEST-04**: App downloads YouTube audio locally and processes it from scratch (no reliance on YouTube's auto-captions)
- [x] **INGEST-05**: App handles long videos by chunking audio automatically, with fallback when a single-shot job would OOM
- [x] **INGEST-06**: App auto-detects the spoken language from the audio

### Job Management

- [ ] **JOB-01**: Playlists are processed sequentially in a single queue; user can pause and resume
- [x] **JOB-02**: Jobs run in the background — user can navigate away and return to status
- [ ] **JOB-03**: App persists all completed jobs to local history; user can revisit, edit, and re-export
- [ ] **JOB-04**: Job queue state persists across app restarts
- [ ] **JOB-05**: User can cancel a queued or running job
- [ ] **JOB-06**: User sees per-job progress (current stage, percent, ETA) in real time

### Transcription & Diarization

- [x] **TRANS-01**: App produces a transcript with timestamps for the entire video
- [ ] **TRANS-02**: App produces a speaker-diarized transcript when multiple speakers are detected
- [ ] **TRANS-03**: Diarized speakers are labelled "Person 1", "Person 2", etc. by default
- [ ] **TRANS-04**: User can bulk-rename a speaker (e.g. "Person 1" → "Jim") via clickable speaker chips at the top of the transcript, and all instances update
- [ ] **TRANS-05**: User can find-and-replace a speaker across the whole transcript
- [ ] **TRANS-06**: User can edit any transcript line's text inline
- [ ] **TRANS-07**: User can reassign a transcript line's speaker from a dropdown on that line (for when the AI mislabels a segment)
- [ ] **TRANS-08**: For YouTube jobs, transcript timestamps link out to YouTube at the correct offset

### Summarization

- [ ] **SUM-01**: App supports four built-in summary templates, multi-select before running:
  - Meeting / coding session — action items, decisions, brief recap
  - Investment analysis — pros, cons, tickers, thesis
  - Concept explainer / how-to — concepts taught, how-to steps, glossary
  - Quick recap — 2-3 sentence TL;DR
- [ ] **SUM-02**: User can select zero, one, or many summary types per job
- [ ] **SUM-03**: Summary outputs are structured (typed schemas) — not free-form prose
- [ ] **SUM-04**: Summary output validates against the template's expected schema; failures re-prompt the LLM

### Export

- [ ] **EXPORT-01**: User can export a job's transcript + selected summaries as Markdown
- [ ] **EXPORT-02**: User can re-export from history with edits applied
- [ ] **EXPORT-03**: Markdown export includes speaker labels and timestamps

### UI Layout

- [ ] **UI-01**: Main working layout is 3-pane: history (left) | transcript (middle) | summary (right)
- [ ] **UI-02**: No embedded video player; YouTube jobs show a "open in YouTube" link at the current timestamp
- [ ] **UI-03**: Active transcript line is highlighted based on current scroll position (for local files only)

### Hardware & Models

- [ ] **HW-01**: Front-end (React) and back-end (Python) are separated and communicate via a job API
- [x] **HW-02**: Transcription, diarization, and LLM summarization all run on local models on the user's GPU
- [x] **HW-03**: App auto-detects GPU (NVIDIA CUDA vs AMD ROCm vs CPU fallback) on first run and configures backends silently
- [x] **HW-04**: App downloads its own models on first run; user can swap model variants in settings
- [ ] **HW-05**: User can configure a "quality preset" (e.g. small / balanced / large) in settings; the app picks compatible model variants automatically
- [ ] **HW-06**: User can override the model selection per category (transcription / diarization / LLM) from a settings panel
- [x] **HW-07**: Default model set fits the 8 GB laptop VRAM budget
- [ ] **HW-08**: User can opt into a larger model on the 16 GB desktop via settings
- [x] **HW-09**: Per-job VRAM discipline: models load on demand, unload when idle; no concurrent multi-model residency

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Export

- **EXPORT-V2-01**: SRT / VTT / JSON / ASS subtitle export formats

### Summarization

- **SUM-V2-01**: User-defined custom summary templates with a prompt editor
- **SUM-V2-02**: Per-segment confidence score with a "review low-confidence" view

### Discovery

- **DISC-V2-01**: AI chat with the transcript (RAG "ask the video")
- **DISC-V2-02**: Auto-generated chapter markers / key moments

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Cloud processing, cloud sync, cloud accounts | Local-only is a stated constraint; user owns the data |
| Multi-user authentication / networked access | Single user on a single machine; explicit in PROJECT.md |
| Mobile app / responsive phone UI | Desktop browser only; explicit in PROJECT.md |
| Custom user-defined summary templates in v1 | Four built-in types cover the four use cases; defer to v2 |
| Real-time live transcription of streaming audio | Input is always a finished file or URL; explicit in PROJECT.md |
| Editing the underlying video / cutting clips | This app is transcription + summarization, not a video editor |
| Translation between languages | Auto-detect transcribes in source language; no translation pass |
| Public sharing / collaboration features | Local-only, single user; explicit in PROJECT.md |
| Per-machine separate UX | Same UX on both machines; settings differ; explicit in PROJECT.md |
| First-run setup wizard | Silent GPU auto-detect on first run; laptop must remain non-intrusive |
| Telemetry, usage analytics, crash reports | No-telemetry is a stated constraint |
| Auto-update / background model refresh | User controls the timing of model downloads; settings panel has manual update button |
| Email / push notifications for job completion | Single user, in the browser tab they're already in |
| SRT / VTT / ASS subtitle export in v1 | Markdown only in v1; subtitle export deferred to v2 |
| Voice cloning / TTS output | Not a transcription feature |
| AI chat with the transcript (RAG) | Deferred to v2; four templates cover the four use cases |
| Embedded video player in v1 | 3-pane layout, no video; YouTube jobs link out |
| Auto-upload of completed jobs to cloud backup | User is responsible for backing up the data directory |
| Speaker-count input prompt | Diarization auto-detects; user can rename after the fact |
| Auto-punctuation beautification (smart quotes, em-dash) | Render the model's output; do not post-process for style |
| Multi-language transcripts on the same video | Single output language = detected source language |
| Plugin / extension API | Per-category model override already covers the real need |
| Public template marketplace | Four templates are intentional and curated |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 5 | Pending |
| INGEST-02 | Phase 6 | Pending |
| INGEST-03 | Phase 6 | Pending |
| INGEST-04 | Phase 6 | Pending |
| INGEST-05 | Phase 3 | Complete |
| INGEST-06 | Phase 3 | Complete |
| JOB-01 | Phase 6 | Pending |
| JOB-02 | Phase 4 | Complete |
| JOB-03 | Phase 5 | Pending |
| JOB-04 | Phase 4 | Pending |
| JOB-05 | Phase 4 | Pending |
| JOB-06 | Phase 4 | Pending |
| TRANS-01 | Phase 3 | Complete |
| TRANS-02 | Phase 7 | Pending |
| TRANS-03 | Phase 7 | Pending |
| TRANS-04 | Phase 7 | Pending |
| TRANS-05 | Phase 7 | Pending |
| TRANS-06 | Phase 9 | Pending |
| TRANS-07 | Phase 7 | Pending |
| TRANS-08 | Phase 6 | Pending |
| SUM-01 | Phase 8 | Pending |
| SUM-02 | Phase 8 | Pending |
| SUM-03 | Phase 8 | Pending |
| SUM-04 | Phase 8 | Pending |
| EXPORT-01 | Phase 9 | Pending |
| EXPORT-02 | Phase 9 | Pending |
| EXPORT-03 | Phase 9 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| HW-01 | Phase 1 | Pending |
| HW-02 | Phase 2 | Pending (lifecycle in 02-02; actual GPU inference in Phase 3/7/8) |
| HW-03 | Phase 2 | Complete (02-01) |
| HW-04 | Phase 2 | Complete (02-02) |
| HW-05 | Phase 10 | Pending |
| HW-06 | Phase 10 | Pending |
| HW-07 | Phase 2 | Complete (02-02) |
| HW-08 | Phase 10 | Pending |
| HW-09 | Phase 2 | Complete (02-02) |

**Coverage:**

- v1 requirements: 38 total
- Mapped to phases: 38
- Unmapped: 0 ✓

**Notes from roadmap creation (2026-06-11):**

- Mode is `mvp` — each phase is a vertical slice delivering observable user-visible or testable system behavior end-to-end, not a horizontal layer.
- Phase 5 owns the 3-pane UI shell (history | transcript | summary) with NO embedded video player; active-line highlight is per the v1 spec (local files only).
- TRANS-08 (YouTube timestamp link-out) is owned by Phase 6, paired with the YouTube ingest pipeline. There is no click-to-seek on local files in v1 — UI-03 highlight is scroll-position based.
- Settings panel is Phase 10 (last) per project guidance; per-category model overrides and quality preset ship with the rest of the app, not interleaved.
- HF-token UX (diarization opt-in banner, "Test token" button) is part of Phase 7's acceptance, not deferred.

---
*Requirements defined: 2026-06-11*
*Last updated: 2026-06-11 after roadmap creation*
