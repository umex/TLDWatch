---
phase: 3
reviewers: [codex]
reviewed_at: 2026-06-19
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md, 03-03-PLAN.md]
note: >
  Single-reviewer run. Gemini CLI could not authenticate (IneligibleTierError —
  Gemini Code Assist CLI deprecated for individuals; migrate to Antigravity to
  restore the Gemini reviewer). Ollama local server could not process the
  192KB review prompt (exceeded the local model context window). Re-run
  /gsd-review --phase 3 --gemini (after migrating to Antigravity) or with a
  trimmed prompt for a local model to add perspectives.
---

# Cross-AI Plan Review — Phase 3

> Single-reviewer run (Codex only). Gemini and Ollama failed to produce reviews
> (see note in frontmatter). The "Consensus Summary" below is therefore
> Codex's synthesis alone — not a cross-reviewer consensus.

## Codex Review

## Plan 03-01 Review

### Summary

Plan 03-01 is strong on architectural boundaries and testability. It correctly establishes the STT abstraction first, keeps `faster-whisper`/`ctranslate2` isolated, and adds the important int8 verification guard early. The main risks are around dependency timing, type-shape drift between `SttSegment` and `TranscriptSegment`, and adding the `transcribe` console script before the CLI module exists.

### Strengths

- Clear `STTAdapter` Protocol boundary directly supports SC-4.
- Lazy import discipline is well aligned with existing Phase 2 model-boundary patterns.
- Int8 verification is a valuable early guard against silent compute fallback.
- Tests avoid real GPU/model downloads, which is appropriate for CI.
- Boundary test is a good regression guard.
- Fake adapter lays useful groundwork for chunker and CLI tests.

### Concerns

- **HIGH:** Adding `[project.scripts] transcribe = "app.cli.transcribe:main"` in 03-01 before `app.cli.transcribe` exists may break editable installs, packaging metadata checks, or smoke tests before Wave 3.
- **MEDIUM:** The plan defines both `SttSegment` and existing `TranscriptSegment`, but the roadmap says output should be existing `Transcript`/`TranscriptSegment`. This extra result type may cause conversion churn and field drift.
- **MEDIUM:** `tests/conftest.py` fixture imports the real `faster_whisper` module. If dependencies are not installed before tests run, collection may fail despite the lazy-import goal.
- **MEDIUM:** The boundary test regex may match plan strings, comments, or docstrings inside non-adapter source files if future comments mention imports. That can make the test brittle.
- **LOW:** `math.exp(avg_logprob)` as confidence is acceptable, but the semantics are weak. It should be documented as a proxy, not true calibrated confidence.
- **LOW:** `unload()` only setting `_model = None` may not actually release GPU memory promptly. Later implementation may need `gc.collect()` and CUDA cleanup if observed.

### Suggestions

- Move `[project.scripts]` addition to 03-03, or create a minimal `app/cli/transcribe.py` stub in 03-01 if the entry point is declared early.
- Prefer returning `TranscriptSegment` directly from `SttTranscription`, unless `SttSegment` has a concrete reason to exist.
- In tests, patch `sys.modules["faster_whisper"]` instead of importing the real package where possible.
- Make the boundary test parse Python AST imports instead of raw text, or at least ignore comments/docstrings.
- Add one positive int8-equivalence test: requested `int8`, actual `int8_float16` passes.
- Add a test that calling `transcribe()` before `load()` fails with a clear error.

### Risk Assessment

**MEDIUM.** The core architecture is sound, but the early console script and dependency import assumptions could cause execution friction. The plan achieves SC-4 and supports SC-3/TRANS-01 foundations, but it does not yet deliver an end-to-end runnable path.

---

## Plan 03-02 Review

### Summary

Plan 03-02 targets the hardest behavioral part of Phase 3: long-audio chunking, overlap stitching, and OOM retry. The plan captures the correct shape, especially the decision to route decoding through the adapter to preserve SC-4. The largest risk is algorithmic: the proposed OOM halve-and-retry loop appears to shrink a failing chunk without necessarily covering the omitted remainder, which can lose transcript content.

### Strengths

