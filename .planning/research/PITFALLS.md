# Domain Pitfalls

**Project:** TranscriptionAndNotes
**Domain:** Local-first video transcription + diarization + LLM summarization on Windows
**Researched:** 2026-06-11
**Mode:** Ecosystem (pitfalls dimension)
**Overall confidence:** MEDIUM-HIGH on the pitfall shapes (these are the well-known failure modes of this stack); MEDIUM on ROCm-on-Windows specifics (volatile; can't be freshly verified in this environment, see "Gaps" at end).

## Executive Summary

The local-transcription + diarization + local-LLM stack has a known failure surface. Three categories dominate this project's risk:

1. **GPU and model-loading fragility** — ROCm on Windows is the canonical "doesn't work the way docs imply" trap; mixed backends (faster-whisper / pyannote / llama.cpp) each have their own load/lifecycle quirks; VRAM budgets on the 8 GB laptop are tight and an LRU manager is non-trivial.
2. **Pipeline correctness under long/realistic inputs** — diarization on long audio drifts, chunking leaves gaps at boundaries, language auto-detect lies on music-heavy intros, summary JSON parsing fails on a 200k-token transcript, and "the playlist is 30 hours" is a queue-design question, not a UI nicety.
3. **The local-first promise is easy to break in the details** — first-run model download silently fails, browser upload of a 4 GB MP4 hits a limit, the front-end and back-end disagree on what a "speaker" is, drag-and-drop is platform-specific, and "Just Works on both machines" requires a battery of smoke tests that the project does not have a phase for yet.

Each pitfall below is concrete to *this* project, names the failure mode by its real symptom, lists warning signs you can detect before the user does, and points at a phase that owns the prevention. Generic "test more" advice is excluded.

---

## Critical Pitfalls

Mistakes that cause rewrites, model-replacement, or break the "Just Works" promise.

### Pitfall 1: ROCm on Windows is treated as "the same as CUDA" in code

**What goes wrong:**
The orchestrator detects the desktop's AMD 6800 XT, picks `GpuBackend.ROCM`, and proceeds as if `torch.cuda.is_available()` and a real GPU-backed pipeline are working. On Windows, the official PyTorch ROCm wheel is **not distributed for Windows** for consumer Radeon cards; community ROCm HIP-on-Windows builds (e.g. for llama.cpp) are partial. The result is one of: silent CPU fallback, a DLL load failure deep in a torch import, or a torch wheel that imports but every kernel call takes the CPU path (the worst kind of failure — no error, just 30x slower).

**Why it happens:**
The PyTorch / CTranslate2 / llama.cpp ecosystems each have their own ROCm story, and none of them line up on Windows for gfx1030. The official line is "ROCm is a Linux platform."

**Consequences:**
- Desktop users get summaries that take 40 minutes instead of 2.
- "Settings says ROCm" but actual runtime is CPU — hard to detect without instrumentation.
- Cross-machine test parity is broken: the laptop uses CUDA + faster-whisper; the desktop needs whisper.cpp + a ROCm/HIP llama.cpp build, or a CPU path. This is two separate pipelines, not one.

**Prevention:**
- First-run detection writes the *active* backend (CUDA / ROCm-active / CPU) to `settings.json` and the user can see it. Do not just write "ROCM detected" — write "ROCM path requested; runtime verification: failed / succeeded / fell back to CPU."
- A runtime GPU-burn test on first run (one small matmul, one small llama.cpp prompt) confirms the path before the user submits a real job.
- A "Settings -> Diagnostics" panel runs a per-backend test and shows device name, VRAM seen by torch, and a measured tokens/sec for the LLM. The user can see the truth.
- The desktop ROCm path is **whisper.cpp ROCm build for Windows** (if a current release exists) for STT, and **llama.cpp ROCm/HIP build for Windows** for LLM. PyTorch ROCm on Windows is not a target.
- The Diarize step on the desktop runs on CPU (pyannote on the 16-core Ryzen is acceptable) or is disabled with a banner.

**Detection (warning signs before users see them):**
- `torch.cuda.is_available()` returns False on a machine with a real AMD GPU.
- `nvidia-smi` is absent on the desktop.
- `pip install torch` defaults to a CUDA wheel on a non-NVIDIA machine.
- `llama-cpp-python` built without `-DGGML_HIPBLAS=ON` reports "CPU" as device.

**Phase ownership:** GPU-backend-detection phase (the spike in Step 2 of ARCHITECTURE.md's build order). This must be done before any model work.

---

### Pitfall 2: VRAM exhaustion from concurrent models on the 8 GB laptop

**What goes wrong:**
The pipeline is STT (Whisper medium int8 ≈ 3 GB) → Diarize (pyannote ≈ 1-2 GB) → LLM (Qwen2.5-7B Q4_K_M ≈ 5-6 GB). The naive "load all three, keep them warm for a 2-hour video" plan uses 9-11 GB. The laptop has 8 GB. The first 90-minute transcript triggers CUDA OOM, the back-end crashes, the job is marked failed, and the user has to restart.

**Why it happens:**
Developers reason about the steady-state size of each model, not the *peak* with activations, KV cache, audio buffer, and ffmpeg in process at the same time. The 8 GB VRAM figure is the *theoretical* budget, not the *operational* one.

**Consequences:**
- Silent OOMs deep in Whisper that produce a partial transcript and a crashed worker.
- LLM generating summaries against partial transcripts without the orchestrator noticing.
- "It worked for 10 minutes" jobs and "it worked for 2 hours" jobs behaving differently.

**Prevention:**
- A model manager with **explicit lifecycle**: STT loads, transcribes, unloads; Diarize loads, runs, unloads; LLM loads, generates, unloads. Single-model-at-a-time semantics by default.
- An opt-in "keep all models warm" toggle in settings, hidden behind a VRAM-availability check; default off.
- VRAM probing on model load (`torch.cuda.memory_allocated()` before and after) and a refusal to load the next model if it would push past 85% of available VRAM.
- A `chunk.fallback` event when STT OOMs, halving chunk size and retrying (this is in ARCHITECTURE.md already, but the *implementation* is the pitfall — naive retry with the same chunk size does nothing).
- A "what's currently in VRAM" indicator in the UI, not just "Settings -> Diagnostics."

**Detection:**
- `torch.cuda.OutOfMemoryError` in logs.
- Job stage durations growing linearly with audio length instead of staying constant under chunking.
- Driver-level Xid errors in Event Viewer on Windows (CUDA driver fault = something crashed the GPU).

**Phase ownership:** Model-manager phase (Step 2 of build order) and STT/chunking phase (Step 3). LLM phase (Step 8) is where concurrent-load temptation peaks.

---

### Pitfall 3: HuggingFace-gated pyannote model treated as a normal dependency

**What goes wrong:**
The app starts, the diarize stage calls `Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")`, gets a 401, and crashes the job. The user is staring at a generic "model not found" error with no path forward. This is the one piece of the stack that requires a real human action (HF account, license accept, token) — and if the design pretends it doesn't, the first "real" job fails.

**Why it happens:**
Most models on HF are public; pyannote 3.1 is gated behind a license agreement. The PyPI install doesn't surface this.

**Consequences:**
- First "real" job fails; user assumes the app is broken.
- "Silent first run" promise is broken if the app tries to diarize before a token is present.

**Prevention:**
- Diarization is **optional and disabled by default** until a token is present in settings. The app transcribes fine without it.
- A non-blocking banner in the UI: "Speaker labels are disabled. Add a HuggingFace token in Settings to enable."
- The settings panel has a one-click "Get a token" link to the HF page; a paste-in field; a "Test token" button that does a dry-run load of the pipeline.
- If a token is present but invalid, the banner says "Token rejected — speaker labels disabled" and the job continues without diarization.
- The token is stored in `settings.json` (or a separate `secrets.json` excluded from any future export) — not in SQLite if export-to-share is ever a future feature.

**Detection:**
- `huggingface_hub` 401 responses.
- Pipeline.from_pretrained raising `RepositoryNotFoundError` or `GatedRepoException`.

**Phase ownership:** Diarize phase (Step 7) and the settings panel (Step 10). The token UX is the only place where a "silent first run" caveat must be honestly surfaced — this is already called out in STACK.md.

---

### Pitfall 4: First-run model download silently fails or stalls

**What goes wrong:**
The user runs the app for the first time. A 4-7 GB download (LLM + Whisper + pyannote weights) starts in the background. A flaky Wi-Fi reconnect, an antivirus quarantine of a `.gguf` file, a HuggingFace rate-limit, or a `data/Models/` path with a space in it (`C:\Program Files\...`) leads to a download that hangs, partially completes, or "completes" with a corrupt file. The next job crashes on model load with no obvious cause.

**Why it happens:**
Model downloads are typically fire-and-forget. Verification (SHA, file size) is rarely done. Windows paths with spaces break some HuggingFace client edge cases. Antivirus quarantines `.gguf` and `.pt` files as "suspicious" routinely.

**Consequences:**
- The user has to know to delete `data/Models/` and retry. They don't.
- "It worked yesterday" + "doesn't work today" is the worst kind of bug.

**Prevention:**
- Model manager verifies each file (size, optional SHA256 from the model card) after download. On mismatch, the file is re-downloaded with a bounded retry budget.
- A persistent download log: "downloading faster-whisper large-v3: 412 MB / 1.5 GB, ETA 3 min" — exposed as a real UI element, not a one-line console print.
- Download paths live under a directory with no spaces in the path (e.g. `%LOCALAPPDATA%\TranscriptionAndNotes\Models\`) and the installer is explicit about this.
- A "Resume download" state survives an app crash — partial files are kept and resumed, not re-downloaded from zero.
- A "Verify all models" button in settings re-checks every installed model against its expected size/hash. This is the user-facing "did anything get corrupted" check.
- The first-run flow lets the user **defer** model download — "Use Small preset to skip the 7B LLM download for now" — and runs a smaller model on first use.

**Detection:**
- `data/models/` shows `.incomplete` files older than 24h.
- Model load throws `RuntimeError: unexpected EOF` or weight-shape mismatches.
- The browser's network tab shows requests with `0/s` throughput for minutes (proxy detection).

**Phase ownership:** Model-manager phase (Step 2). The download UX is the surface; the verification is the meat.

---

### Pitfall 5: Long-audio pipeline OOMs despite "chunking"

**What goes wrong:**
The job is a 3-hour podcast. Chunking splits the audio into 30-second pieces. Each chunk is loaded into faster-whisper; faster-whisper does internal batching and *also* uses a 30-second sliding window. The 30-second chunk + the 30-second internal context = up to 60 seconds of activations, which on large-v3 with int8 can hit 5-6 GB. Worse, **pyannote runs on the full audio** for global speaker turns — that's the *un-chunked* 3-hour audio hitting a 1-2 GB diarization model with a long-context encoder. Long podcasts (3+ hours) with overlapping speech or music are the OOM trigger.

**Why it happens:**
Chunking solves the "input too long" problem, not the "model context too long" problem. Pyannote is explicitly a full-audio pipeline. Whisper's internal window is independent of the chunk size the orchestrator hands it.

**Consequences:**
- A 2-hour video that "worked fine" in dev fails on a 3-hour meeting recording.
- The orchestrator's `chunk.fallback` event is a half-measure — halving chunk size doesn't help if the OOM is in pyannote.

**Prevention:**
- Diarize is the chunking pinch point. Two viable strategies:
  1. **Sliding-window diarize** for very long audio: process the audio in 5-10 minute windows with overlap, stitch speaker turns, accept small boundary errors. The pyannote API supports this via `Pipeline(...).apply_in_chunks()` or by chunking the audio and using the same pipeline.
  2. **Two-pass:** STT chunks the audio and produces timestamped segments. Diarize runs on the *full* audio, but on a smaller model variant (pyannote has community smaller pipelines) or with mixed precision.
- The auto-fallback rule: if the audio is > N minutes (configurable, default 90), switch to a long-audio diarization strategy. Document the trade-off in the UI ("Speaker labels may be less accurate on long audio").
- A long-audio mode in the orchestrator that *releases* GPU memory between STT and Diarize (a `torch.cuda.empty_cache()` and explicit model unload) so pyannote gets a fresh VRAM budget.
- A "skip diarize for jobs longer than 4 hours" soft-warning, since the marginal value of speaker labels on a 6-hour unedited lecture is low and the cost is high.

**Detection:**
- `torch.cuda.OutOfMemoryError` in pyannote logs (not faster-whisper).
- Whisper finishes; pyannote crashes; job is half-done.
- Driver-level Xid errors or `cudaGetLastError() == CUDA_ERROR_OUT_OF_MEMORY` at the CTranslate2 layer.

**Phase ownership:** STT + chunker phase (Step 3) and diarize phase (Step 7). The "auto-fallback chunking" requirement is a *system* requirement, not a single-stage one.

---

### Pitfall 6: yt-dlp breaks when YouTube changes its player or applies bot detection

**What goes wrong:**
The app works for three weeks, then a user's YouTube URL fails with "Sign in to confirm you're not a bot" or "HTTP 403." The user blames the app. The fix is `pip install -U yt-dlp` — but the app's own "first run downloaded everything" UX gives the user no path to discover this. yt-dlp is updated ~weekly to keep up with YouTube's anti-scraping changes; a six-month-old yt-dlp will fail on most videos.

**Why it happens:**
YouTube aggressively throttles and blocks scrapers. yt-dlp is the only thing keeping up. It's a moving target.

**Consequences:**
- YouTube ingest breaks silently for the user; the job hangs in `ingesting` forever.
- The user has no idea yt-dlp is the culprit and assumes the app is broken.
- Playlist expansion fails on the first child, marking the whole playlist as failed.

**Prevention:**
- The app's launcher / settings panel has an explicit "Update yt-dlp" button (and a periodic check on app start that surfaces a non-blocking notification: "yt-dlp is N days old; update recommended").
- A friendly error path: when yt-dlp fails, the error message explicitly says "yt-dlp could not fetch this video. Try updating yt-dlp in Settings, or check your network." — not a generic 500.
- A network-failure detection layer: if the failure is a 429/403/IP-block pattern, suggest a cooldown.
- A `--no-check-certificates` and proxy-passthrough escape hatch in settings for power users.
- A "test URL" button in settings that runs a yt-dlp dry-run on a known-good video and reports the result, so the user can verify their setup.

**Detection:**
- yt-dlp returns `ExtractorError`, `HTTPError 403`, or "Sign in to confirm you're not a bot."
- Network logs show repeated requests to `youtube.com` with no successful response.
- The launcher can compare its bundled yt-dlp version's age to a "is this version known broken?" list (a tiny allowlist of recent known-good versions in the app's data).

**Phase ownership:** YouTube ingest phase (Step 6). Not a phase-zero issue; becomes critical once YouTube ingest ships.

---

### Pitfall 7: Local LLM structured outputs are flaky on long transcripts

**What goes wrong:**
The four summary templates ask the LLM for structured Markdown (e.g. "Investment analysis — pros, cons, tickers, thesis"). On a 50k-token transcript the LLM does fine. On a 200k-token meeting transcript (4-hour meeting), the LLM:
- Loses track of which section it's in and writes a freeform summary.
- Hallucinates tickers / action items that aren't in the transcript.
- Outputs the prompt back partially.
- Goes off-format (Markdown sections become prose paragraphs).
- Refuses on "this looks like PII / I'm not allowed to summarize recordings" (some instruct models do this).

**Why it happens:**
Local LLMs in the 7B-14B Q4_K_M range are good at "summarize" but not great at "summarize into this exact schema." The longer the input, the worse the structure adherence.

**Consequences:**
- One in five summary runs produces something the UI can't render.
- The user re-runs the summary and gets a different shape each time.
- The "meeting summary" template silently omits "decisions" when the input is long.

**Prevention:**
- For the four built-in templates, the prompt includes a **hard schema** the LLM must fill (e.g. "Output exactly these Markdown sections, in this order: ## TL;DR, ## Action Items, ## Decisions"). A small post-validator in the back-end checks the output and, if a section is missing, re-prompts the LLM with a "you missed section X, add it" follow-up. Bounded to 2 retries.
- For long transcripts, the orchestrator **chunks the summarization**: produce a per-section summary, then a "synthesize the section summaries" pass. This is two LLM calls instead of one but is dramatically more reliable.
- The four templates are unit-tested against a battery of sample transcripts (short, medium, long, edge cases like silence / music / no clear speakers). The test set ships with the back-end and runs in CI.
- The LLM temperature is low (0.1-0.2) for summary runs to maximize determinism; the user can override in settings.
- A "schema-strict" mode in settings uses llama.cpp grammar constraints (GBNF) to force the output structure at the sampler level. This is the strongest guarantee and is worth the engineering for the four built-in templates.

**Detection:**
- Output doesn't contain expected section headers (`## Action Items`).
- Output is shorter than `min_output_tokens` from the template.
- LLM output contains the prompt template text verbatim (the "the model is confused" tell).
- Output contains a refusal pattern ("I'm sorry, but as an AI...").

**Phase ownership:** LLM adapter + templates phase (Step 8). The schema-strict mode + chunked summarization is part of this phase's definition of done, not polish.

---

### Pitfall 8: Speaker diarization accuracy collapses on long audio or overlapping speech

**What goes wrong:**
On a 30-minute interview, pyannote 3.1 is roughly 90%+ accurate. On a 2-hour meeting with 6 people, overlap, crosstalk, and the same person changing registers (loud / soft / on phone) push accuracy well below 50%. The user gets "Person 1, Person 2, Person 5, Person 2, Person 5, Person 3" with no rhythm — the speaker labels look like noise. Worse, on audio with background music, the diarizer invents speakers that aren't there.

**Why it happens:**
Diarization is genuinely hard on long, multi-speaker, real-world audio. pyannote is the best open option and it's not magic.

**Consequences:**
- Speaker chips have 8+ entries with single-line counts each.
- Bulk rename is the right pattern, but the user has to do it for 8 speakers, not 2.
- Per-line reassignment becomes the dominant correction pattern, not a rare fix.

**Prevention:**
- The UI must be honest about diarization accuracy: a "Diarization confidence" hint per line (the pyannote pipeline exposes this) shown subtly, and a "this may be one person talking over themselves" tool tip when a line flips speakers very rapidly.
- The "find-and-replace speaker" feature is a first-class workflow, not a power-user one — the help text points to it explicitly.
- A "Diarize: Off / Auto (1-N speakers) / Expected N speakers" setting. The "expected N" mode lets the user say "this is a 2-person podcast" and gives pyannote a count hint, which measurably improves accuracy on the long tail.
- The orchestrator emits `diarization.confidence` per segment; the UI can sort/filter low-confidence segments for review.
- For the investment-analysis / concept-explainer use cases, the diarize step is often a net negative (one presenter, no real speaker info). The orchestrator can *skip* diarize when only one voice is detected in the first 60 seconds (cheap VAD pre-check).

**Detection:**
- Number of distinct speakers > 5 on an audio file the user knows is < 4 speakers.
- Speaker boundaries fire more than once per 5 seconds (the "rapid flipping" tell).
- pyannote confidence scores for assignments are < 0.5 in aggregate.

**Phase ownership:** Diarize phase (Step 7). The "expected N speakers" setting and the confidence display are non-negotiable for this phase.

---

### Pitfall 9: Job-queue state on disk is the source of truth, but the schema evolves

**What goes wrong:**
The job queue lives in SQLite. The schema is `jobs(id, status, source, source_type, created_at, ...)` and the orchestrator mutates state machine values like `pending -> ingesting -> transcribing -> diarizing -> summarizing -> done`. Three months in, a new state is added (`aligning`, `reexporting`), a new field is added (`quality_preset`, `parent_playlist_id`), and the existing rows don't have the new columns. The app crashes on first read. Worse: a *crash* mid-state-machine-transition leaves a job in `transcribing` and on restart, the orchestrator must decide whether to resume, re-run, or mark failed. If the transition logic is wrong, the user loses the whole job.

**Why it happens:**
SQLite is convenient; the temptation is to keep state in one row. The "what state is the job in after a crash" question is a real distributed-systems problem disguised as a one-user app.

**Consequences:**
- Crash mid-job → resume ambiguity → user re-runs the whole 3-hour job.
- Schema migrations break old jobs.
- Playlist children reference a parent that no longer exists.

**Prevention:**
- State machine transitions are *atomic*: a job moves from `transcribing` to `transcribed` only if `transcript.json` exists on disk. The DB row references the file; the file is the truth. This is already in ARCHITECTURE.md ("Per-job working directory") — the pitfall is the *discipline* of not skipping the disk check.
- Schema migrations: every migration is an idempotent script with a version table; old DBs run forward on app start. Add a `schema_version` table; refuse to start with a newer DB than the app knows about.
- Resume logic: on startup, scan `data/jobs/<id>/` for stage-output files and *infer* the resume point. Don't trust the DB row. The DB row is updated after the file is written.
- A "stale" detector: jobs in `transcribing` with no stage-output file newer than 10 minutes are auto-reset to `pending`.
- A "crash-safe" pattern: write a `.tmp` file, fsync, rename to the final name. Every persisted stage uses this.
- The "pause" state is *cooperative*: a paused job runs to the next stage boundary and stops. There is no "kill the GPU mid-inference" button in v1.

**Detection:**
- App startup logs a warning about a job in `transcribing` with no `transcript.json` partial.
- Schema mismatch on a new column.
- Two restart attempts leave the same job in different states.

**Phase ownership:** Job orchestrator + queue phase (Step 4). This is the spine of the app; the state machine is the hardest single piece.

---

### Pitfall 10: Front-end and back-end disagree on job IDs, speaker labels, and stage names

**What goes wrong:**
The front-end POSTs a job; the back-end returns `{job_id: "abc-123"}`. The front-end opens a WebSocket to `/ws/jobs/abc-123`. A new job is submitted; the back-end's `uuid` generation hits a collision (unlikely) or the front-end sends the request twice (button mashing) and gets two different job IDs. The WebSocket subscribes to one, the user looks at the other. Or: the back-end uses `transcribing` as a state, the front-end's TypeScript type uses `processing`, and progress events with the back-end's name get silently dropped on the client. Or: the back-end stores speaker labels as `SPEAKER_00`, the front-end displays `Person 1`, and on find-and-replace the back-end stores the rename but the front-end doesn't refetch.

**Why it happens:**
Two codebases, two type systems, an HTTP boundary. The shared schema is implicit; the temptation is to "just send JSON."

**Consequences:**
- Progress events disappear; the UI sits at 0% forever on a job that's actually at 80%.
- "Rename Jim" works in the UI but the export still says "Person 1."
- A job ID mismatch means the user can't reconnect after navigating away.

**Prevention:**
- A **shared schema**: an OpenAPI spec generated from the back-end's Pydantic models, and the front-end generates its TypeScript types from the OpenAPI spec (e.g. via `openapi-typescript`). Both sides consume the same source of truth. Stage names, speaker label format, job state enum — all generated.
- WebSocket reconnection: the client subscribes by job ID; on reconnect, it replays missed events from a server-side event log (or just re-fetches the job state and resumes from the latest event ID). The job ID is opaque to the user but is the only thing the client and server share.
- Idempotency: `POST /jobs` accepts an idempotency key. The user double-submits the same video; the second request returns the existing job ID, not a new one.
- "Optimistic UI" is dangerous for jobs. The UI waits for the server's confirmation on every state-changing action. Rename → POST → 200 → UI updates. No optimistic flip-flop.
- A version string on the WebSocket protocol: when the back-end changes the event shape, the front-end says "out of date, please refresh."

**Detection:**
- WebSocket connects but no events arrive.
- Front-end log: "unknown stage `transcribing`" — the client enum has `processing`, the server sends `transcribing`.
- Two jobs created from one click; the user's history shows duplicates.

**Phase ownership:** API contract (set up in Step 1, evolved with every step). This is the kind of pitfall that compounds — catching it late is a rewrite.

---

### Pitfall 11: Drag-and-drop of a multi-gigabyte video file hits browser or server limits

**What goes wrong:**
The user drags a 4 GB MP4 into the browser. The browser holds the whole file in memory (some browsers do, some stream) and POSTs it to the back-end. FastAPI's `python-multipart` reads it into memory (default), the back-end OOMs, or the request times out. Even on a working path, the user gets a generic "upload failed" with no indication of which limit was hit.

**Why it happens:**
"Drag and drop a file into a web form" is a primitive that hides enormous complexity for large files. Default server limits are tuned for 10 MB uploads, not 4 GB videos.

**Consequences:**
- The headline input path (drag-and-drop) fails on realistic inputs.
- The user assumes the app can't handle large files (the explicit project promise is "no size limit").

**Prevention:**
- **Streaming upload** with FastAPI: read the request body in chunks and write directly to `data/jobs/<id>/source.ext`. Never hold the full file in memory. Use a `StreamingResponse`/`Request.stream()` pattern, not `UploadFile`.
- Set explicit server limits that match the use case (`max_upload_size` is *unbounded* in v1, but request body reads are streamed).
- Front-end uses `fetch` with a `ReadableStream` body for true streaming upload, with progress events. (Standard `FormData` + `fetch` is fine; the `XMLHttpRequest` `upload.onprogress` pattern also works.)
- A pre-upload UI check: the browser exposes the file size; if > 2 GB, show "this will take a few minutes to upload, leave the tab open." (Realistic advice; not a blocking dialog.)
- A "resumable upload" path for very large files (TUS protocol or a custom chunked POST) is a v2 feature. v1 streams; if the connection drops, the user re-drags.
- A WebSocket fallback for upload: the front-end opens a WS, the back-end accepts a binary stream, writes to disk. Useful when HTTP upload is filtered (corporate networks) — v2.

**Detection:**
- Server OOM during upload (`MemoryError` in worker logs).
- HTTP 413 Payload Too Large.
- Browser freezes for > 30s after drop.
- Upload reaches 100% then "fails" with a network reset.

**Phase ownership:** Local-file ingest phase (Step 5). This is the first user-facing path; the upload streaming has to work before the first demo.

---

### Pitfall 12: "Just works on both machines" turns into a per-machine configuration nightmare

**What goes wrong:**
The project explicitly says GPU detection must be silent and the same UX must work on the laptop and desktop. The reality:
- The laptop (CUDA, 8 GB) is the easy case; faster-whisper + pyannote + llama-cpp-python all have CUDA wheels.
- The desktop (ROCm, 16 GB) is the painful case; PyTorch ROCm isn't on Windows; the path is whisper.cpp ROCm build + llama.cpp ROCm/HIP build + pyannote on CPU.
- The two paths have different model files, different quantization options, different "what runs" lists.

If the design says "one code path" and pretends the two machines are equivalent, the desktop is broken on day one. If the design says "two code paths with auto-detection," the per-category model-override settings panel becomes a maze: "this model is CUDA-only," "this model is ROCm-only," "this model works on both."

**Why it happens:**
The same UX on different hardware is a real product goal but it conflicts with the underlying reality: ROCm on Windows is a different ecosystem. The "settings panel" abstraction can paper over this, but only if the abstraction is honest about what's actually running.

**Consequences:**
- The user installs the app on the desktop and the first job fails.
- "What works" is a per-machine matrix the user has to discover by failure.
- The settings panel hides constraints the user needs to know.

**Prevention:**
- The first-run flow shows **what is active** for each model category, with a "Test" button per model. Not a wizard — a non-blocking info card on the main page the first time the app starts.
- The desktop ROCm path is **acknowledged as a different backend**, not hidden. The settings panel has a "Backend: CUDA (laptop) / ROCm (desktop) / CPU" indicator that the user can see and verify.
- A diagnostics page runs a per-backend smoke test and reports measured tokens/sec and a "this is what you'd see on the other machine" hint.
- A "two-machine sync" is *not* in v1; the user accepts that settings are per-machine. The data directory is the only thing that can be synced (and even that, only manually).
- The default model set in settings is `BALANCED` (fits the 8 GB laptop). The desktop user can opt into `LARGE` (a bigger LLM, a fp16 Whisper) — but the preset description says "designed for the 8 GB laptop; will use ~10 GB VRAM on the desktop."

**Detection:**
- Settings says "Backend: ROCm" but every job runs on CPU (the worst tell).
- `nvidia-smi` shows zero utilization on a supposedly-CUDA job.
- A 1-hour video on the desktop takes 3x as long as the same video on the laptop.

**Phase ownership:** GPU detection + settings panel (Steps 2 and 10). The first-run diagnostics card and the per-backend smoke test are part of the spec, not polish.

---

## Moderate Pitfalls

### Pitfall 13: Mixing model sources breaks version pinning

**What goes wrong:**
The Whisper weights come from `Systran/faster-whisper-*` on HuggingFace (via `huggingface_hub`). The pyannote weights come from `pyannote/speaker-diarization-3.1` on HuggingFace (same library). The LLM weights come from `TheBloke/Qwen2.5-7B-Instruct-GGUF` on HuggingFace. The user swaps one in settings: "use `KakologArchives/Qwen2.5-14B-Instruct-abliterated-GGUF`." Now the model manager's "is this installed?" check is by filename, not by content hash. The "update models" workflow doesn't know this swap happened. The settings file references a model that no longer exists upstream.

**Prevention:**
- The model manager keys on a content hash + a model ID, not just a name. A settings entry like `{"stt": {"id": "Systran/faster-whisper-medium", "revision": "abc123def"}}` is explicit.
- Custom model entries are first-class: the settings panel has an "Add custom model" path that takes a HF repo ID, downloads, and registers.
- A "models I have installed" page lists every file in `data/models/`, its size, its source, and a "remove" button. Drift is visible.

**Phase ownership:** Model manager (Step 2) and settings panel (Step 10).

---

### Pitfall 14: Language auto-detect is wrong on music, silence, or non-speech audio

**What goes wrong:**
Whisper's `detect_language` returns "english" on a video that's actually Japanese with a long silent intro. Or it returns "zh" on a video with Chinese background music and English speech. The transcript is in the wrong language; the user has to re-run with `language="ja"` — but the UI doesn't expose that.

**Prevention:**
- The default is auto-detect; the user can override language per job in the submit form (or in settings, with "always transcribe in X" as an option).
- The UI shows the detected language and confidence after STT completes, with a "Wrong language? Re-run with language: [ja]" affordance.
- For very quiet / music-heavy intros, the first 30 seconds of audio should be excluded from language detection (a known Whisper issue).

**Phase ownership:** STT phase (Step 3), minor settings addition in Step 10.

---

### Pitfall 15: Browser-side `EventSource` / WebSocket handling breaks on tab close and reopen

**What goes wrong:**
The user submits a job, navigates away from the job page (PROJECT requires: "user can navigate away and return to status"). The WebSocket disconnects. The user comes back; the UI re-fetches the job state via REST, but live progress events are gone — the UI is frozen at the last received event.

**Prevention:**
- WebSocket reconnection is built in (the back-end has a `last-event-id` / resume protocol).
- On reconnect, the back-end sends a "current state snapshot" event with all stages' statuses, and the front-end renders from the snapshot.
- For long jobs (3 hours), a polling fallback is acceptable: if the WebSocket doesn't connect in 3 seconds, the front-end falls back to `GET /jobs/<id>` every 5 seconds. The WebSocket is the *fast path*; polling is the *correctness fallback*.

**Phase ownership:** Job orchestrator + WebSocket (Step 4).

---

### Pitfall 16: 16 kHz mono WAV conversion fails on weird input formats

**What goes wrong:**
The back-end assumes ffmpeg can convert the input to 16 kHz mono WAV. Some inputs:
- A `.m4a` with DRM (iTunes-purchased audio) — ffmpeg refuses.
- A `.mkv` with multiple audio tracks — ffmpeg picks the wrong one.
- A `.webm` from a screen recording with Opus audio.
- A YouTube age-restricted video (already in yt-dlp pitfalls, but also hits here if the user downloads manually).
- A `.wav` that's actually 48 kHz stereo and very large.

**Prevention:**
- ffmpeg is invoked with explicit codec options, not "just convert it." `-ar 16000 -ac 1 -c:a pcm_s16le` is the canonical command.
- Multi-audio-track inputs: ffmpeg's `-map 0:a:0` picks the first audio track; the settings panel should expose "audio track" for the user to choose, defaulting to the first.
- DRM'd inputs: detect and fail with a clear message ("DRM-protected files are not supported. Please use a different source."). Don't try to "fix" it.
- Large WAV inputs: stream ffmpeg's output to disk, don't hold the intermediate in memory.
- ffmpeg presence is checked on first run; the installer verifies the static build is the right one.

**Phase ownership:** Ingest (Step 5, Step 6).

---

### Pitfall 17: SQLite WAL mode is on, but backups and migrations aren't

**What goes wrong:**
The DB is in WAL mode (correct for concurrent reads during jobs), but:
- A user-initiated "reset" of the app doesn't back up the DB first; the user loses all job history.
- A migration script runs and the DB is corrupted; the user's data is gone.
- The DB is in `%LOCALAPPDATA%` and the user copies `data/` to a new machine, but `db.sqlite` is locked because the back-end is running.

**Prevention:**
- A `data/` backup tool (settings panel: "Back up data to a folder") that snapshots the DB and the job folders as a tarball. The user runs it before risky changes.
- The DB connection is the only writer; the front-end never touches it. Migrations run on back-end start, never on user-triggered actions.
- The lock file is a real SQLite lock; copy while the back-end is running, or stop the back-end first. The settings panel shows a "DB is open" warning if the user tries to back up while the back-end runs.

**Phase ownership:** Storage / DB (Step 1), polished in Step 10.

---

### Pitfall 18: Drag-and-drop UX is browser-specific and platform-specific

**What goes wrong:**
The user drags a file from File Explorer. The browser's default behavior opens the file in the tab. The drop event fires, but the React drop handler has to call `e.preventDefault()` correctly, and the OS path that the browser exposes is the *file system* path, not a real path the back-end can read (the front-end must upload the file's contents, not the path).

**Prevention:**
- Use a library like `react-dropzone` that handles the cross-browser drop semantics.
- The front-end reads the `File` object from the drop event, not any path; the upload is via `FormData` or streamed `fetch`.
- The dropzone shows a clear "drop here" affordance and rejects non-video files with a clear message.
- The "click to pick" fallback is always present for users who don't drag.

**Phase ownership:** Front-end (Steps 5, 9).

---

### Pitfall 19: Embedded `<video>` element and transcript timestamps are out of sync

**What goes wrong:**
The user clicks a transcript timestamp; the video seeks to 0:00, not the timestamp. The transcript is rendered with line-level timestamps but the video element's `currentTime` is set in the wrong unit (ms vs seconds), or the segment start time is wall-clock-time instead of video-time. The video plays out of sync with the highlighted line.

**Prevention:**
- The video element is the same `<video>` instance for the whole session; on transcript click, `videoRef.current.currentTime = segment.start_seconds` — not a fresh `<video>` mount.
- Auto-scroll the transcript to the active line based on `timeupdate` (with a debounce — `timeupdate` fires ~4x/sec).
- The "active line" highlight uses the segment's `[start, end]` range, not just `start`, so the highlight tracks the audio correctly.
- A "video element didn't load" fallback: if the source file is a `.wav` from a YouTube download, the back-end needs to serve a video file the browser can play (or stream the original). The job's `source.ext` is the video when available; for YouTube, the original `.mp4` from yt-dlp is kept alongside the extracted audio.

**Phase ownership:** Front-end transcript editor (Step 9).

---

### Pitfall 20: Multi-select summary templates produce inconsistent styles across runs

**What goes wrong:**
The user selects "Meeting" + "Concept explainer" on the same video. The LLM produces two summaries, but the schemas drift run-to-run: one run has "## Action Items" and the next has "## Action items" (capitalization matters for the find-and-replace). The UI's "expected sections" check fails; the export is half-broken.

**Prevention:**
- The four templates ship as **typed schemas** the back-end validates. The section names are constants; the LLM is told "the section names must be exactly these strings."
- The templates are unit-tested: a fixture of N transcripts run through each template produces output that matches the expected schema. The CI test fails on a missing section header.
- The "multi-select summaries" feature is implemented as N independent LLM calls (one per selected template), not one big prompt with N schemas; the per-template correctness is what matters.

**Phase ownership:** LLM + templates (Step 8).

---

### Pitfall 21: Inline transcript editing is not persisted if the back-end restarts mid-edit

**What goes wrong:**
The user edits a transcript line; the front-end PATCHes to the back-end; the back-end writes to the DB; the user edits another line before the first PATCH returns; the back-end crashes; the second edit's PATCH is lost. Worse: the front-end and back-end agree on the transcript state via "last-write-wins" with no conflict resolution.

**Prevention:**
- The transcript is the `transcript.json` file on disk, not a SQLite row. Edits write through to the file with a `.tmp` + rename. Concurrency is solved by file-level locks.
- Each edit returns the new transcript content; the front-end treats the back-end as the source of truth.
- A "dirty" indicator in the UI shows unsaved changes; on navigation away, the user is warned.
- The DB stores only "this job's transcript was last edited at X" for history views; the file is the truth.

**Phase ownership:** Transcript editor (Step 9).

---

## Minor Pitfalls

### Pitfall 22: The default ffmpeg path in PATH isn't the one the app finds

On Windows, ffmpeg can be installed via npm, conda, or downloaded manually to `Program Files`. The app's "find ffmpeg" logic must look in the right places, and the settings panel must let the user override the path. The error message when ffmpeg is missing should be "ffmpeg not found — install it or set the path in Settings," not a cryptic `FileNotFoundError` from a child process.

### Pitfall 23: yt-dlp's "audio only" preference fails on some YouTube videos

Some YouTube videos are video-only with a separate audio track, or have audio in a format yt-dlp can't mux. The fallback is to download the bestvideo+bestaudio and let ffmpeg combine. Pin the format selector: `bestaudio[ext=m4a]/bestaudio/best` with a `--merge-output-format` post-processor. Test on a small set of known-problematic videos in CI.

### Pitfall 24: Pydantic v1 vs v2 schemas leak through

Pydantic v2 is faster but has a different validation surface. Mixing a v1-era library (some HF sub-libraries still have v1 models) with v2 in the back-end produces subtle errors. Pin `pydantic >= 2` everywhere; if a dependency insists on v1, isolate it.

### Pitfall 25: HuggingFace rate limits on first-run download

The HF token-free path has rate limits (a few GB/day per IP). On first-run, the user might hit them. Mitigations: prompt for a free HF token up front (unlocks higher rate limits); use `huggingface_hub`'s retry-with-backoff; let the user retry on failure.

### Pitfall 26: PyTorch's `cuda` semantically means different things to different libraries

`faster-whisper` (CTranslate2) has its own CUDA detection. `llama-cpp-python` has its own. `pyannote` uses torch's. They can disagree on a multi-GPU box (this project is single-GPU, so less of a worry, but the back-end's `torch.cuda.set_device(0)` is a real call to make). On a multi-GPU desktop, the "device 0" assumption breaks. The orchestrator should pin to one device and surface the choice in diagnostics.

### Pitfall 27: Audio sample rate mismatch in pyannote

pyannote's pipeline assumes 16 kHz mono; faster-whisper assumes 16 kHz mono. The "canonical audio" is 16 kHz mono WAV. But pyannote in some versions resamples internally and reports slightly different time boundaries than faster-whisper. The alignment step has to handle a few tens of milliseconds of slop. The back-end's align function (in the diarize phase) should be tested with known fixtures.

### Pitfall 28: The "settings.json" file ends up in the wrong location on Windows

`%LOCALAPPDATA%` is the right choice, but if the app is run from a non-admin shell that can't write there, it falls back to the current working directory, which is the install dir, which might be `Program Files` (read-only). The launcher should resolve the data dir on first run, create it, and fail clearly if it can't. Don't silently fall back to CWD.

### Pitfall 29: Console windows popping up on Windows during ffmpeg / yt-dlp

`subprocess.run("ffmpeg", ...)` on Windows, by default, flashes a console window. Use `subprocess.run(..., creationflags=CREATE_NO_WINDOW)` (or the `subprocess.STARTUPINFO` pattern) to hide the console. This is the difference between a polished app and one that flashes a black window every time it processes a video.

### Pitfall 30: The "find and replace speaker" feature has off-by-one or whole-word edge cases

`replace "Person 1"` with "Jim" — what if the transcript has "Person 10" too? The replace must be exact-match on the speaker ID, not substring. Speaker IDs are typed values, not free text; the rename logic is a per-line mutation of the `speaker` field, not a string replace on the transcript. This is a small implementation detail that's easy to get wrong.

---

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|----------------|------------|
| Phase 0 — Scaffold / GPU detect | ROCm on Windows is broken in subtle ways (Pitfall 1) | First action on the desktop: install torch + faster-whisper + llama-cpp-python + run a 30-second transcription. Don't proceed until this works or the fallback is known. |
| Phase 1 — Storage / DB | SQLite state machine schema drift (Pitfall 9) | Schema versioning + atomic file-based state from day one. |
| Phase 2 — Model manager | First-run download silent failure (Pitfall 4) | Hash + size verification, resumable downloads, deferred-download UX. |
| Phase 3 — STT + chunking | Long-audio OOM despite chunking (Pitfall 5) | Build the chunker with VAD-aware boundaries and a fallback that halves chunk size on OOM. |
| Phase 4 — Orchestrator + WS | Front-end/back-end schema drift (Pitfall 10); state machine crash recovery (Pitfall 9) | OpenAPI-generated TypeScript types; resume-by-disk-truth. |
| Phase 5 — Local file ingest | Drag-and-drop of 4 GB files (Pitfall 11); browser-specific drop UX (Pitfall 18) | Streaming upload server-side; `react-dropzone` client-side. |
| Phase 6 — YouTube ingest | yt-dlp breaks when YouTube changes (Pitfall 6); ffmpeg format edge cases (Pitfall 16, 23) | Update-ytdlp button; format selectors pinned; clear error messages. |
| Phase 7 — Diarize | HuggingFace gating (Pitfall 3); long-audio accuracy (Pitfall 8) | Token UX; expected-N-speakers setting; long-audio diarize strategy. |
| Phase 8 — LLM + summaries | Structured outputs are flaky (Pitfall 7); multi-template schema drift (Pitfall 20) | Schema-constrained sampling; per-template unit tests; chunked summarization for long inputs. |
| Phase 9 — Transcript editor + export | Video/transcript sync (Pitfall 19); inline edit persistence (Pitfall 21) | Single `<video>` instance; file-as-truth edit persistence. |
| Phase 10 — Settings + per-machine | "Same UX on both machines" pressure (Pitfall 12); version pinning (Pitfall 13) | Honest first-run diagnostics; per-backend smoke test; content-hash model manager. |

---

## Confidence Assessment

| Pitfall area | Confidence | Reason |
|--------------|------------|--------|
| ROCm on Windows specifics (1) | LOW | This is the most volatile area; "current state" can't be verified without a desktop. Re-verify at Phase 0. |
| VRAM budget math (2) | HIGH | The math is well-known for these models at int8/Q4_K_M. |
| HuggingFace token gating (3) | HIGH | pyannote 3.1 has been gated for > 1 year. |
| First-run download pitfalls (4) | HIGH | The failure modes are well-known. |
| Long-audio OOM (5) | HIGH | Standard pattern, well-documented in faster-whisper / pyannote issues. |
| yt-dlp breakage (6) | HIGH | Happens monthly. |
| LLM structured outputs (7) | HIGH | Well-known local-LLM issue. |
| Diarization accuracy on long audio (8) | HIGH | Published pyannote benchmarks. |
| SQLite state machine (9) | MEDIUM | Pattern is well-known; the specific failure modes for this project are derivable. |
| Front-end/back-end drift (10) | HIGH | Two-codebase integration issue, standard. |
| Drag-and-drop large files (11) | HIGH | Well-known browser limit. |
| Per-machine config (12) | HIGH | Direct consequence of the project's two-hardware setup. |
| All "minor" pitfalls (22-30) | MEDIUM-HIGH | Each is a known issue in its respective library. |

## Gaps to Address

- **The actual state of ROCm on Windows for the 6800 XT in mid-2026** — cannot be verified in this environment. Phase 0 (the GPU-detect spike) is the first thing the project does. If the spike reveals a path that works, document it; if not, the desktop goes to CPU or WSL2.
- **The current faster-whisper / pyannote / llama-cpp-python version pins** — these should be confirmed in Phase 0 against PyPI / GitHub releases. Some versions of faster-whisper had a CUDA regression that affected the 8 GB laptop; the chosen version must be tested, not just installed.
- **Whether yt-dlp's current state (early-to-mid 2026) handles playlists with age-gated or region-locked videos** — the design treats this as "user-fixable via token" but the actual UX needs a Phase-6 spike.
- **The "expected N speakers" pyannote mode** — exists in pyannote's API; the exact knob name and reliability needs Phase-7 verification.
- **The "schema-constrained sampling" via llama.cpp GBNF** — should be prototyped in Phase 8 to confirm the four templates can be expressed as grammars; if not, fall back to a "validate and re-prompt" pattern.
- **The browser's actual streaming-upload support** — fetch with a ReadableStream body is well-supported in 2026 but the file-size threshold where browsers start buffering (rather than streaming) varies. Should be tested in Phase 5.

---

## Sources

- PROJECT.md (TranscriptionAndNotes) — hardware, requirements, decisions, two-machine constraint.
- Sibling research files in `.planning/research/` (ARCHITECTURE.md, FEATURES.md, STACK.md) — the architectural and stack decisions that the pitfalls are scoped against.
- Established knowledge of the local-transcription stack (faster-whisper / CTranslate2, pyannote.audio 3.x, llama.cpp / llama-cpp-python, yt-dlp, Silero VAD, FastAPI, React + Vite) and its known failure modes as of the 2025-2026 cycle.
- **Cannot verify in this environment:** exact PyPI / GitHub release versions of any dependency, the current state of ROCm-on-Windows community wheels, and recent (2026) yt-dlp issues. All version-dependent claims are MEDIUM confidence; the failure-mode shapes are MEDIUM-HIGH.

---

*Last updated: 2026-06-11 by pitfalls-dimension researcher*
