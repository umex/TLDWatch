---
phase: 03
plan: 03
subsystem: cli
tags: [cli, argparse, settings-bootstrap, model-manager, device-resolution, sc-5, sc-4, tdd, codex-high, deferred]
requires:
  - "03-01 (STTAdapter Protocol + FasterWhisperAdapter + faster-whisper/ctranslate2 pins)"
  - "03-02 (chunker.transcribe_file + decode_audio Protocol extension)"
  - "02-01 (device_for(backend, InferenceEngine.FASTER_WHISPER) — the SC-5 seam)"
  - "02-02 (ModelManager + get_spec/get_category + ensure_downloaded + configure_manager/get_manager)"
  - "01-03 (atomic_write_json)"
provides:
  - "app/cli/transcribe.py:main — the `transcribe` console_scripts entry point (D-03): argparse + settings/manager bootstrap + device/compute_type resolution + atomic write + finally-block unload + raw error preservation"
  - "app/cli/transcribe.py:_bootstrap_settings — load_settings_from_disk + configure BEFORE current() (PATTERNS CLI gap closed)"
  - "app/cli/transcribe.py:_get_or_configure_manager — configure_manager(ModelManager(settings)) before get_manager() when unconfigured (Codex HIGH)"
  - "app/cli/transcribe.py:_default_compute_type — int8_float16 on cuda, int8 elsewhere (D-04)"
  - "app/cli/__init__.py — empty package init"
  - "pyproject.toml [project.scripts] transcribe entry (declared HERE per Codex HIGH, not in 03-01)"
  - "tests/test_cli_transcribe.py — 14 tests covering SC-5 device resolution, --device auto as valid choice, D-04 defaults/override, D-07 --language force, default --out, atomic write, stdout summary, V5 path validation, SC-4 no-faster-whisper, W2 bootstrap ordering, Codex HIGH manager ordering, finally-block unload"
affects:
  - "Phase 4 (job orchestrator — the CLI is the runnable end-to-end slice the orchestrator composes with the queue/WebSocket)"
  - "Phase 5 (local file ingest — the CLI's atomic_write_json output shape is the transcript contract the UI renders)"
  - "Phase 10 (settings panel — exposes the same settings.backend the CLI reads; --device auto is the user-facing seam)"
tech-stack:
  added: []
  patterns:
    - "Standalone CLI settings bootstrap: load_settings_from_disk -> configure -> current (no FastAPI lifespan) — the PATTERNS gap closed behaviorally"
    - "Standalone CLI model-manager bootstrap: try get_manager(); on RuntimeError configure_manager(ModelManager(settings)) then get_manager() — mirrors manager.py lines 554-567 (Codex HIGH)"
    - "SC-5 device resolution: --device auto (default) -> device_for(settings.backend, InferenceEngine.FASTER_WHISPER) — same command, no per-machine flags"
    - "Raw error preservation: except RuntimeError prints str(exc) to stderr (Codex MEDIUM — never mask int8/CUDA-DLL errors as generic failure)"
    - "finally-block adapter.unload() (Codex suggestion — VRAM cleanup on transcription/write error)"
    - "V5 path validation: input exists + --out parent EXISTS (writability NOT pre-checked — cross-platform unreliable; atomic_write_json reports write failures with raw message)"
    - "TDD RED/GREEN cycle (RED collection on missing app.cli.transcribe, then GREEN implementation + entry-point declaration)"
key-files:
  created:
    - app/cli/__init__.py
    - app/cli/transcribe.py
    - tests/test_cli_transcribe.py
  modified:
    - pyproject.toml