- Correctly preserves the `faster-whisper` import boundary by adding `adapter.decode_audio()`.
- Covers the main INGEST-05 behaviors with focused tests.
- Explicitly distinguishes OOM `RuntimeError` from unrelated runtime errors.
- Good decision to use `condition_on_previous_text=False` for chunked transcription.
- First-30-second language detection for chunked files aligns with SC-3/D-07.
- Constants make chunking thresholds testable and explicit.

### Concerns

- **HIGH:** OOM retry logic as written may truncate audio. If a 15-minute chunk OOMs and is retried as 7.5 minutes, the remaining 7.5 minutes of that original window may never be transcribed unless the scheduler splits the failed window into multiple subchunks.
- **HIGH:** Stitching by trimming segment timestamps to midpoint can create segments whose text spans audio that was partially discarded. For straddling segments, changing only `start_s` without changing text is imprecise.
- **MEDIUM:** Tests described may not catch content loss from OOM splitting. They assert success/non-empty, but not full time coverage.
- **MEDIUM:** Pre-decoding an entire very long file into memory could be large. Mono float32 16 kHz is manageable for hours, but “no size limit” means this should be bounded or documented.
- **MEDIUM:** `Transcript(schema_version=1, job_id=...)` may not match the actual model constructor depending on existing schema defaults. The plan should verify actual fields.
- **MEDIUM:** `prev_midpoint` formula needs careful handling for the final shorter chunk and for chunks shorter than overlap after halving.
- **LOW:** VAD may remove silent sections, so “continuous timestamps” should mean source-time timestamps are monotonic, not gap-free.
- **LOW:** Adding `decode_audio` to the Protocol in Wave 2 is reasonable, but it modifies the Wave 1 interface. This should be reflected back in 03-01 or planned upfront.

### Suggestions

- Replace shrink-only retry with recursive/window queue splitting: on OOM, split the failing interval into two half-sized intervals and process both, preserving coverage.
- Add a test asserting full coverage after OOM: segments from both halves of the originally failing chunk are present and offset correctly.
- Add tests for exact threshold behavior: exactly 30 minutes should be single-call; 30 minutes + 1 sample should chunk.
- Add tests for short final chunk, language override in chunked mode, and OOM below floor.
- Consider storing chunk intervals as `(start_sample, end_sample)` rather than deriving from mutable `chunk_s`.
- Make overlap dedupe segment-based: drop segments fully before midpoint and keep later segments; avoid mutating segment starts unless necessary.
- Document memory cost of full decode and revisit streaming decode later if very long files become problematic.

### Risk Assessment

**HIGH.** The plan is directionally right, but the OOM halve-and-retry behavior risks violating SC-2/TRANS-01 by silently losing part of the audio. Fixing the retry scheduler before implementation is important.

---

## Plan 03-03 Review

### Summary

Plan 03-03 completes the vertical slice and addresses the important CLI-specific gaps: settings bootstrap, device resolution, atomic write, and human verification for SC-5. It is well scoped as the end-to-end proof. The main risks are real-world setup reliability on Windows/CUDA, model-manager bootstrap assumptions, and a possible mismatch between test mocks and actual CLI dependency flow.

### Strengths

- Directly targets SC-1 and SC-5.
- Correctly treats SC-5 hardware verification as a blocking human checkpoint.
- Settings bootstrap before `current()` is explicitly tested.
- Device resolution through `device_for(..., FASTER_WHISPER)` supports the no-code-change hardware goal.
- Atomic write is correctly reused.
- Good coverage of CLI flags, output path, language override, and path validation.
- Avoids importing `faster-whisper`/`ctranslate2` in the CLI.

### Concerns

