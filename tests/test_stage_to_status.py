"""Tests for :func:`app.jobs.manifest.stage_to_status` (Plan 01-04 H3).

The :func:`stage_to_status` helper is the single source of truth for
the stage-to-status mapping. This test enumerates every row of the
mapping table in the plan, and asserts end-to-end that
``update_stage`` projects the correct ``status`` to the DB.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.api import dependencies as deps_module
from app.jobs.manifest import stage_to_status
from app.models.common import StageTimestamps
from app.models.manifest import JobManifest
from app.util.time import utcnow_iso


def _session_factory():
    sf = deps_module.session_factory
    assert sf is not None
    return sf


def _fresh_manifest(diarization_enabled: bool = False, summary_kinds=None) -> JobManifest:
    return JobManifest(
        schema_version=1,
        job_id="00000000-0000-0000-0000-000000000000",
        diarization_enabled=diarization_enabled,
        summary_kinds=summary_kinds or [],
        stage_timestamps=StageTimestamps(queued=utcnow_iso()),
    )


def test_stage_to_status_table() -> None:
    """Enumerate the mapping table from the plan."""
    # (stage, diarization_enabled, summary_kinds) -> expected status
    cases = [
        (None, False, [], "queued"),
        ("ingested", False, [], "ingesting"),
        ("ingested", True, [], "ingesting"),
        ("transcribed", False, [], "transcribing"),
        ("transcribed", True, ["meeting"], "transcribing"),
        ("diarized", True, [], "diarizing"),
        ("diarized", True, ["meeting"], "diarizing"),
        ("summarized", False, ["meeting"], "summarizing"),
        ("summarized", True, ["meeting", "investment"], "summarizing"),
        ("done", False, [], "done"),
        ("done", True, ["meeting"], "done"),
        # Defensive fallbacks
        ("diarized", False, [], "transcribing"),
        ("summarized", False, [], "transcribing"),
        # Unknown stage -> queued
        ("unknown", False, [], "queued"),
    ]
    for stage, diar, kinds, expected in cases:
        m = _fresh_manifest(diarization_enabled=diar, summary_kinds=kinds)
        got = stage_to_status(stage, m)
        assert got == expected, (stage, diar, kinds, got, expected)


@pytest.mark.asyncio
async def test_update_stage_projects_status_to_db(
    client: httpx.AsyncClient,
) -> None:
    """End-to-end: POST /jobs/{id}/stage projects the right status to the DB."""
    resp = await client.post("/jobs", json={})
    assert resp.status_code == 201
    job_id = resp.json()["id"]
    sf = _session_factory()

    async with sf() as session:
        row = (
            await session.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
        ).scalar()
    assert row == "queued"

    # ingested -> "ingesting"
    resp = await client.post(f"/jobs/{job_id}/stage", json={"stage": "ingested"})
    assert resp.status_code == 200, resp.text
    async with sf() as session:
        row = (
            await session.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
        ).scalar()
    assert row == "ingesting", row

    # transcribed -> "transcribing"
    resp = await client.post(f"/jobs/{job_id}/stage", json={"stage": "transcribed"})
    assert resp.status_code == 200, resp.text
    async with sf() as session:
        row = (
            await session.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
        ).scalar()
    assert row == "transcribing", row

    # done -> "done"
    resp = await client.post(f"/jobs/{job_id}/stage", json={"stage": "done"})
    assert resp.status_code == 200, resp.text
    async with sf() as session:
        row = (
            await session.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
        ).scalar()
    assert row == "done", row
