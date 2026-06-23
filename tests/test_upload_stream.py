"""Streaming upload endpoint tests -- plan 05-01 Task 2 (INGEST-01).

Integration tests for ``POST /jobs/upload`` (D-11, SC-1, Pitfall 1/2/3):

- ``test_upload_stream_writes_source_atomically``: a small upload lands
  ``source.<ext>`` in the job dir atomically and the job ends up
  ``status='queued'`` (enqueue flipped the pre-queued ``'uploading'`` row).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_upload_stream_writes_source_atomically(
    client: httpx.AsyncClient,
) -> None:
    """POST /jobs/upload streams the raw body to ``source.<ext>`` atomically.

    After the request completes the job dir contains ``source.<ext>`` and
    the job is ``status='queued'`` (enqueue flipped it). The worker is off
    (``run_worker=False``) so the job is not picked up.
    """
    headers = {
        "Idempotency-Key": "stream-upload-1",
        "X-Filename": "video.mp4",
        "Content-Type": "application/octet-stream",
    }
    resp = await client.post("/jobs/upload", content=b"\x00" * 1024, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "id" in body
    job_id = body["id"]
    # enqueue flipped the pre-queued 'uploading' row to 'queued'.
    assert body["status"] == "queued", body

    # The source file landed atomically in the job dir.
    from app.main import app

    job_dir = Path(app.state.settings.data_dir) / "jobs" / job_id
    assert (job_dir / "source.mp4").exists(), list(job_dir.iterdir())

    # No .tmp_* scratch files left behind.
    tmp_leftovers = list(job_dir.glob(".tmp_*"))
    assert tmp_leftovers == [], tmp_leftovers