decisions:
  - "Default --out is <input>.<stem>.transcript.json (Path.with_suffix) — the accepted interpretation of SC-1's 'writes transcript.json' per Codex MEDIUM, not a literal 'transcript.json'"
  - "--device 'auto' is a VALID argparse choice alongside cuda/cpu/rocm (Codex HIGH regression guard: test_device_auto_is_valid_choice)"
  - "[project.scripts] transcribe declared HERE, NOT in 03-01 — declaring it before app.cli.transcribe exists breaks editable installs (Codex HIGH)"
  - "transcript.job_id = input filename stem (the CLI does NOT create a data/jobs/<id>/ dir per D-03)"
  - "compute_type default int8_float16 (cuda) / int8 (cpu, ROCm->CPU) — D-04; --compute-type overrides"
  - "Writability of --out parent NOT pre-checked (Codex MEDIUM); parent EXISTS is checked; atomic_write_json reports write failures with its raw message"
  - "Adapter.unload() in a finally block (Codex suggestion — VRAM released even on transcription/write errors)"
patterns-established:
  - "CLI bootstrap order: _bootstrap_settings() before current(); _get_or_configure_manager() before any successful get_manager() — both behaviorally guarded by tests (W2 + Codex HIGH)"
  - "CLI is a thin caller: imports Protocol + transcribe_file + FasterWhisperAdapter; NEVER imports faster_whisper or ctranslate2 (SC-4)"
requirements-completed: [TRANS-01, INGEST-06]
metrics:
  duration: ~25 min (excludes deferred human-verify wait)
  completed: 2026-06-19
  tasks: 3 (2 code + 1 human-verify checkpoint)
  files: 4
---

# Phase 03 Plan 03: Standalone `transcribe` CLI Summary

One-liner: Standalone `transcribe` console_scripts CLI with `--device auto` resolving CUDA/CPU from persisted settings via `device_for` (SC-5), standalone settings+model-manager bootstrap (PATTERNS gap + Codex HIGH), atomic write, finally-block unload; SC-5 desktop CPU half VERIFIED end-to-end (3.09 GB snapshot, 20 segments, language=en), laptop CUDA half DEFERRED.

## What Was Built

### app/cli/transcribe.py
- `def main() -> int` — the `transcribe` console_scripts entry point (D-03). argparse with: positional `file`; `--preset {small,balanced,large}` default `balanced`; `--device {auto,cuda,cpu,rocm}` default `auto` (**Codex HIGH**: `auto` IS in choices so `--device auto` is accepted — `test_device_auto_is_valid_choice` regression guard); `--language <code>` default `None`; `--compute-type {int8,int8_float16,float16,int8_float32}` default `None`; `--out <path>` default `<input>.transcript.json` (Path.with_suffix — the accepted interpretation of SC-1 per Codex MEDIUM); `--verbose`.
- `def _bootstrap_settings() -> None` — **the PATTERNS CLI settings-bootstrap gap closed**: standalone CLI has no FastAPI lifespan, so `current()` would raise. Calls `load_settings_from_disk()` (reads `bootstrap_settings_path()` when path=None) then `configure(settings)` BEFORE any `current()` call. FileNotFoundError is surfaced as a clear stderr message + exit 2.
- `def _get_or_configure_manager(settings) -> ModelManager` — **Codex HIGH precise model-manager bootstrap** (mirrors manager.py lines 554-567): `try: get_manager()`; on `RuntimeError` (unconfigured, as in a standalone CLI), `configure_manager(ModelManager(settings))` then `get_manager()`. Guarantees `configure_manager` runs BEFORE a successful `get_manager()` when the manager was unconfigured.
- `def _default_compute_type(device: str) -> str` — D-04: `int8_float16` on cuda, `int8` elsewhere (CPU and ROCm->CPU both use int8; CTranslate2 has no ROCm path per D-05).
- V5 path validation: `Path(args.file).resolve()` + `exists()` check (returns exit code 2 with `f"error: input file not found: {file_path}"` on missing); `--out` parent-dir EXISTS check (writability NOT pre-checked — Codex MEDIUM: cross-platform unreliable; `atomic_write_json` reports write failures with its raw message).
- Device resolution (SC-5): `device = args.device if args.device != "auto" else device_for(settings.backend, InferenceEngine.FASTER_WHISPER)` — same command on both machines, no per-machine flags.
- `try:` block runs `transcribe_file(adapter, str(file_path), language=args.language, job_id=file_path.stem)` (D-07 — `language=None` auto-detects; `--language` forces and skips detect), then `asyncio.run(atomic_write_json(out_path, transcript.model_dump()))` (Phase 1 D-04 atomic writes), then prints the one-line stdout summary `f"language={transcript.language} segments={len(transcript.segments)} -> {out_path}"`. Returns 0.
- `except RuntimeError as exc:` prints the RAW `str(exc)` to stderr (**Codex MEDIUM**: do NOT mask int8-verification or CUDA-DLL errors as a generic failure) and returns 1 (no traceback).
- `finally:` block calls `adapter.unload()` guarded by `if 'adapter' in locals() and adapter is not None:` (**Codex suggestion**: VRAM cleanup on error — unload runs even when `transcribe_file` or `atomic_write_json` raised).
- SC-4 boundary preserved: imports only the Protocol + `transcribe_file` + `FasterWhisperAdapter` + `device_for` + settings/manager/storage seams; NEVER imports `faster_whisper` or `ctranslate2` (`test_cli_does_not_import_faster_whisper` enforces via `inspect.getsource`).

