# Feature Landscape

**Project:** TranscriptionAndNotes
**Domain:** Local-first video transcription + summarization web app
**Researched:** 2026-06-11
**Mode:** Ecosystem (features dimension)
**Overall confidence:** MEDIUM (research tools unavailable; derived from prior knowledge of the Whisper / pyannote / local-LLM ecosystem as of early 2026, cross-checked against PROJECT.md's stated decisions)

## Executive Summary

The local transcription + summarization space has converged on a clear set of table-stakes features: drag-and-drop file ingest, timestamped transcript segments, speaker diarization with rename, basic export, and a job queue with progress. Most competitors (WhisperLive, MacWhisper, Aiko, WhisperDesktop, Buzz, VideoLingo, scribe-from-yt) cluster around these. The user's PROJECT.md already explicitly commits to most of them.

The differentiator surface for a *single-user, local, four-template* app is small but real: (1) multi-select summary templates per job, (2) YouTube playlist queueing with pause/resume and persistence, (3) silent GPU auto-detect across CUDA and ROCm, (4) chunked long-video processing with OOM fallback, (5) model-swap settings that respect a default-that-fits-the-laptop constraint.

The anti-feature surface is the most important output of this research. Transcription apps are bloated with cloud sync, accounts, mobile, live-streaming, translation, video editing, and custom-prompt builders. Most of these are explicitly out of scope per PROJECT.md. We extend that list with features that commonly creep in but don't fit this product.

---

## Table Stakes

Features users of *any* transcription app expect. Missing these makes the product feel broken or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| Drag-and-drop file upload in browser | Every modern web tool uses it; click-to-pick is table stakes but not enough | Low | PROJECT.md Active #1 |
| YouTube URL paste-and-submit | Half the use cases are YouTube; without it the app is half a product | Medium | Requires yt-dlp + audio extraction. PROJECT.md Active #2 |
| Timestamped transcript segments | A transcript without clickable timestamps is not a transcript | Low | PROJECT.md Active #8 |
| Click timestamp to seek video playback | Without this, timestamps are decorative | Medium | Implies an embedded `<video>` player tied to transcript scroll |
| Job queue with per-job progress | Long videos + playlists make sync impossible | Medium | PROJECT.md Active #15 |
| History of completed jobs with re-open | Users must be able to find old transcripts; otherwise the app is a one-shot tool | Medium | PROJECT.md Active #11 |
| Local export of transcript (Markdown minimum) | "Did the work, can't take it home" = unusable | Low | PROJECT.md Active #12. JSON / SRT / VTT are easy follow-ons. |
| Language auto-detect | Most workflows don't know language upfront | Low | PROJECT.md Active #10. Whisper handles natively. |
| Speaker labels ("Person 1", "Person 2", ...) | Expected when a meeting has >1 speaker | Medium | PROJECT.md Active #7 |
| Inline edit of transcript text | Auto-transcripts are wrong; user must fix | Low | PROJECT.md Active #9 |
| Pause / resume for the running job and the queue | Long jobs, big playlists, need to step away | Medium | PROJECT.md Active #4 (playlist pause/resume). Per-job cancel is the corollary. |
| Persistence across restarts | Close the laptop, come back tomorrow, find the queue | Medium | PROJECT.md Constraints: "Job queue persistence across restarts" |
| Settings panel with at least a quality/model selector | Local ML apps without this feel like toys | Low | PROJECT.md Active #17-19 |

## Differentiators

Features that set the product apart. Not strictly expected, but high-value for this user. Most align with PROJECT.md's stated scope rather than out-of-trying.

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| YouTube playlist as input, processed as queue | "Process a 12-video course overnight" is a real workflow | High | PROJECT.md Active #3, #4. Few competitors handle this cleanly. |
| Multi-select summary templates per job | One video can be both a meeting recap and a concept explainer; don't force re-run | High | PROJECT.md Active #6. Most apps do one-summary-per-job. |
| Four well-shaped built-in summary types (meeting, investment, concept, quick recap) | Domain-specific outputs > generic "summarize this" | Medium | PROJECT.md Active #6, Key Decisions table. Tied to the four use cases. |
| Silent GPU auto-detect (CUDA vs ROCm) on first run | Removes the biggest local-ML UX failure mode | Medium | PROJECT.md Active #16, Constraints ("laptop is non-negotiable"). Differentiator because most apps crash or show a wizard. |
| Quality preset (small / balanced / large) auto-selecting model variants | One dial, not 12; the laptop Just Works | Low | PROJECT.md Active #17. |
| Per-category model override (transcription / diarization / LLM) | Power-user escape hatch without UX bloat | Medium | PROJECT.md Active #18. |
| Auto-chunking with OOM fallback for long videos | "No size limit, but with safety" is rare; most apps either OOM or refuse | High | PROJECT.md Active #13, Key Decisions. This is the desktop-vs-laptop unblocker. |
| Bulk-rename speaker chips ("Person 1" -> "Jim", applies to all instances) | Two click rename > typing names 200 times | Low | PROJECT.md Active #8. Most apps force per-segment rename. |
| Find-and-replace speaker across transcript | Bulk rename is the common case; this covers the rest | Low | PROJECT.md Active #9. |
| Per-line speaker reassignment dropdown | AI mislabels one segment; fix it without re-running | Low | PROJECT.md Active #10. Distinguishes this from apps that only re-diarize globally. |
| Re-export from history with edits applied | User renamed a speaker yesterday; today's export reflects that | Low | PROJECT.md Active #11. |
| Side-by-side video + transcript + summary view | Three-pane layout = the actual working surface | Medium | Implied by PROJECT.md's speaker-chip and inline-edit patterns. |

## Anti-Features

Things to deliberately NOT build. These are common in transcription apps but do not fit this product (single-user, local, four built-in templates, no live streaming, no editing, no translation, no auth).

| Anti-Feature | Why Avoid | What to Do Instead |
|---|---|---|
| **Cloud sync / cloud accounts** | Explicit out of scope; data is the user's, not ours | All data in local SQLite / filesystem |
| **Multi-user / auth / networked access** | Explicit out of scope; single user on one machine | None. Local-only, no login screen. |
| **Mobile / responsive phone UI** | Explicit out of scope; desktop browser only | Build for desktop breakpoints; phone is a graceful-degrade "doesn't fit" not a target |
| **Live real-time transcription of streaming audio / mic** | Explicit out of scope; input is always a finished file or URL | Reject streaming endpoints. If asked, point at live-streaming products. |
| **Translation between languages** | Explicit out of scope | Auto-detect transcribes in source language only; no target-language pass |
| **Custom user-defined summary templates in v1** | Explicit out of scope; only the four built-in ship | Ship four. Re-evaluate after v1 if users ask. |
| **In-app video editor / clip cutter / trim** | Explicit out of scope; app is transcription + summary, not editor | If a clip is needed, edit the original elsewhere; app just ingests the result |
| **Public sharing / collaboration on saved jobs** | Explicit out of scope; single user | Local export only. No shareable links, no comments. |
| **Mobile app (iOS / Android)** | Explicit out of scope | Web only. Don't even scaffold a PWA install prompt. |
| **Telephony / call recording integration (Zoom, Meet, Teams bots)** | Cloud-tied by nature; out of scope | If user wants a meeting transcript, they screen-record + upload |
| **AI chat with the transcript (RAG / "ask the video")** | Tempting, but expands scope dramatically and the LLM can already do summary extraction; not in PROJECT.md | Defer. Four templates cover the four use cases. |
| **Auto-generated chapter markers / chapters / "key moments"** | Adjacent to summary but a fifth output type; stretches the template set | If desired, fold into the "concept explainer" template as a "structure" section |
| **Social-media style share cards / thumbnails** | Tied to cloud sharing; anti-local | None |
| **Webcam / mic recording inside the app** | Live-streaming adjacent; out of scope | Use the OS to record, then drag the file in |
| **Viral / public template marketplace** | The four templates are intentional and curated | Hard-coded prompts in the back-end; no template registry |
| **Plugin / extension API (e.g. for custom LLM backends)** | The per-category model override already covers the real need | Settings panel swap; no plugin SDK in v1 |
| **Auto-publish to Notion / Obsidian / Readwise** | Cloud-tied, third-party API | Markdown export covers the user; they sync their own vault |
| **Per-machine separate UX** | Explicit decision: same UX, settings differ | One settings panel. "Quality preset" + per-category override. No machine-profile wizard. |
| **First-run setup wizard** | Explicit constraint: "no first-run wizards" on the laptop | Silent auto-detect; settings are reachable but never blocking |
| **Speaker count input ("how many speakers?")** | Diarization should auto-detect; asking the user defeats the point | pyannote infers; user can rename after the fact |
| **Auto-punctuation beautification ("smart quotes", em-dash)" beyond what the model already outputs** | Stylistic; risks regressing accuracy | Render the model's output; do not post-process for style |
| **Confidence score per segment in v1** | Useful for power users, but the inline-edit + reassign pattern covers correction already | Defer. Add later as an opt-in toggle if asked. |
| **Multi-language transcript on the same video** | Translation is out of scope | Single output language = detected source language |
| **Auto-upload of completed jobs to a backup target** | Cloud-tied | User is responsible for backing up the data directory |
| **Telemetry / usage analytics / "send anonymous crash report"** | No-telemetry is a stated constraint | None. Local logs only. |
| **Auto-update / background model refresh** | User controls the timing of model downloads (stated constraint) | Settings panel has a "check for updates" button; never auto |
| **Email notifications / push when a job finishes** | Single user, local, in the browser tab they're already in | The browser tab is the notification surface |
| **Voice-cloning / TTS output** | Not transcription | None |
| **Subtitle / closed-caption file generation (SRT, VTT, ASS)** | Tempting because it's easy, but PROJECT.md says "export Markdown". SRT/VTT are not in scope. | Defer; one-file-per-format is a rabbit hole |

## Feature Dependencies

A short dependency map. Useful when ordering phases.

```
Drag-and-drop / URL submit
  -> Job queue
       -> Background worker
            -> Audio extraction (yt-dlp for YouTube, ffmpeg for files)
                 -> Chunked transcription (Whisper / faster-whisper)
                      -> Optional: Diarization (pyannote) on chunks
                           -> Speaker reassignment UI
                                -> Speaker rename / find-replace
                 -> Language detection (inside Whisper)
            -> LLM summarization (one pass per selected template)
                 -> Multi-select summary templates
       -> Persistence (SQLite + filesystem)
            -> History list
                 -> Re-open + re-edit
                      -> Re-export Markdown
  -> Settings panel
       -> Quality preset -> model variant picker
       -> Per-category model override
       -> GPU auto-detect (silent, first run)
  -> Long-video OOM fallback (chunking) is a cross-cutting safety net for the worker
  -> Click-timestamp-to-seek is a cross-cutting UX layer over the transcript + video
```

**Highlights:**

- The job queue is the trunk; everything else is a branch.
- Diarization, speaker rename, and per-line reassignment form a single UX cluster; build them in one phase.
- Settings panel is independent and can land late, but the quality preset must exist before the long-video OOM fallback can pick models.
- Multi-select summary templates depend on a working LLM pass, which depends on the LLM being in the per-category override.

## MVP Recommendation

For a v1 that the user will actually use, prioritize in this order:

1. **Core ingest + transcribe loop** - drag-and-drop, YouTube URL, single job, transcript with timestamps, language auto-detect, Markdown export. This alone is a usable product.
2. **Job queue with persistence** - because YouTube URLs in the same session will pile up fast.
3. **Diarization + speaker rename cluster** - clickable chips, per-line reassignment, find-replace. This is the day-two must-have.
4. **History** - persist completed jobs, re-open, re-export. The app earns its keep when old work is findable.
5. **Settings panel** - quality preset, per-category model override, silent GPU detect. Needed before the desktop-vs-laptop asymmetry is usable.
6. **Long-video OOM chunking fallback** - the safety net; ship early enough that 2-hour videos don't crash the demo.
7. **YouTube playlist input + queue pause/resume** - high value but the queue infra from #2 is the prerequisite.
8. **Multi-select summary templates** - the headline differentiator; the four templates are the reason this app exists, but the rest has to work first.
9. **Click-timestamp-to-seek + side-by-side video** - polish; convert the transcript from text into a working surface.

**Defer to v2:**
- SRT / VTT export, custom summary templates, RAG chat with the transcript, chapter markers, auto-translation, per-segment confidence scores, plugin / extension API, backup integration, mobile breakpoints beyond "doesn't break."

**Explicitly never (per PROJECT.md + this anti-feature list):**
- Cloud sync, accounts, mobile app, live streaming, translation, video editor, collaboration, telemetry, first-run wizard, machine-profile UX, AI chat.

## Sources

- PROJECT.md (TranscriptionAndNotes) - canonical scope, constraints, decisions
- Prior knowledge of the local-transcription ecosystem (Whisper / faster-whisper / pyannote / whisperX / yt-dlp / Ollama / llama.cpp) as of early 2026
- Confidence tier: MEDIUM - research tools (WebSearch, WebFetch) were unavailable in this environment, so ecosystem claims are not freshly re-verified against the latest GitHub READMEs. The feature/anti-feature categorization itself is high-confidence because it is grounded in PROJECT.md's explicit decisions; only the *competitive landscape* claims (e.g. "most apps do one-summary-per-job") are MEDIUM.
