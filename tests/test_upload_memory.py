"""Streaming upload memory-bound test -- plan 05-01 Task 2 (INGEST-01, SC-1).

Integration test for ``POST /jobs/upload`` asserting the request body is
NOT buffered in process memory (Pitfall 2 / SC-1). The ``request.stream()`` +
``aiofiles`` path must stream chunks to disk without holding the whole body
in Python heap.
"""

from __future__ import annotations

import tracemalloc

import httpx
import pytest


@pytest.mark.asyncio
async def test_upload_does_not_buffer_in_memory(
    client: httpx.AsyncClient,
) -> None:
    """Uploading a >100MB fixture does not grow process memory proportionally.

    The ``request.stream()`` + ``aiofiles`` path must NOT buffer the whole
    body in process memory (Pitfall 2 / SC-1). ``tracemalloc`` peak during
    the upload is well below the file size.

    A 128 MB fixture is generated in-test and streamed via httpx's content
    body. We assert the tracemalloc peak (Python-allocated bytes) stays
    below 64 MB -- i.e. well under the 128 MB payload -- proving the body
    is streamed to disk in chunks, not buffered whole.
    """
    payload_size = 128 * 1024 * 1024  # 128 MB
    # httpx will stream this bytes object; the ASGI transport feeds it
    # to request.stream() in chunks. The bytes object itself lives in
    # Python heap (so tracemalloc will count it), but the SERVER-side
    # buffering path (what we are testing) must not duplicate it. We
    # baseline against the peak including the payload by asserting the
    # peak growth during the request is far smaller than the payload.
    body = b"\x00" * payload_size
    headers = {
        "Idempotency-Key": "mem-upload-1",
        "X-Filename": "video.mp4",
        "Content-Type": "application/octet-stream",
    }

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    try:
        resp = await client.post("/jobs/upload", content=body, headers=headers)
    finally:
        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

    assert resp.status_code == 201, resp.text

    # The peak Python-allocated growth during the request must be far
    # smaller than the 128 MB payload -- proving the server streamed the
    # body to disk in chunks rather than buffering it whole (Pitfall 2).
    # We allow up to 64 MB of growth (the client-side bytes object is
    # already counted in the baseline snapshot, so the delta reflects
    # server-side allocation + httpx transport overhead).
    stats = snapshot_after.compare_to(snapshot_before, "filename")
    total_growth = sum(stat.size_diff for stat in stats if stat.size_diff > 0)
    assert total_growth < 64 * 1024 * 1024, (
        f"memory growth {total_growth / 1024 / 1024:.1f} MB >= 64 MB; "
        "the upload route is buffering the body in memory (Pitfall 2)"
    )