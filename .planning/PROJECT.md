# TranscriptionAndNotes

## What This Is

A local-first web app that turns video (uploaded files, YouTube URLs, or YouTube playlists) into a transcript, an optional speaker-labelled transcript, and one or more structured summaries — all processed on the user's own machine with no cloud calls. The user owns the data, the models, and the output.

## Core Value

The user can drop in any video and get back a clean, speaker-aware transcript plus summaries shaped for the content type (meeting, investment analysis, concept explainer, quick recap) — without it ever leaving the machine.

## Requirements

### Validated

- ✓ App produces a transcript with timestamps for the entire video — Phase 3 (TRANS-01)
- ✓ App handles long videos by chunking audio automatically, with fallback when a single-shot job would OOM — Phase 3 (INGEST-05)
- ✓ App auto-detects the spoken language from the audio — Phase 3 (INGEST-06)
- ✓ Jobs run in the background — user can navigate away and return to status — Phase 4 (JOB-02)
- ✓ Job queue state persists across app restarts; queued/in-flight jobs resume — Phase 4 (JOB-04)
- ✓ User can cancel a queued or running job (cooperative, non-destructive) — Phase 4 (JOB-05)
- ✓ User sees per-job progress (current stage, percent, ETA) in real time over WebSocket — Phase 4 (JOB-06)

### Active

