"""Tests for :mod:`app.jobs.resume` — the file-as-truth resume rule (D-12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jobs.manifest import empty_manifest, write_manifest
from app.jobs.resume import (
    STAGE_ORDER,
    infer_resume_point,
    is_stage_complete,
)
from app.models.diagnostics import GpuBackend
from app.models.manifest import JobManifest
from app.models.settings import Settings
from app.models.summary import SummaryKind
from app.storage.fs import (
    ensure_job_dir,
    source_path,
    summary_path,
    transcript_path,
)


def _settings(tmp_data_dir: Path) -> Settings:
    return Settings(data_dir=str(tmp_data_dir / "data"), backend=GpuBackend.CPU)


@pytest.mark.asyncio
async def test_stage_order_constant() -> None:
    """STAGE_ORDER is the canonical walk order from D-12."""
    assert STAGE_ORDER == ("ingested", "transcribed", "diarized", "summarized", "done")


@pytest.mark.asyncio
async def test_no_files_returns_ingested(tmp_data_dir: Path) -> None:
    """No files at all -> resume at 'ingested'."""
    import asyncio

    s = _settings(tmp_data_dir)
    j = "11111111-1111-1111-1111-111111111111"
    await ensure_job_dir(s, j)
    m = await write_manifest(s, empty_manifest(j))
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) == "ingested"


@pytest.mark.asyncio
async def test_source_only_returns_transcribed(tmp_data_dir: Path) -> None:
    """source.mp4 exists but no transcript -> resume at 'transcribed'."""
    s = _settings(tmp_data_dir)
    j = "22222222-2222-2222-2222-222222222222"
    await ensure_job_dir(s, j)
    await write_manifest(s, empty_manifest(j))
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) == "transcribed"


@pytest.mark.asyncio
async def test_source_and_transcript_returns_diarized(tmp_data_dir: Path) -> None:
    """With source + transcript and diarization_enabled=True and
    summary_kinds=['meeting'] but no summary file written yet, the
    resume rule walks to 'diarized' (the first applicable incomplete
    stage)."""
    s = _settings(tmp_data_dir)
    j = "33333333-3333-3333-3333-333333333333"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(
        update={"diarization_enabled": True, "summary_kinds": ["meeting"]}
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    manifest = await _read_or_dump(s, j)
    assert manifest.diarization_enabled is True
    # ingested: complete (source exists)
    # transcribed: complete (transcript exists)
    # diarized: applicable but no diarization file -> first incomplete
    assert infer_resume_point(s, j, manifest) == "diarized"


@pytest.mark.asyncio
async def test_source_and_transcript_diarization_enabled_returns_diarized(
    tmp_data_dir: Path,
) -> None:
    """If diarization_enabled=True and no diarization file -> 'diarized'."""
    s = _settings(tmp_data_dir)
    j = "44444444-4444-4444-4444-444444444444"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(update={"diarization_enabled": True, "summary_kinds": []})
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) == "diarized"


@pytest.mark.asyncio
async def test_all_stages_returns_none(tmp_data_dir: Path) -> None:
    """All applicable stages complete + current_stage='done' -> None.

    The 'done' state is DERIVED; we do NOT write a done.json file.
    The manifest's current_stage is set to 'done' as the terminal
    marker, and the resume rule returns None when every prior
    stage is complete.
    """
    from app.util.time import utcnow_iso
    from app.models.common import StageTimestamps

    s = _settings(tmp_data_dir)
    j = "55555555-5555-5555-5555-555555555555"
    await ensure_job_dir(s, j)
    m = JobManifest(
        schema_version=1,
        job_id=j,
        diarization_enabled=False,
        summary_kinds=[],
        status="done",
        current_stage="done",
        stage_timestamps=StageTimestamps(
            queued=utcnow_iso(),
            ingested=utcnow_iso(),
            transcribed=utcnow_iso(),
            done=utcnow_iso(),
        ),
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) is None


@pytest.mark.asyncio
async def test_one_summary_missing_returns_summarized(tmp_data_dir: Path) -> None:
    """Two summary kinds requested, only one summary file present -> 'summarized'."""
    s = _settings(tmp_data_dir)
    j = "66666666-6666-6666-6666-666666666666"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(
        update={"diarization_enabled": False, "summary_kinds": ["meeting", "investment"]}
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    summary_path(s, j, "meeting").write_text(
        json.dumps(
            {
                "job_id": j,
                "kind": "meeting",
                "created_at": "2026-06-15T00:00:00+00:00",
                "sections": {},
            }
        ),
        encoding="utf-8",
    )
    # investment summary is missing
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) == "summarized"


@pytest.mark.asyncio
async def test_diarization_disabled_skips_diarized(tmp_data_dir: Path) -> None:
    """diarization_enabled=False: the resume walk skips 'diarized' entirely."""
    s = _settings(tmp_data_dir)
    j = "77777777-7777-7777-7777-777777777777"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(update={"diarization_enabled": False, "summary_kinds": ["meeting"]})
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    summary_path(s, j, "meeting").write_text(
        json.dumps(
            {
                "job_id": j,
                "kind": "meeting",
                "created_at": "2026-06-15T00:00:00+00:00",
                "sections": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = await _read_or_dump(s, j)
    # 'diarized' is skipped (not applicable); 'summarized' is complete
    # (meeting file exists); 'done' derives True (manifest says done + all
    # prior applicable stages complete). Without current_stage='done' on
    # the manifest, 'done' is NOT complete, so the resume point is 'done'.
    assert infer_resume_point(s, j, manifest) == "done"


@pytest.mark.asyncio
async def test_summary_kinds_empty_skips_summarized(tmp_data_dir: Path) -> None:
    """summary_kinds=[]: the walk skips 'summarized' and lands at 'done'."""
    s = _settings(tmp_data_dir)
    j = "88888888-8888-8888-8888-888888888888"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(update={"diarization_enabled": False, "summary_kinds": []})
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    manifest = await _read_or_dump(s, j)
    # 'summarized' is NOT applicable; 'done' is not complete (manifest
    # does not say current_stage='done'); so the resume point is 'done'.
    assert infer_resume_point(s, j, manifest) == "done"


@pytest.mark.asyncio
async def test_done_is_derived(tmp_data_dir: Path) -> None:
    """is_stage_complete('done', ...) returns False when prior stages incomplete,
    even if manifest.current_stage=='done'."""
    s = _settings(tmp_data_dir)
    j = "99999999-9999-9999-9999-999999999999"
    await ensure_job_dir(s, j)
    from app.util.time import utcnow_iso
    from app.models.common import StageTimestamps

    m = JobManifest(
        schema_version=1,
        job_id=j,
        diarization_enabled=False,
        summary_kinds=[],
        status="done",
        current_stage="done",
        stage_timestamps=StageTimestamps(
            queued=utcnow_iso(),
            done=utcnow_iso(),
        ),
    )
    await write_manifest(s, m)
    # No source file -> 'ingested' is not complete. The manifest says
    # current_stage='done' but the file truth says otherwise.
    manifest = await _read_or_dump(s, j)
    assert is_stage_complete("done", s, j, manifest) is False


async def _read_or_dump(s: Settings, j: str) -> JobManifest:
    """Read the manifest that was just written (helper for inline reuse)."""
    from app.jobs.manifest import read_manifest

    return await read_manifest(s, j)


# --- Plan 01-04 T6+M2: invalid / zero-byte stage file rejection -----------


@pytest.mark.asyncio
async def test_transcript_file_missing_required_fields(tmp_data_dir: Path) -> None:
    """M1: transcript.json with ``{}`` (missing required ``job_id``) is
    rejected by ``parse_stage_file`` (Transcript.model_validate_json
    raises). The resume rule treats the stage as incomplete and
    walks back to 'transcribed'."""
    s = _settings(tmp_data_dir)
    j = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    await ensure_job_dir(s, j)
    from app.jobs.manifest import empty_manifest, write_manifest

    m = empty_manifest(j)
    m = m.model_copy(update={"diarization_enabled": False, "summary_kinds": []})
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(json.dumps({}), encoding="utf-8")
    manifest = await _read_or_dump(s, j)
    # ingested complete; transcribed fails (empty dict fails Transcript validation)
    assert infer_resume_point(s, j, manifest) == "transcribed"


@pytest.mark.asyncio
async def test_transcript_file_invalid_json(tmp_data_dir: Path) -> None:
    """Corrupt JSON in transcript.json -> transcribed not complete."""
    s = _settings(tmp_data_dir)
    j = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    await ensure_job_dir(s, j)
    from app.jobs.manifest import empty_manifest, write_manifest

    m = empty_manifest(j)
    m = m.model_copy(update={"diarization_enabled": False, "summary_kinds": []})
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text("not json at all", encoding="utf-8")
    manifest = await _read_or_dump(s, j)
    assert infer_resume_point(s, j, manifest) == "transcribed"


@pytest.mark.asyncio
async def test_diarization_file_invalid_json(tmp_data_dir: Path) -> None:
    """Corrupt JSON in diarization.json -> diarized not complete."""
    from app.jobs.manifest import empty_manifest, write_manifest
    from app.storage.fs import diarization_path

    s = _settings(tmp_data_dir)
    j = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(
        update={"diarization_enabled": True, "summary_kinds": []}
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    diarization_path(s, j).write_text("not json at all", encoding="utf-8")
    manifest = await _read_or_dump(s, j)
    # ingested + transcribed complete; diarized fails on parse -> resume at 'diarized'
    assert infer_resume_point(s, j, manifest) == "diarized"


@pytest.mark.asyncio
async def test_summary_file_invalid_json(tmp_data_dir: Path) -> None:
    """Corrupt JSON in summary-<kind>.json -> summarized not complete."""
    from app.jobs.manifest import empty_manifest, write_manifest

    s = _settings(tmp_data_dir)
    j = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(
        update={"diarization_enabled": False, "summary_kinds": ["meeting"]}
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"\x00" * 16)
    transcript_path(s, j).write_text(
        json.dumps({"job_id": j, "segments": []}), encoding="utf-8"
    )
    summary_path(s, j, "meeting").write_text("not json at all", encoding="utf-8")
    manifest = await _read_or_dump(s, j)
    # ingested + transcribed complete; summarized fails on parse -> resume at 'summarized'
    assert infer_resume_point(s, j, manifest) == "summarized"


@pytest.mark.asyncio
async def test_source_file_zero_bytes_rejected(tmp_data_dir: Path) -> None:
    """M2: zero-byte source.* is rejected; the resume rule walks back to 'ingested'."""
    from app.jobs.manifest import empty_manifest, write_manifest

    s = _settings(tmp_data_dir)
    j = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    await ensure_job_dir(s, j)
    m = empty_manifest(j)
    m = m.model_copy(
        update={"diarization_enabled": False, "summary_kinds": []}
    )
    await write_manifest(s, m)
    source_path(s, j, "mp4").write_bytes(b"")
    manifest = await _read_or_dump(s, j)
    # ingested fails (zero-byte source) -> resume at 'ingested'
    assert infer_resume_point(s, j, manifest) == "ingested"
