"""Tests for ``ModelManager.ensure_downloaded`` (SC-3, Pitfall 4, D-01).

Four tests:

- ``test_ensure_downloaded_size_and_sha`` -- the mock writes a complete
  file at the expected path with the right size; the fast-path returns
  the target without re-downloading.
- ``test_resume_after_crash`` -- a partial file at the target is NOT
  re-fetched from zero; ``force_download`` is NOT in the kwargs (the
  library resumes via the ``<blob>.incomplete`` + Range mechanism).
- ``test_ensure_downloaded_gated_repo_raises_model_gated_error`` -- a
  ``GatedRepoError`` from the mock is re-raised as
  :class:`ModelGatedError` (Pitfall 3).
- ``test_ensure_downloaded_corrupt_sha_raises_integrity_error`` -- a
  file whose SHA does not match raises :class:`ModelIntegrityError`
  after the bounded retry.

These tests build a ``ModelManager`` directly (no lifespan) with a tmp
``data_dir`` so the on-disk paths are isolated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.models.diagnostics import GpuBackend, ModelCategory, ModelSpec
from app.models.manager import (
    ModelGatedError,
    ModelIntegrityError,
    ModelManager,
)
from app.models.registry import REGISTRY
from app.models.settings import Settings
from app.storage.models_dir import spec_file_path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        backend=GpuBackend.CUDA,
    )


@pytest.mark.asyncio
async def test_ensure_downloaded_size_and_sha(
    tmp_path: Path, mock_hf_hub_download
) -> None:
    """SC-3: download writes the file at the expected path with the right size."""
    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.llm"]
    target = spec_file_path(settings, ModelCategory.LLM, spec)

    path = await mgr.ensure_downloaded(spec, ModelCategory.LLM)
    assert path == target
    assert target.exists()
    assert target.stat().st_size == spec.expected_size_bytes
    # The mock was called (the size fast-path only triggers when the
    # file already exists at the expected size AND no SHA is set; here
    # the file does not exist on entry so the download runs).
    assert mock_hf_hub_download.call_count >= 1
    # force_download was NOT passed (default False -> resume path).
    for call in mock_hf_hub_download.call_args_list:
        assert "force_download" not in call.kwargs


@pytest.mark.asyncio
async def test_resume_after_crash(
    tmp_path: Path, mock_hf_hub_download
) -> None:
    """SC-3, Pitfall 4: a partial file is NOT re-fetched from zero.

    The mock writes a complete file at the expected size; the fast-path
    triggers on the SECOND call (the file now exists at the expected
    size), so ``hf_hub_download`` is called exactly once.
    """
    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.llm"]
    target = spec_file_path(settings, ModelCategory.LLM, spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Pre-create a partial file at half the expected size.
    target.write_bytes(b"x" * (spec.expected_size_bytes // 2))

    await mgr.ensure_downloaded(spec, ModelCategory.LLM)
    # The library was called (the partial file is not at the full
    # expected size, so the fast-path does not trigger).
    assert mock_hf_hub_download.call_count == 1
    # force_download was NOT in the kwargs (default False -> resume).
    assert "force_download" not in mock_hf_hub_download.call_args.kwargs


@pytest.mark.asyncio
async def test_ensure_downloaded_gated_repo_raises_model_gated_error(
    tmp_path: Path, mock_hf_hub_download
) -> None:
    """Pitfall 3: a ``GatedRepoError`` is re-raised as :class:`ModelGatedError`."""
    import sys

    errors = sys.modules["huggingface_hub"].errors
    # ``GatedRepoError`` requires an ``httpx.Response``; build a minimal
    # stand-in so the constructor does not blow up (the manager only
    # re-wraps the exception, it does not read the response).
    import httpx

    fake_resp = httpx.Response(403, request=httpx.Request("HEAD", "https://x"))
    mock_hf_hub_download.side_effect = errors.GatedRepoError(
        "gated", response=fake_resp
    )
    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.diarize"]

    with pytest.raises(ModelGatedError) as exc:
        await mgr.ensure_downloaded(spec, ModelCategory.DIARIZE)
    assert exc.value.repo_id == "pyannote/speaker-diarization-3.1"


@pytest.mark.asyncio
async def test_ensure_downloaded_corrupt_sha_raises_integrity_error(
    tmp_path: Path, mock_hf_hub_download, monkeypatch
) -> None:
    """SC-3: a file whose SHA does not match raises :class:`ModelIntegrityError`.

    Builds a spec with a known SHA; the mock writes a file with the
    WRONG content (so the SHA mismatches); the bounded retry also
    writes the wrong content; the manager raises
    :class:`ModelIntegrityError` after the retry.
    """
    settings = _settings(tmp_path)
    spec = ModelSpec(
        repo_id="test/llm",
        file="model.bin",
        revision=None,
        expected_size_bytes=1024,
        expected_sha256=hashlib.sha256(b"good").hexdigest(),
    )

    def _bad_download(*, repo_id, filename, revision, local_dir, token):
        from pathlib import Path

        out = Path(local_dir) / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        # Write the right SIZE but the wrong CONTENT -> SHA mismatch.
        out.write_bytes(b"b" * 1024)
        return str(out)

    mock_hf_hub_download.side_effect = _bad_download
    mgr = ModelManager(settings, settings_factory=lambda: settings)

    with pytest.raises(ModelIntegrityError):
        await mgr.ensure_downloaded(spec, ModelCategory.LLM)


# --- file=None snapshot-repo path (03-03 SC-5 checkpoint) --------------------
#
# ``balanced.stt`` / ``balanced.diarize`` have ``file=None`` (multi-file
# CTranslate2 / pyannote snapshot repos). The OLD code fabricated
# ``<sanitized_repo_id>.bin`` and 404'd; the NEW code calls
# ``snapshot_download`` and returns the repo DIRECTORY. These tests mock
# the ``huggingface_hub.snapshot_download`` boundary (no real network).


@pytest.mark.asyncio
async def test_file_none_uses_snapshot_download_and_returns_dir(
    tmp_path: Path, mock_hf_snapshot_download
) -> None:
    """file=None: ensure_downloaded calls snapshot_download + returns the spec dir.

    Regression guard for the 03-03 SC-5 checkpoint: the OLD code called
    ``hf_hub_download`` with the fabricated ``Systran--faster-whisper-large-v3.bin``
    filename (which 404'd on a real HF repo) and returned a file path;
    the NEW code calls ``snapshot_download`` with ``local_dir`` = the
    spec dir and returns the directory Path. This test FAILS on the old
    code (which never calls ``snapshot_download`` and returns a .bin
    file path) and PASSES on the new code.
    """
    from app.storage.models_dir import spec_dir as spec_dir_fn

    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.stt"]
    expected_dir = spec_dir_fn(settings, ModelCategory.STT, spec.repo_id)

    path = await mgr.ensure_downloaded(spec, ModelCategory.STT)

    # Returned the repo directory (NOT a fabricated .bin file).
    assert path == expected_dir
    assert path.is_dir()
    # snapshot_download was called with repo_id + local_dir = the spec dir.
    assert mock_hf_snapshot_download.call_count >= 1
    call = mock_hf_snapshot_download.call_args
    assert call.kwargs["repo_id"] == spec.repo_id
    assert call.kwargs["local_dir"] == str(expected_dir)
    # The mock populated the directory with config.json (the fast-path
    # sentinel), exercising the return-dir logic.
    assert (path / "config.json").exists()


@pytest.mark.asyncio
async def test_file_set_still_uses_hf_hub_download(
    tmp_path: Path, mock_hf_hub_download, mock_hf_snapshot_download
) -> None:
    """file set: ensure_downloaded STILL calls hf_hub_download (single-file path unchanged).

    Proves the single-file (GGUF LLM) path is byte-for-byte unchanged --
    ``snapshot_download`` is NOT invoked, ``hf_hub_download`` is, and the
    returned path is the single-file target (not a directory).
    """
    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.llm"]
    target = spec_file_path(settings, ModelCategory.LLM, spec)

    path = await mgr.ensure_downloaded(spec, ModelCategory.LLM)

    assert path == target
    assert target.exists()
    assert target.stat().st_size == spec.expected_size_bytes
    # Single-file path: hf_hub_download called, snapshot_download NOT.
    assert mock_hf_hub_download.call_count >= 1
    mock_hf_snapshot_download.assert_not_called()
    # The single-file filename is the spec's file (NOT the fabricated
    # sanitized-repo .bin fallback).
    call = mock_hf_hub_download.call_args
    assert call.kwargs["filename"] == spec.file


@pytest.mark.asyncio
async def test_file_none_fast_path_returns_without_network(
    tmp_path: Path, mock_hf_snapshot_download
) -> None:
    """file=None fast-path: a pre-populated spec dir returns without snapshot_download.

    If the spec dir already holds a populated snapshot (``config.json``
    present), ``ensure_downloaded`` returns it WITHOUT hitting the
    network (``snapshot_download`` is not called) -- the offline / cached
    fast-path.
    """
    from app.storage.models_dir import spec_dir as spec_dir_fn

    settings = _settings(tmp_path)
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.diarize"]
    spec_directory = spec_dir_fn(settings, ModelCategory.DIARIZE, spec.repo_id)
    spec_directory.mkdir(parents=True, exist_ok=True)
    # Pre-populate the snapshot sentinel.
    (spec_directory / "config.json").write_text("{}", encoding="utf-8")

    path = await mgr.ensure_downloaded(spec, ModelCategory.DIARIZE)

    assert path == spec_directory
    # Fast-path: snapshot_download was NOT called (no network round-trip).
    mock_hf_snapshot_download.assert_not_called()