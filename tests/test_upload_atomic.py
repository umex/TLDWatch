"""Streaming upload atomic-cleanup test -- plan 05-01 Task 2 (INGEST-01, T-05-02).

Integration test for ``POST /jobs/upload`` asserting a mid-stream abort
leaves no partial ``source.<ext>`` on disk (T-05-02). The route's
``except BaseException: os.unlink(tmp)`` branch cleans the ``.tmp_*``
scratch file so a crashed upload cannot leave a partial file the
orchestrator would pick up.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


async def _aborting_body() -> "object":
    """Yield a few chunks then raise to simulate a client mid-stream disconnect."""
    yield b"\x00" * (1024 * 64)
    yield b"\x00" * (1024 * 64)
    raise RuntimeError("simulated client disconnect mid-upload")


@pytest.mark.asyncio
async def test_aborted_upload_leaves_no_source(
    client: httpx.AsyncClient,
) -> None:
    """Aborting the request mid-stream leaves no ``source.<ext>`` in the job dir.

    Only the ``.tmp_*`` scratch file may be created, and the route's
    ``except BaseException: os.unlink(tmp)`` cleans it up (T-05-02).
    """
    headers = {
        "Idempotency-Key": "atomic-upload-1",
        "X-Filename": "video.mp4",
        "Content-Type": "application/octet-stream",
    }

    # The async generator raises mid-stream; httpx surfaces the failure
    # (the exact exception type depends on transport). We only care that
    # the request did NOT succeed and the route's cleanup ran.
    with pytest.raises(Exception):
        await client.post(
            "/jobs/upload", content=_aborting_body(), headers=headers
        )

    from app.main import app

    jobs_root = Path(app.state.settings.data_dir) / "jobs"
    # No source.<ext> file landed anywhere (the atomic rename never ran).
    assert list(jobs_root.glob("*/source.*")) == [], (
        "source.<ext> must NOT exist after a mid-stream abort"
    )
    # No .tmp_* scratch files left behind (the except branch unlinked them).
    assert list(jobs_root.glob("*/.tmp_*")) == [], (
        ".tmp_* scratch files must be cleaned up after a mid-stream abort"
    )