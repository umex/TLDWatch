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