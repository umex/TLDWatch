"""Standalone ``transcribe`` console_scripts entry point (D-03, SC-5).

This module ties the STT adapter (03-01) and the windowed audio chunker
(03-02) into the runnable end-to-end slice: ``transcribe <file>`` produces
a ``<input>.transcript.json`` (the accepted interpretation of SC-1 per
Codex MEDIUM -- the filename is ``<stem>.transcript.json``, not a literal
``transcript.json``).

GPU abstraction (SC-5): ``--device auto`` (the default) resolves the
device from the persisted ``settings.backend`` via
:func:`app.models.backend.device_for` with
:attr:`~app.models.diagnostics.InferenceEngine.FASTER_WHISPER`. The same
command runs on the CUDA laptop and the CPU desktop with no per-machine
flags. ``auto`` is a VALID argparse choice (Codex HIGH).

Bootstrap (PATTERNS CLI settings-bootstrap gap, tightened per Codex HIGH):
the CLI is a standalone entry point with NO FastAPI lifespan, so
:func:`app.settings.service.current` would raise. :func:`_bootstrap_settings`
runs :func:`load_settings_from_disk` then :func:`configure` BEFORE any
:func:`current` call (behavioral guard -- tested by
``test_bootstrap_settings_runs_before_current``). The model manager is
bootstrapped via :func:`_get_or_configure_manager`: when
:func:`get_manager` raises (unconfigured, as in a standalone CLI),
:func:`configure_manager` is called BEFORE the next :func:`get_manager`
call (Codex HIGH -- tested by ``test_cli_configures_model_manager_when_unconfigured``).

SC-4 boundary: this module NEVER imports ``faster_whisper`` or
``ctranslate2`` -- it depends on the STTAdapter Protocol +
:func:`app.models.stt.chunker.transcribe_file` + the
:class:`app.models.stt.FasterWhisperAdapter` factory (the concrete adapter
is the ONLY import site of the GPU packages; see
``tests/test_stt_boundary.py``).

Error handling (Codex MEDIUM + suggestion): a ``finally`` block calls
``adapter.unload()`` so VRAM is released even when transcribe or the write
raises. The raw ``RuntimeError`` message is printed to stderr (NOT masked
as a generic "transcription failed") so the user sees the real cause
(e.g. an int8-verification failure or a missing CUDA DLL message).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.models.backend import device_for
from app.models.diagnostics import GpuBackend, InferenceEngine
from app.models.manager import ModelManager, configure_manager, get_manager
from app.models.registry import get_category, get_spec
from app.models.stt import FasterWhisperAdapter
from app.models.stt.chunker import transcribe_file
from app.settings.service import configure, current, load_settings_from_disk
from app.storage.atomic import atomic_write_json

_log = logging.getLogger(__name__)


def _default_compute_type(device: str) -> str:
    """Return the D-04 default ``compute_type`` for ``device``.

    CUDA uses ``int8_float16`` (the load-bearing OOM defense that keeps
    large-v3 at ~2 GB on the 8 GB laptop). CPU and the ROCm->CPU fallback
    both use ``int8`` (CTranslate2 has no ROCm path per D-05).
    """
    if device == "cuda":
        return "int8_float16"
    return "int8"


def _bootstrap_settings() -> int:
    """Load + install the settings before any :func:`current` call.

    The CLI runs with NO FastAPI lifespan, so :func:`current` would raise
    ``RuntimeError("settings not configured (lifespan not installed)")``.
    This reads the bootstrap settings file via
    :func:`load_settings_from_disk` (which reads from
    :func:`app.storage.fs.bootstrap_settings_path` when ``path=None``) and
    installs the result via :func:`configure`.

    Returns 0 on success. On a missing settings file, prints a clear stderr
    message and returns 2 (the caller exits non-zero).
    """
    try:
        settings, _pending = load_settings_from_disk()
    except FileNotFoundError:
        print(
            "error: settings.json not found; run the back-end once to bootstrap it",
            file=sys.stderr,
        )
        return 2
    configure(settings)
    return 0


def _get_or_configure_manager(settings: object) -> ModelManager:
    """Return the configured :class:`ModelManager`, configuring it if needed.

    Mirrors the manager.py lines 554-567 pattern: try :func:`get_manager`;
    if it raises (the manager is not configured, as in a standalone CLI with
    no lifespan), call :func:`configure_manager` with a fresh
    :class:`ModelManager` and retry :func:`get_manager`. This guarantees
    :func:`configure_manager` runs BEFORE a successful :func:`get_manager`
    call when the manager was unconfigured (Codex HIGH).
    """
    try:
        return get_manager()
    except RuntimeError:
        configure_manager(ModelManager(settings))  # type: ignore[arg-type]
        return get_manager()


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``transcribe`` argparse parser (D-03)."""
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="Transcribe an audio/video file into a transcript JSON.",
    )
    parser.add_argument("file", metavar="<file>", help="path to the audio/video file")
    parser.add_argument(
        "--preset",
        choices=["small", "balanced", "large"],
        default="balanced",
        help="quality preset (default: balanced)",
    )
    parser.add_argument(
        "--device",
        # Codex HIGH: 'auto' is a valid choice so --device auto is accepted.
        choices=["auto", "cuda", "cpu", "rocm"],
        default="auto",
        help="device override (default: auto -- resolves from settings.backend)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="force a language code (omit to auto-detect, D-07 / INGEST-06)",
    )
    parser.add_argument(
        "--compute-type",
        choices=["int8", "int8_float16", "float16", "int8_float32"],
        default=None,
        help="compute_type override (default: int8_float16 on CUDA, int8 on CPU, D-04)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output transcript JSON path (default: <input>.transcript.json)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable INFO logging (per-chunk progress)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ``transcribe`` CLI and return an exit code.

    :param argv: optional argv list (defaults to ``sys.argv[1:]``). Tests
        pass an explicit list so they do not depend on the process argv.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    # 1. V5 path validation (T-03-02).
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(f"error: input file not found: {file_path}", file=sys.stderr)
        return 2

    # Compute the output path. with_suffix replaces .wav -> .transcript.json
    # (the accepted interpretation of SC-1 per Codex MEDIUM: the filename is
    # <stem>.transcript.json, not a literal "transcript.json").
    out_path = (
        Path(args.out).resolve() if args.out else file_path.with_suffix(".transcript.json")
    )
    # Check the parent EXISTS (writability is cross-platform-unreliable --
    # Codex MEDIUM: let atomic_write_json report write failures clearly).
    if not out_path.parent.exists():
        print(
            f"error: output directory does not exist: {out_path.parent}",
            file=sys.stderr,
        )
        return 2

    # 2. Bootstrap settings BEFORE any current() call (PATTERNS gap fix, W2).
    rc = _bootstrap_settings()
    if rc != 0:
        return rc

    # 3. Resolve device + compute_type.
    settings = current()
    device = (
        args.device
        if args.device != "auto"
        else str(device_for(settings.backend, InferenceEngine.FASTER_WHISPER))
    )
    compute_type = args.compute_type or _default_compute_type(device)

    # 4. Resolve the model spec + category, get the manager, download the model.
    spec = get_spec(f"{args.preset}.stt")
    category = get_category(f"{args.preset}.stt")
    manager = _get_or_configure_manager(settings)
    model_path = asyncio.run(manager.ensure_downloaded(spec, category))

    # 5. Build + load the adapter (D-08 int8 verification runs here -- fail loud
    # on a silent float16 fallback).
    adapter: FasterWhisperAdapter | None = None
    try:
        adapter = FasterWhisperAdapter(
            model_path=str(model_path),
            device=device,
            compute_type=compute_type,
        )
        adapter.load()

        # 6. Transcribe + write atomically (Phase 1 D-04 atomic writes).
        # job_id is the filename stem (the CLI does NOT create a data/jobs/<id>/
        # dir per D-03 -- it is a logical label).
        transcript = transcribe_file(
            adapter, str(file_path), language=args.language, job_id=file_path.stem
        )
        asyncio.run(atomic_write_json(out_path, transcript.model_dump()))

        # D-03 one-line stdout summary.
        print(
            f"language={transcript.language} segments={len(transcript.segments)} -> {out_path}"
        )
        return 0
    except RuntimeError as exc:
        # Codex MEDIUM: preserve the RAW exception message (do NOT mask an
        # int8-verification or CUDA-DLL error as a generic failure).
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        # Codex suggestion: VRAM cleanup on error -- unload runs even when
        # transcribe_file or atomic_write_json raised. Guard against a failed
        # adapter build so we do not double-raise.
        if adapter is not None:
            adapter.unload()


__all__ = ["main"]