### app/cli/__init__.py
- Empty package init (mirrors `app/jobs/__init__.py` minimal convention).

### pyproject.toml
- Added `[project.scripts]` table (after `[project]`, before `[project.optional-dependencies]`) with `transcribe = "app.cli.transcribe:main"`. Declared HERE, NOT in 03-01 (Codex HIGH: declaring it before `app.cli.transcribe` exists breaks editable installs / smoke tests in Waves 1-2). 03-01 added only the faster-whisper + ctranslate2 dependency pins.

### tests/test_cli_transcribe.py
Fourteen tests (TDD contract) — module docstring maps each to SC-5 / D-04 / D-07 / TRANS-01 / T-03-02 / Codex HIGH (--device auto, bootstrap+manager ordering) / Codex MEDIUM (path validation, error preservation):
- `test_device_resolution_from_settings_cuda` / `test_device_resolution_from_settings_cpu` (SC-5 — `--device auto` resolves from `settings.backend` via `device_for`)
- `test_device_auto_is_valid_choice` (Codex HIGH regression guard — `--device auto` does not raise SystemExit(2) from argparse)
- `test_default_compute_type_per_device` (D-04 — cuda -> `int8_float16`, cpu -> `int8`)
- `test_compute_type_override` (D-04 escape hatch — `--compute-type int8_float32` wins over default)
- `test_language_force_skips_detect` (D-07 — `--language en` passes `language="en"`; omitted -> `language=None` auto-detect)
- `test_default_out_path` (Codex MEDIUM — `<input>.transcript.json` via `Path.with_suffix`)
- `test_atomic_write_called` (atomic_write_json called once with resolved out_path + `transcript.model_dump()`)
- `test_stdout_summary` (capsys — stdout contains `language=`, `segments=`, out path)
- `test_missing_file_errors` (V5 / T-03-02 — missing input exits non-zero with a clear stderr message; writability NOT asserted)
- `test_cli_does_not_import_faster_whisper` (SC-4 — `inspect.getsource` regex over the module)
- `test_bootstrap_settings_runs_before_current` (W2 — call recorder asserts `[load_settings_from_disk, configure, current]` order; behavioral guard, not source-textual)
- `test_cli_configures_model_manager_when_unconfigured` (Codex HIGH — `configure_manager` runs before the successful `get_manager()` when the manager was unconfigured)
- `test_adapter_unload_on_error` (Codex suggestion + MEDIUM — `adapter.unload()` called in finally; raw `RuntimeError("boom")` message preserved to stderr)

## Test Results

| Check | Result |
|-------|--------|
| `pytest tests/test_cli_transcribe.py -x` | 14 passed (GREEN after Task 2; RED after Task 1 as expected — ImportError on `app.cli.transcribe`) |
| `pytest -q` (full suite) | **220 passed** (no regressions) |
| `pip install -e .` + `transcribe --help` | entry point resolves (smoke check — Codex HIGH) |
| SC-4 boundary grep over `app/` | matches exactly `app/models/stt/adapter.py` (CLI added no new faster_whisper/ctranslate2 import sites) |
| `test_bootstrap_settings_runs_before_current` | exits 0 (W2 behavioral guard on call order) |
| `test_cli_configures_model_manager_when_unconfigured` | exits 0 (Codex HIGH — configure_manager before get_manager) |
| `test_device_auto_is_valid_choice` | exits 0 (Codex HIGH — `--device auto` accepted) |
| `test_adapter_unload_on_error` | exits 0 (finally-block unload + raw error preserved) |

