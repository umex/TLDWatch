"""Tests for the per-stage file path helpers and the extension validators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.models.summary import validate_summary_kind
from app.storage.fs import (
    ALLOWED_SOURCE_EXTS,
    diarization_path,
    edits_path,
    last_stage_mtime,
    list_stage_files,
    source_path,
    summary_path,
    transcript_path,
    validate_source_ext,
)


def test_path_helpers(tmp_data_dir: Path) -> None:
    """Every path helper returns a path inside the per-job folder."""
    s = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    j = "00000000-0000-0000-0000-000000000001"
    expected_root = tmp_data_dir / "data" / "jobs" / j

    assert transcript_path(s, j) == expected_root / "transcript.json"
    assert diarization_path(s, j) == expected_root / "diarization.json"
    assert summary_path(s, j, "meeting") == expected_root / "summary-meeting.json"
    assert edits_path(s, j) == expected_root / "edits.json"
    assert source_path(s, j, "mp4") == expected_root / "source.mp4"


def test_validate_source_ext_rejects_path_traversal() -> None:
    """Path-traversal-looking extensions are rejected with ValueError."""
    # Good: lowercase, no leading dot, in allowlist
    assert validate_source_ext("mp4") == "mp4"
    # Good: uppercase is normalised
    assert validate_source_ext(".MP4") == "mp4"
    assert validate_source_ext("WAV") == "wav"
    # Bad: path traversal
    with pytest.raises(ValueError):
        validate_source_ext("../../etc/passwd")
    # Bad: contains ..
    with pytest.raises(ValueError):
        validate_source_ext("..")
    # Bad: contains /
    with pytest.raises(ValueError):
        validate_source_ext("a/b")
    # Bad: contains backslash
    with pytest.raises(ValueError):
        validate_source_ext("a\\b")
    # Bad: contains colon (Windows drive letter)
    with pytest.raises(ValueError):
        validate_source_ext("c:mp4")
    # Bad: not in allowlist
    with pytest.raises(ValueError):
        validate_source_ext("exe")
    # Bad: empty
    with pytest.raises(ValueError):
        validate_source_ext("")
    # Bad: just a dot
    with pytest.raises(ValueError):
        validate_source_ext(".")


def test_validate_summary_kind_rejects_path_traversal() -> None:
    """Path-traversal-looking kinds are rejected by the summary validator."""
    assert validate_summary_kind("meeting") == "meeting"
    with pytest.raises(ValueError):
        validate_summary_kind("../../etc/passwd")
    with pytest.raises(ValueError):
        validate_summary_kind("not-a-kind")


def test_source_path_validates_ext(tmp_data_dir: Path) -> None:
    """source_path raises ValueError on bad extensions (no path is built)."""
    s = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    j = "00000000-0000-0000-0000-000000000002"
    with pytest.raises(ValueError):
        source_path(s, j, "../../etc/passwd")
    # OK path returns the expected Path
    assert source_path(s, j, "mp3") == (
        tmp_data_dir / "data" / "jobs" / j / "source.mp3"
    )


def test_summary_path_validates_kind(tmp_data_dir: Path) -> None:
    """summary_path raises ValueError on bad kinds (no path is built)."""
    s = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    j = "00000000-0000-0000-0000-0000-000000000003"
    with pytest.raises(ValueError):
        summary_path(s, j, "../../etc/passwd")


def test_list_stage_files_and_last_mtime(tmp_data_dir: Path) -> None:
    """list_stage_files returns the actual files; last_stage_mtime is the max."""
    import asyncio

    from app.storage.fs import ensure_job_dir

    s = Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)
    j = "00000000-0000-0000-0000-000000000004"
    asyncio.run(ensure_job_dir(s, j))

    # Empty job -> empty list, None mtime
    assert list_stage_files(s, j) == []
    assert last_stage_mtime(s, j) is None

    # Write a stage file -> it's listed and contributes to the mtime
    transcript_path(s, j).write_text(json.dumps({}), encoding="utf-8")
    files = list_stage_files(s, j)
    assert any(f.name == "transcript.json" for f in files)
    assert last_stage_mtime(s, j) is not None


def test_allowed_source_exts_is_frozenset() -> None:
    """The allowlist is a frozenset (immutable; safe to import anywhere)."""
    assert isinstance(ALLOWED_SOURCE_EXTS, frozenset)
    assert "mp4" in ALLOWED_SOURCE_EXTS
    assert "wav" in ALLOWED_SOURCE_EXTS