- **HIGH:** `--device` choices are listed as `["cuda","cpu","rocm"]` with default `"auto"`. In `argparse`, the default is not validated against choices, but help/semantics are awkward. If user passes `--device auto`, it will be rejected unless `"auto"` is in choices.
- **HIGH:** Model manager configuration is underspecified. `get_manager()` may fail if `configure_manager()` has not run. The plan says “or configure_manager if not configured,” but needs a precise implementation path.
- **HIGH:** CUDA runtime handling is left to human verification, which is acceptable for SC-5, but if the laptop needs `nvidia-*-cu12`, the app still has a silent-first-run risk unless the follow-up is mandatory.
- **MEDIUM:** Tests monkeypatching `current()` may bypass `_bootstrap_settings()`, potentially hiding integration issues unless the bootstrap-order test also exercises the normal path.
- **MEDIUM:** `Path.parent` writability check can be unreliable cross-platform. Better to check parent exists and attempt atomic write later, reporting errors clearly.
- **MEDIUM:** `with_suffix(".transcript.json")` turns `audio.wav` into `audio.transcript.json`, while the roadmap wording says writes `transcript.json`. Context allows default `<input>.transcript.json`, but plan should be explicit that SC-1 accepts this.
- **MEDIUM:** Catching all `RuntimeError` around transcribe/write may mask int8 verification or CUDA DLL errors as generic runtime failure. For a CLI this is okay, but messages must be preserved.
- **LOW:** `--preset` maps to registry specs, but tests should ensure `small/balanced/large` resolve correctly.
- **LOW:** `--verbose` logging behavior is mentioned but not included in tests.

### Suggestions

- Include `"auto"` in `--device` choices.
- Define exact manager bootstrap logic:
  - load settings
  - configure settings service
  - configure model manager if needed
  - then `get_manager()`
- Add a test where manager is unconfigured and CLI configures it successfully.
- Add a test that `adapter.unload()` runs in a `finally` block after transcription/write errors.
- Add a human-checkpoint follow-up rule: if `nvidia-*-cu12` packages are required, create a tracked task to add/document them before marking SC-5 fully closed.
- Preserve raw exception messages in stderr for CUDA/CT2 failures.
- Confirm whether output default should be `<input>.transcript.json` or a literal `transcript.json`; if the former, record it as accepted interpretation of SC-1.

### Risk Assessment

**MEDIUM.** The CLI plan is solid, but hardware verification and model-manager bootstrap are practical failure points. It likely achieves SC-1, SC-3, SC-4, and the CPU side of SC-5; the CUDA side depends on the checkpoint outcome.

---

## Overall Phase Review

### Summary

The three plans are mostly coherent and map well to Phase 3’s success criteria. The abstraction boundary, lazy imports, int8 verification, chunker, CLI, and human hardware checkpoint are all appropriate. The main issue to fix before execution is the chunker’s OOM retry design: it must split and preserve all audio, not merely shorten a failed chunk. The second major issue is tightening dependency/order assumptions around console script timing, settings/model-manager bootstrap, and CUDA runtime packaging.

### Success Criteria Coverage

- **SC-1:** Covered by 03-03 CLI, assuming output naming is accepted.
- **SC-2:** Partially covered, but OOM halve-and-retry needs redesign to avoid audio loss.
- **SC-3:** Covered through adapter auto-detect and chunked first-30s detection.
- **SC-4:** Strongly covered by Protocol, boundary tests, and lazy imports.
- **SC-5:** Covered by design plus blocking human verification, but CUDA runtime dependency remains the key external risk.

### Highest-Priority Fixes

- Fix OOM retry to split failed windows into smaller windows while preserving full coverage.
- Move `[project.scripts]` to 03-03 or add a CLI stub earlier.
- Include `"auto"` in CLI `--device` choices.
- Specify model-manager bootstrap exactly.
- Add tests for OOM full coverage, 30-minute threshold boundary, and adapter unload on CLI failure.
- Make CUDA runtime package outcome a tracked follow-up if human verification requires it.

### Overall Risk Assessment

**MEDIUM-HIGH.** The architecture is good and test strategy is thoughtful, but SC-2 has a correctness risk that could silently drop transcript content, and SC-5 depends on real CUDA runtime availability. With the chunker retry corrected and CLI bootstrap tightened, the phase risk drops to **MEDIUM**.

---

## Failed Reviewers