## TDD Gate Compliance

- RED gate commit: `14d701d test(03-03): add CLI Wave 0 stubs (--device auto, bootstrap+manager ordering, unload on error)` — tests collected and failed on missing `app.cli.transcribe` (ImportError, NOT a fixture collection error)
- GREEN gate commit: `9131e5e feat(03-03): implement transcribe CLI + settings+manager bootstrap + device resolution + atomic write + declare entry point` — all 14 tests pass
- REFACTOR: no separate refactor commit needed (implementation was already minimal)

## SC-5 Human-Verify Checkpoint (Task 3) — RESOLUTION

**Status: PARTIAL — desktop CPU half VERIFIED; laptop CUDA half DEFERRED (does not block Phase 03 completion; the CPU half proves the "same command, no code changes" seam).**

### SC-5 desktop CPU half: VERIFIED

The user ran the default command on the CPU desktop:
```
transcribe test.mp4 --out out.json
```
Result: downloaded the **full 7-file `Systran/faster-whisper-large-v3` snapshot (3.09 GB via `snapshot_download`)** — proving the cross-phase `051b0302` fix works end-to-end (no 404 on a fabricated `Systran--faster-whisper-large-v3.bin`). Then:
```
language=en segments=20 -> E:\Projects\TranscriptionAndNotes\out.json
```
`out.json` was written with a valid `Transcript` (20 segments, `language=en`) on CPU with `compute_type=int8`, **no code changes vs the laptop path** (device resolved via `device_for` from persisted settings → CPU fallback). The runnable end-to-end slice `transcribe <file>` → `transcript.json` works.

### SC-5 laptop CUDA half + Open Q1: DEFERRED

The user could not test on the CUDA laptop at this time. Recorded as a **DEFERRED human-verification item**: the laptop must confirm:
1. `ctranslate2.get_supported_compute_types('cuda',0)` returns `int8`/`int8_float16` (NOT just `float32`) — i.e. the CUDA runtime libs `cublas64_12.dll` / `cudart12.dll` are findable;
2. `transcribe <file>` runs end-to-end on CUDA with default `compute_type=int8_float16`; and
3. whether `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` pip packages were required.

This does NOT block Phase 03 completion (the desktop CPU half proves the SC-5 "same command, no code changes" seam); the laptop CUDA half is an explicit deferred follow-up.

## Phase-2 model-manager defect surfaced by the SC-5 checkpoint

The first real end-to-end CLI run 404'd on a fabricated `Systran--faster-whisper-large-v3.bin` (single-file GGUF path was being used for an STT repo whose `spec.file is None`). This exposed a Phase-2 `ModelManager` defect: snapshot repos (`file=None`) were routed through the single-file `hf_hub_download` path instead of `snapshot_download`.

**Cross-phase fix (already committed — NOT re-committed here):** commit `051b0302 fix(models): file=None snapshot repos use snapshot_download, return repo dir (03-03 SC-5 checkpoint)`. Routes `spec.file is None` repos through `snapshot_download` and returns the repo directory so `WhisperModel(<dir>)` loads weights+config+tokenizer. Single-file (GGUF LLM) path unchanged. +3 regression tests; full suite 220 passed (the count above includes these). Reference: this fix is what made the SC-5 desktop CPU half succeed — the 3.09 GB / 7-file download is `snapshot_download` in action.

## Task Commits

