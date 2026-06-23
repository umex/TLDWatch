"""Transcript read endpoint tests -- plan 05-01 Task 2 (D-14).

Integration tests for ``GET /jobs/{id}/transcript``:

- 200 + the parsed :class:`Transcript` JSON when ``transcript.json`` exists.
- 404 ``{"detail": "transcript not found"}`` when the job has no transcript yet.
- 400 ``{"detail": "invalid job id"}`` for a malformed id.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.main import app
from app.models.transcript import Transcript, TranscriptSegment
from app.storage.fs import transcript_path


@pytest.mark.asyncio
async def test_get_transcript_returns_200_when_present(
    client: httpx.AsyncClient,
) -> None:
    """GET /jobs/{id}/transcript returns 200 + the Transcript JSON when present."""
    # Create a job (POST /jobs) and write a real transcript.json.
    created = await client.post("/jobs", json={})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    settings = app.state.settings
    tpath = transcript_path(settings, job_id)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text(
        Transcript(
            job_id=job_id,
            segments=[TranscriptSegment(start_s=0.0, end_s=1.0, text="hello")],
        ).model_dump_json(),
        encoding="utf-8",
    )

    resp = await client.get(f"/jobs/{job_id}/transcript")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["segments"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_get_transcript_returns_404_when_missing(
    client: httpx.AsyncClient,
) -> None:
    """GET /jobs/{id}/transcript returns 404 when no transcript.json exists yet."""
    created = await client.post("/jobs", json={})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    resp = await client.get(f"/jobs/{job_id}/transcript")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "transcript not found"


@pytest.mark.asyncio
async def test_get_transcript_returns_400_for_invalid_id(
    client: httpx.AsyncClient,
) -> None:
    """GET /jobs/{bad-id}/transcript returns 400 for an invalid job id."""
    resp = await client.get("/jobs/not-a-uuid/transcript")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "invalid job id"