### Gemini — did not run
`IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals. To continue using Gemini, please migrate to the Antigravity suite of products: https://antigravity.google.` The installed `@google/gemini-cli` can no longer authenticate. Not a plan defect — an environment/auth issue. To restore the Gemini reviewer, migrate to the Antigravity CLI (`agy`) and re-run `/gsd-review --phase 3 --antigravity`.

### Ollama — did not run
The local Ollama server (localhost:11434) returned an empty response for the ~192KB / ~50K-token review prompt — the prompt exceeded the local model's context window. To get a local-model review, either run with a larger-context model or re-run with prompt-budget trimming configured (`review.max_prompt_tokens`).

---

## Consensus Summary

> **Single-reviewer note:** Only Codex reviewed the plans. There is no
> cross-reviewer agreement or divergence to report. The synthesis below is
> Codex's view only; treat it as one perspective, not a converged consensus.
> Re-running with Gemini (post-Antigravity migration) is recommended before
> execution to get an independent second opinion, per the project's
> `review.default_reviewers = ["codex","gemini"]` preference.

### Agreed Strengths
- Clear `STTAdapter` Protocol boundary directly supports SC-4 (03-01).
- Lazy import discipline aligns with Phase 2 model-boundary patterns; int8 verification is an early guard against silent compute fallback (03-01).
- Chunker correctly preserves the `faster-whisper` import boundary via `adapter.decode_audio()`; uses `condition_on_previous_text=False` and first-30s language detection aligned with SC-3/D-07 (03-02).
- CLI directly targets SC-1 and SC-5; treats SC-5 hardware verification as a blocking human checkpoint; reuses atomic write; avoids importing `faster-whisper`/`ctranslate2` in the CLI (03-03).
- Test strategies avoid real GPU/model downloads and lay groundwork (fake adapter, boundary tests) reusable across the phase.

### Agreed Concerns
- **HIGH (03-02):** OOM halve-and-retry may truncate audio — a 15-min chunk OOMing and retrying as 7.5 min can leave the remaining 7.5 min untranscribed unless the scheduler splits the failed window into multiple subchunks. Risks violating SC-2/TRANS-01 by silently losing content.
- **HIGH (03-02):** Stitching by trimming segment timestamps to midpoint can create segments whose text spans partially-discarded audio; mutating `start_s` without adjusting text is imprecise.
- **HIGH (03-03):** `--device` choices `["cuda","cpu","rocm"]` with default `"auto"` — passing `--device auto` is rejected unless `"auto"` is in choices.
- **HIGH (03-03):** Model manager configuration underspecified — `get_manager()` may fail if `configure_manager()` has not run; needs a precise bootstrap implementation path.
- **HIGH (03-03):** CUDA runtime handling left to human verification; if `nvidia-*-cu12` packages are required, silent-first-run risk remains unless the follow-up is mandatory.
- **HIGH (03-01):** `[project.scripts] transcribe = "app.cli.transcribe:main"` declared before `app.cli.transcribe` exists — may break editable installs, packaging metadata checks, or smoke tests before Wave 3.
- **MEDIUM (03-01):** Dual `SttSegment` / `TranscriptSegment` types may cause conversion churn and field drift; prefer returning `TranscriptSegment` directly.
- **MEDIUM (03-01):** `tests/conftest.py` fixture imports real `faster_whisper` — collection may fail if dependencies are not installed first, undermining the lazy-import goal.
- **MEDIUM (03-02):** Tests assert success/non-empty but not full time coverage, so they may not catch content loss from OOM splitting.
- **MEDIUM (03-03):** Tests monkeypatching `current()` may bypass `_bootstrap_settings()`, hiding integration issues unless the bootstrap-order test exercises the normal path.
- **MEDIUM (03-03):** Catching all `RuntimeError` around transcribe/write may mask int8 verification or CUDA DLL errors; raw messages must be preserved.

### Divergent Views
N/A — single reviewer.

### Overall Risk (per Codex)
**MEDIUM-HIGH.** Architecture and test strategy are sound, but SC-2 has a correctness risk (OOM retry could silently drop transcript content) and SC-5 depends on real CUDA runtime availability. With the chunker retry corrected to split-and-preserve and CLI bootstrap tightened, phase risk drops to **MEDIUM**.