1. **Task 1 (RED): CLI Wave 0 test stubs** — `14d701d` (test) — 14 failing CLI tests covering SC-5 device resolution, `--device auto`, D-04 compute_type defaults/override, D-07 language force, default --out, atomic write, stdout summary, V5 path validation, SC-4 boundary, W2 bootstrap ordering, Codex HIGH manager ordering, finally-block unload.
2. **Task 2 (GREEN): `transcribe` CLI + entry point** — `9131e5e` (feat) — `app/cli/transcribe.py` + `app/cli/__init__.py` + `[project.scripts] transcribe` in `pyproject.toml`. All 14 tests GREEN; full suite green; `transcribe --help` resolves.
3. **Cross-phase manager fix (already committed — NOT re-committed)** — `051b0302` (fix) — Phase-2 `ModelManager` defect surfaced by Task 3's first real CLI run; routes `file=None` repos through `snapshot_download`. +3 regression tests.
4. **Task 3 (human-verify): SC-5 checkpoint** — no code; resolution recorded above (CPU VERIFIED, CUDA DEFERRED).

## Files Created/Modified

- `app/cli/__init__.py` — empty package init (created)
- `app/cli/transcribe.py` — argparse CLI + main + `_bootstrap_settings` + `_get_or_configure_manager` + `_default_compute_type` (created)
- `tests/test_cli_transcribe.py` — 14 CLI tests (created)
- `pyproject.toml` — `[project.scripts] transcribe = "app.cli.transcribe:main"` (modified)

## Decisions Made

- Default `--out` is `<input>.transcript.json` via `Path.with_suffix` (the accepted interpretation of SC-1 per Codex MEDIUM — not a literal `transcript.json`).
- `--device auto` is a VALID argparse choice (Codex HIGH — `test_device_auto_is_valid_choice` is the regression guard).
- `[project.scripts] transcribe` declared HERE (03-03), NOT in 03-01 — declaring it before `app.cli.transcribe` exists breaks editable installs (Codex HIGH).
- `transcript.job_id` = the input filename stem; the CLI does NOT create a `data/jobs/<id>/` dir (D-03 — that's the orchestrator's job in Phase 4).
- Writability of `--out` parent NOT pre-checked (Codex MEDIUM); parent EXISTS is checked; `atomic_write_json` reports write failures with its raw message.
- `adapter.unload()` runs in a `finally` block (Codex suggestion — VRAM released even on transcription/write errors).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug (cross-phase)] `ModelManager` routed `file=None` (snapshot) repos through the single-file `hf_hub_download` path, producing a 404 on a fabricated `<repo_id>.bin`**
- **Found during:** Task 3 (SC-5 checkpoint — first real end-to-end CLI run)
- **Issue:** STT specs have `spec.file is None` (multi-file snapshot repos); the manager was treating them as single-file downloads, fabricating a `<repo_id>--<filename>.bin` path that 404'd.
- **Fix:** Commit `051b0302` routes `spec.file is None` repos through `snapshot_download` and returns the repo directory so `WhisperModel(<dir>)` loads weights+config+tokenizer. Single-file (GGUF LLM) path unchanged. +3 regression tests.
- **Files modified:** `app/models/manager.py` (and test files)
- **Verification:** Full suite 220 passed; the SC-5 desktop CPU half then succeeded (3.09 GB / 7-file snapshot download via `snapshot_download`).
- **Committed in:** `051b0302` (NOT re-committed here — cross-phase fix already in history)

**2. [Continuation — checkpoint resolution recorded, no code]** Task 3 is a blocking-human-verify checkpoint; this SUMMARY records its resolution (CPU half VERIFIED, CUDA laptop half DEFERRED) rather than producing code.

---