- [ ] User can submit a local video file via drag-and-drop in the browser
- [ ] User can submit a single YouTube video URL
- [ ] User can submit a YouTube playlist URL
- [ ] App downloads YouTube audio locally and processes it from scratch (no reliance on YouTube's auto-captions)
- [ ] Playlists are processed sequentially in a single queue; user can pause and resume
- [ ] App produces a speaker-diarized transcript when multiple speakers are detected
- [ ] Diarized speakers are labelled "Person 1", "Person 2", etc. by default
- [ ] User can bulk-rename a speaker (e.g. "Person 1" → "Jim") via clickable speaker chips at the top of the transcript, and all instances update
- [ ] User can find-and-replace a speaker across the whole transcript
- [ ] User can edit any transcript line's text inline
- [ ] User can reassign a transcript line's speaker from a dropdown on that line (for when the AI mislabels a segment)
- [ ] App supports multiple summary templates per video, multi-select before running:
  - Meeting / coding session — action items, decisions, brief recap
  - Investment analysis — pros, cons, tickers, thesis
  - Concept explainer / how-to — concepts taught, how-to steps, glossary
  - Quick recap — 2-3 sentence TL;DR
- [ ] App persists all completed jobs to local history; user can revisit, edit, and re-export
- [ ] User can export a job's transcript + summaries as Markdown
- [ ] Front-end (React) and back-end (Python) are separated and communicate via a job API
- [ ] Transcription, diarization, and LLM summarization all run on local models on the user's GPU
- [ ] App downloads its own models on first run; user can swap model variants in settings
- [ ] App auto-detects GPU (NVIDIA CUDA vs AMD ROCm) on first run and configures backends silently
- [ ] User can configure a "quality preset" (e.g. small / balanced / large) in settings; the app picks compatible model variants automatically
- [ ] User can override the model selection per category (transcription / diarization / LLM) from a settings panel

### Out of Scope

- Cloud processing, cloud sync, cloud accounts — everything stays local
- Multi-user authentication / networked access — single user on a single machine
- Mobile app — desktop browser only
- Custom user-defined summary templates in v1 — only the four built-in types ship
- Real-time live transcription of streaming audio — input is always a file or URL pointing to a finished video
- Editing the underlying video / cutting clips — this app is transcription + summarization, not a video editor
- Translation between languages — auto-detect transcribes in the source language, no translation pass
- Public sharing / collaboration features on saved jobs
- A separate "model per machine" UI in v1 — the same model set works on both machines; per-machine model overrides live in a settings panel, not a separate UX

## Context

- **Two hardware targets:**
  - Desktop: AMD Ryzen 5 5700X3D, 32 GB DDR4, AMD Radeon 6800 XT (16 GB VRAM, ROCm)
  - Laptop: NVIDIA RTX 2000 Ada (8 GB VRAM, CUDA). This is a working machine — detection and configuration must be silent and not intrusive.
- **Why two machines:** the laptop is for ad-hoc work and is more constrained. The desktop has the GPU headroom for bigger models. The user wants the option to use a larger LLM on the desktop and a smaller, faster one on the laptop, but doesn't want a separate UX for it — just a settings toggle.
- **No cloud, no telemetry.** Every model runs on the user's box. The first-run model download is the only network action.
- **Use cases driving the design:** meeting recordings, coding sessions, learning/tech content, investment/finance videos. These four drove the four built-in summary templates.
- **Multiple summaries on one video:** meeting + concept explainer on the same video is a real use case. The app must support multi-select summary types per job, not one-summary-per-video.
- **No size limit, but with safety:** very long videos must not OOM. The auto-fallback chunking approach is the safety valve.
- **Laptop is the constraint:** because it must work on the 8 GB RTX 2000 Ada, the default model set has to fit there. The 6800 XT is "fast / spare VRAM" relative to the laptop, not "needs a different model." Per-machine overrides are settings, not defaults.

## Constraints

- **Hardware:** Must work on the user's two machines. Default model set must fit the 8 GB laptop. The 16 GB desktop is the "more headroom" machine.
- **Laptop is non-negotiable:** the user is explicit that GPU detection and config on the laptop must be silent — no first-run wizards, no error dialogs about CUDA versions, no per-machine setup steps.
- **Local-only:** No third-party API calls during processing. Model downloads happen from public sources (HuggingFace etc.) but the user controls the timing.
- **Separation of concerns:** Front-end and back-end are two distinct codebases that talk over HTTP/WebSocket. The back-end is the only thing that touches models and the filesystem.
- **No vendor lock-in on a specific model:** Should support swapping Whisper for a faster/smaller variant, pyannote for a different diarizer, etc. via config, without code changes.
- **Job queue persistence across restarts:** A user can close the app and come back; queued and in-flight jobs should resume or at least be re-joinable.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python + React stack | Best local-model ecosystem on the Python side; clean separation between ML-heavy back-end and a typical SPA front-end. | — Pending |
| Background jobs with persistence | Long videos + playlists mean any synchronous request would time out. Jobs let the user close the tab. | — Pending |
| YouTube audio is always downloaded and processed from scratch | User wants no size limit and consistency with local video handling; no dependency on YouTube captions being accurate or even present. | — Pending |
| Four built-in summary templates, no custom editor in v1 | Use cases are concrete and well-shaped; building a prompt editor before validating the templates would be premature. | — Pending |
| Multi-select summary types per job | One video can be both a meeting and a concept explainer; users should not have to re-run the job for each. | — Pending |
| Auto-detect language by default | Most workflows don't know the language upfront; auto-detect is the right default. | ✓ Delivered Phase 3 |
| Auto-fallback chunking for long videos | VRAM is the hard ceiling on both machines; chunking is the only way to guarantee a 2-3 hour video doesn't OOM. | ✓ Delivered Phase 3 (split-both-halves + FLOOR_SECONDS=60) |
| App downloads its own models | Removes a setup step; user just runs the app and it pulls what it needs. | — Pending |
| Single user, no auth | Removes a whole class of complexity; explicit out-of-scope. | — Pending |
| Clickable speaker chips + per-line reassignment | Two rename modes: bulk "Person 1 → Jim" and per-line fix when the AI mislabels a segment. | — Pending |
| Silent GPU auto-detect on first run | Laptop is a working machine — user explicitly does not want intrusive setup. | — Pending |
| Quality preset (small / balanced / large) + per-category model override | Default model set fits the 8 GB laptop. Desktop can opt into a larger LLM. Settings panel, not a separate UX. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-23 after Phase 4*
