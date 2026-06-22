---
phase: 03-stt-adapter-audio-chunker-standalone-cli
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - app/models/stt/__init__.py
  - app/models/stt/protocol.py
  - app/models/stt/adapter.py
  - app/models/stt/chunker.py
  - app/cli/__init__.py
  - app/cli/transcribe.py
  - app/models/manager.py
  - pyproject.toml
  - tests/_stt_fake.py
  - tests/conftest.py
  - tests/test_stt_adapter.py
  - tests/test_stt_boundary.py
  - tests/test_chunker.py
  - tests/test_cli_transcribe.py
  - tests/test_manager_download.py
  - tests/test_download_routes.py
findings:
  critical: 1
  warning: 8
  info: 5
  total: 14
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-19
**Depth:** standard
**Files Reviewed:** 14 source + test files
**Status:** issues_found

## Summary

Phase 03 ships the STT Protocol + FasterWhisperAdapter, the windowed audio
chunker with OOM split-both-halves retry, the standalone `transcribe` CLI,
and the cross-phase `ModelManager._ensure_snapshot_downloaded` fix. The D-08
int8 verification, SC-4 import boundary, and Codex HIGH split-both-halves
coverage are correctly implemented and test-pinned.

The most significant defect is a **typed-error escape hatch in the CLI**:
`main` catches only `RuntimeError`, but `ModelManager.ensure_downloaded`
raises `ModelGatedError` / `ModelIntegrityError` / `ModelManagerError` (which
inherit from `Exception`, not `RuntimeError`). A gated-repo or SHA-mismatch
failure during the CLI's `asyncio.run(manager.ensure_downloaded(...))`
propagates as a raw traceback instead of a clean exit-1 stderr line,
breaking the documented exit-code contract ("2 for bad input vs runtime
errors"). Additional warnings cover the snapshot fast-path's missing
integrity check, the `--device rocm` choice with no working codepath, the
chunker's overlap-dedupe using the theoretical chunk end rather than the
actual last-segment end, and the `os.environ["HF_HUB_DISABLE_XET"]`
manipulation being unsafe under concurrent downloads.

## Critical Issues

### CR-01: CLI does not catch ModelManager typed errors — gated-repo / integrity failures escape as tracebacks

**File:** `app/cli/transcribe.py:210, 236-240`
**Issue:** The CLI's `except RuntimeError as exc:` handler is the only
exception trap around the transcribe pipeline. However
`asyncio.run(manager.ensure_downloaded(spec, category))` (line 210) runs
*before* the `try` block opens at line 215, and even inside the `try`,
`manager.ensure_downloaded` can raise `ModelGatedError`,
`ModelIntegrityError`, `VramBudgetExceeded`, `ConcurrentModelRefused`, or
`ModelManagerError` (e.g. `RepositoryNotFoundError`). All of these inherit
from `ModelManagerError(Exception)`, **not** from `RuntimeError`, so they
bypass the `except RuntimeError` handler and surface to the user as a full
Python traceback. The phase brief requires clean exit-code semantics
("2 for bad input vs runtime errors"); a gated-repo error (the documented
"add HF token in settings" UX path) currently produces a stack trace
instead of a one-line stderr message and exit code 1.

This is compounded by the fact that `ensure_downloaded` is called
**outside** the `try/finally` that owns `adapter.unload()` — but since the
adapter has not been constructed yet at that point, that part is safe.
The real defect is the narrow `RuntimeError` filter on a path that raises
typed siblings of `Exception`.

**Fix:**
```python
# Wrap the whole post-bootstrap pipeline (download + load + transcribe + write)
# in a try/except that catches BOTH RuntimeError and ModelManagerError.
from app.models.manager import ModelManagerError

adapter: FasterWhisperAdapter | None = None
try:
    model_path = asyncio.run(manager.ensure_downloaded(spec, category))
    adapter = FasterWhisperAdapter(model_path=str(model_path), device=device, compute_type=compute_type)
    adapter.load()
    transcript = transcribe_file(adapter, str(file_path), language=args.language, job_id=file_path.stem)
    asyncio.run(atomic_write_json(out_path, transcript.model_dump()))
    print(f"language={transcript.language} segments={len(transcript.segments)} -> {out_path}")
    return 0
except (RuntimeError, ModelManagerError) as exc:
    print(str(exc), file=sys.stderr)
    return 1
finally:
    if adapter is not None:
        adapter.unload()
```

## Warnings

### WR-01: Snapshot fast-path trusts `config.json` presence with no integrity/wholeness check

**File:** `app/models/manager.py:456-458`
**Issue:** `_ensure_snapshot_downloaded` returns the spec directory as soon
as `config.json` exists, skipping `snapshot_download` entirely. If a prior
run was interrupted after `config.json` was written but before
`model.bin` / sharded weights / tokenizer finished, the fast-path returns a
corrupt snapshot. `WhisperModel(<dir>)` then fails at load with an opaque
"weight file not found" error, and every subsequent CLI invocation keeps
hitting the same fast-path (no self-healing). The single-file path has a
SHA-verify + bounded re-download guard; the snapshot path has none.
**Fix:** Either call `snapshot_download` unconditionally (it is idempotent
and re-fetches only missing files), or add a minimal wholeness sentinel
(e.g. require both `config.json` AND `model.bin` AND a `.snapshot_complete`
marker written atomically after `snapshot_download` returns).

### WR-02: `--device rocm` is accepted by argparse but has no working codepath

**File:** `app/cli/transcribe.py:131, 199-204, 61-70`
**Issue:** `choices=["auto", "cuda", "cpu", "rocm"]` advertises `rocm` as a
valid choice, and `--device rocm` is forwarded verbatim as the `device`
argument to `FasterWhisperAdapter` → `WhisperModel(device="rocm", ...)`.
ctranslate2 has no ROCm device string and will raise at load time. The
project memory note ("ROCm is best-effort and must NOT block the roadmap;
CPU fallback acceptable") implies a fallback, not a silent guaranteed
failure. Additionally, `_default_compute_type("rocm")` falls through to
`"int8"` (the CPU branch), so the compute_type and device are
inconsistent (CPU compute_type with a ROCm device string).
**Fix:** Either drop `"rocm"` from the choices, or remap `args.device ==
"rocm"` to `"cpu"` (with a stderr warning) before constructing the
adapter, mirroring the `device_for` seam's CPU fallback for unsupported
backends.

### WR-03: Overlap-dedupe drops based on theoretical chunk end, not actual last-segment end

**File:** `app/models/stt/chunker.py:168, 179-180`
**Issue:** `prev_chunk_end = chunk_start + chunk_seconds` is the chunk's
*theoretical* end (e.g. `chunk_start + 900.0`). The dedupe then drops
every next-chunk segment whose `abs_start < prev_chunk_end`. If the
previous chunk's actual last segment ended at `chunk_start + 850.0`
(Whisper did not produce speech in the last 50 s), the next chunk's
segments in `[chunk_start+870, chunk_start+900]` (the 30 s overlap window)
are dropped even though they cover audio the previous chunk never
transcribed. This is the standard overlap-dedupe heuristic, but with
sparse audio (long silences) it can drop legitimately uncovered speech.
The docstring acknowledges this is a heuristic; flagging because the
phase brief lists "no over/under-drop" as a focus area.
**Fix:** Track `prev_chunk_end` as the previous chunk's actual last
segment `end_s` (max of kept segments' `abs_end`), falling back to
`chunk_start + chunk_seconds` only if the previous chunk emitted zero
segments. This makes the dedupe conservative (never drop uncovered
audio) instead of aggressive.

### WR-04: `os.environ["HF_HUB_DISABLE_XET"]` mutation is unsafe under concurrent downloads

**File:** `app/models/manager.py:378-427, 492-507`
**Issue:** Both the single-file and snapshot paths set
`os.environ["HF_HUB_DISABLE_XET"] = "1"` around the
`asyncio.to_thread(...)` call and restore it in `finally`. Because
`os.environ` is process-global, two concurrent downloads (e.g. two HTTP
clients hitting `POST /models/{id}/download` simultaneously, or the CLI
sharing a process with another caller) race: one's `finally` restore can
un-set the variable while the other's worker thread is still reading it.
The single-file path's `inspect.signature` kwarg (`hf_xet=False`) is the
thread-safe half of the belt-and-suspenders; the env-var half is not.
**Fix:** Drop the env-var manipulation and rely solely on the
`hf_xet=False` kwarg on versions that support it; on older versions
without the kwarg, accept the Xet default (the resume scanner contract is
already broken on old `huggingface_hub`). Alternatively, pass the env var
only via the `asyncio.to_thread` callable's closure (e.g. set it inside
the threaded function and restore inside the same thread before return).

### WR-05: Chunker overlap-dedupe can drop chunk-0 segments with tiny negative `start_s`

**File:** `app/models/stt/chunker.py:144, 168`
**Issue:** `prev_chunk_end` is initialized to `0.0` for chunk 0 (no
previous chunk). The dedupe rule `if abs_start < prev_chunk_end: continue`
then drops any chunk-0 segment whose absolute start is negative.
Real faster-whisper VAD segments can occasionally start at `0.0` but
edge-segment timestamps have been observed to be slightly negative on
some audio (VAD lookback). Dropping the very first segment of the whole
transcript is a silent correctness loss the FakeAdapter tests cannot
catch (the fake emits starts at `i * step >= 0`).
**Fix:** Initialize `prev_chunk_end = -float("inf")` (or use a sentinel
`prev_chunk_end = None` and skip the dedupe entirely when `None`).

### WR-06: `_get_token()` swallows all exceptions and returns `None`, silently downgrading gated-repo auth

**File:** `app/models/manager.py:201-211`
**Issue:** `_get_token` catches bare `Exception` and returns `None`. If
`current()` raises for any reason other than "settings not configured"
(e.g. a transient settings reload error, a Pydantic validation glitch),
the manager proceeds anonymously. For a gated repo this turns a clear
"add HF token" failure into a 401 loop. The CLI bootstraps settings
before calling `ensure_downloaded`, so in the CLI path `current()` is
populated; the concern is the route-layer path where a transient
`current()` failure would silently strip the token.
**Fix:** Catch only `RuntimeError` (the "settings not configured" signal)
and let other exceptions propagate, or log a warning before returning
`None`.

### WR-07: Two `asyncio.run` calls in one CLI invocation

**File:** `app/cli/transcribe.py:210, 229`
**Issue:** `asyncio.run(manager.ensure_downloaded(...))` and
`asyncio.run(atomic_write_json(...))` each create and tear down a fresh
event loop. This works today, but it means any state cached on the
manager's default executor or on `asyncio` primitives does not survive
between the download and the write. It also doubles the loop-creation
overhead and makes future refactors (e.g. wrapping the whole pipeline in
one async helper) non-trivial.
**Fix:** Wrap the whole post-bootstrap pipeline in a single
`async def _run(...)` and call `asyncio.run(_run(...))` once.

### WR-08: CLI catches only `RuntimeError` — non-RuntimeError exceptions (OSError, PermissionError, json encode errors) escape as tracebacks

**File:** `app/cli/transcribe.py:236-240`
**Issue:** The `except RuntimeError` handler misses `OSError` from
`atomic_write_json` (disk full, permission denied on the output path),
`UnicodeDecodeError` from `decode_audio`, `ValueError` from a malformed
audio container, etc. The phase brief's "let `atomic_write_json` report
write failures clearly" intent is undermined: a clear error message is
raised but then escapes as a traceback instead of a clean exit-1 stderr.
**Fix:** Broaden the handler to `except Exception as exc:` (or at least
`except (RuntimeError, OSError, ModelManagerError) as exc:`), keeping the
"preserve raw message" behavior.

## Info

### IN-01: `if TYPE_CHECKING: import numpy.ndarray` is not a real submodule import

**File:** `app/models/stt/protocol.py:40-41`
**Issue:** `numpy.ndarray` is a class, not a submodule; `import
numpy.ndarray` would raise `ModuleNotFoundError` at runtime if the
`TYPE_CHECKING` block were ever executed. It is only safe because
`TYPE_CHECKING` is `False` at runtime. Type checkers may or may not
resolve it. The annotation is also a string (`"numpy.ndarray"`), so the
import is purely for the type checker's benefit.
**Fix:** Use `import numpy as np` under `TYPE_CHECKING` and annotate as
`"np.ndarray"` (or `from numpy.typing import NDArray`).

### IN-02: `transcribe_file` does not handle empty audio (0 samples)

**File:** `app/models/stt/chunker.py:105-110`
**Issue:** If `decode_audio` returns a 0-length array, `total_seconds =
0.0`, the fast path runs, and `adapter.transcribe(empty_array)` is called.
faster-whisper's behavior on empty audio is undefined (likely raises).
Not a regression — the prior chunker had the same gap — but worth a guard.
**Fix:** Add `if total_samples == 0: return Transcript(job_id=job_id,
language=language or "", segments=[])` after the decode.

### IN-03: `chunk_s` parameter drifts from actual audio length after recursive halving

**File:** `app/models/stt/chunker.py:234-240`
**Issue:** `mid = len(audio_slice) // 2` floors the split point, so the
right half has `ceil(orig / 2)` samples. The recursive call passes
`chunk_s = chunk_s / 2`, which is the theoretical half-duration, not the
actual `len(audio_slice[mid:]) / SAMPLE_RATE`. The `chunk_s` is only used
for the `FLOOR_SECONDS` comparison, so the drift is bounded by one
sample, but it is a latent inconsistency.
**Fix:** Compute `chunk_s` from the actual slice length inside the
recursive call: `chunk_s=len(audio_slice)/SAMPLE_RATE`.

### IN-04: `_transcribe_chunk_oom_safe` recursion merges left+right segments without intra-chunk dedupe

**File:** `app/models/stt/chunker.py:242-256`
**Issue:** When a chunk OOMs and is split, the left half's last segment
and the right half's first segment may overlap at the midpoint (Whisper
VAD can over-extend a segment past the slice boundary). The merged
`SttTranscription.segments` could contain a small overlap at the split
point. In practice Whisper's segment boundaries respect the audio slice,
so this is rare; flagging for completeness.
**Fix:** No action needed unless observed; if it occurs, apply the same
`abs_start < prev_end` dedupe at the split midpoint.

### IN-05: `transcribe_file` fast path returns `result.language` even when Whisper auto-detects a different language than the user forced

**File:** `app/models/stt/chunker.py:129`
**Issue:** `language=result.language if language is None else language`
returns the user-forced language verbatim, ignoring Whisper's detected
language. This is correct behavior (user override wins), but the
`result.language_probability` is also discarded silently. Not a bug;
documenting the data loss for future callers who might want the
probability.
**Fix:** None needed; consider surfacing `result.language_probability`
on the `Transcript` if a future schema revision adds it.

---

_Reviewed: 2026-06-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_