**Total deviations:** 1 auto-fixed cross-phase bug (Rule 1) + 1 checkpoint resolution (no code).
**Impact on plan:** The cross-phase manager fix was necessary for SC-5 to pass at all (without it, every real STT model download 404'd). No scope creep.

## Issues Encountered

- The SC-5 checkpoint surfaced a latent Phase-2 `ModelManager` bug (`file=None` repos). Because the automated suite mocks the download path, this could only be caught by a real end-to-end CLI run — exactly what the blocking-human-verify checkpoint is for. The fix is a separate commit (`051b0302`) and is referenced, not duplicated, in this plan's commits.

## Open Follow-ups (tracked, NOT implemented in this plan)

1. **Laptop CUDA SC-5 + Open Q1 (DEFERRED human-verify).** The laptop must confirm: (a) `ctranslate2.get_supported_compute_types('cuda',0)` returns `int8`/`int8_float16` (not just `float32`); (b) `transcribe <file>` runs end-to-end on CUDA with default `compute_type=int8_float16`; and (c) whether `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12` pip packages were required. Does NOT block Phase 03 (CPU half proves the seam); the laptop half is an explicit deferred follow-up.
2. **`nvidia-*-cu12` dependency question.** UNKNOWN until the laptop test. If the laptop required `nvidia-cublas-cu12`/`nvidia-cuda-runtime-cu12`, they MUST be added to `pyproject.toml` (tracked here; do NOT add without the laptop confirmation — the packages were [ASSUMED] in the RESEARCH Package Legitimacy Audit and adding them is a separate decision per Codex HIGH).
3. **Snapshot-download live SSE byte-progress test coverage gap.** Commit `051b0302` moved 3 download-route tests (`test_download_duplicate_in_flight_returns_409`, `test_download_progress_sse_streams_live`, `test_download_progress_byte_level`) from `small.stt` (`file=None`) to `small.llm` (single-file), so the `file=None` / `snapshot_download` codepath's live SSE byte-progress is no longer covered by the suite (single-file GGUF progress is still covered). Add a real snapshot-progress test in a later phase.

## Known Stubs

None. The CLI is fully wired: argparse → settings/manager bootstrap → device resolution → `transcribe_file` → `atomic_write_json` → stdout summary. No placeholder data, no TODO/FIXME, no empty defaults flowing anywhere. The `--verbose` flag is wired (sets the logging level to INFO before the adapter build so the chunker's per-chunk progress logs are visible).

## Threat Flags

None. The threat model in the plan (T-03-02 path validation, T-03-05 raw error to stderr, T-03-06 checkpoint-gated pip install, T-03-07 VRAM-release-on-error, T-03-SC) is accepted/mitigated as documented. No new security-relevant surface was introduced beyond what the plan declared: the checkpoint-gated `nvidia-*-cu12` install is tracked as follow-up #2 (NOT silently added to `pyproject`), and the cross-phase manager fix (`051b0302`) did not introduce new network/auth/file surface — it changed which already-approved HuggingFace download path is used for `file=None` repos.

## Self-Check: PASSED

- All 4 created/modified files exist on disk: `app/cli/__init__.py`, `app/cli/transcribe.py`, `tests/test_cli_transcribe.py`, `pyproject.toml`
- RED gate commit `14d701d` found in git log
- GREEN gate commit `9131e5e` found in git log
- Cross-phase manager fix commit `051b0302` found in git log (`git rev-parse --short=8 051b030` → `051b0302`; `git log --oneline` displays it truncated as `051b030`)
- Full suite 220 passed (no regressions); CLI tests 14 passed

## Next Phase Readiness

- Phase 3 vertical slice complete: `transcribe <file>` → `transcript.json` works end-to-end on CPU (SC-5 desktop half verified). The orchestrator (Phase 4) composes the same adapter + chunker + atomic_write_json path inside the job state machine.
- The `STTAdapter` Protocol + `FasterWhisperAdapter` + chunker + CLI form the SC-4 boundary: only `app/models/stt/adapter.py` imports `faster_whisper`/`ctranslate2`. The CLI and the future orchestrator import only the Protocol.
- **Blockers/concerns:** the laptop CUDA SC-5 half (follow-up #1) and the `nvidia-*-cu12` question (follow-up #2) are deferred — they do not block Phase 4 planning but should be closed before a release that claims "runs on CUDA out of the box."
- Phase 3 is ready to surface for `/gsd-review` (D-09 cross-AI review is a downstream orchestrator concern, NOT a Phase 3 implementation deliverable).

---
*Phase: 03-stt-adapter-audio-chunker-standalone-cli*
*Completed: 2026-06-19*