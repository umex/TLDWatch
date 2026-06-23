"""Streaming upload endpoint tests -- plan 05-01 Task 2 (INGEST-01).

Wave 0 stub: each test is skipped until Task 2 implements the streaming
upload route (``POST /jobs/upload``) and fills these in. The full back-end
suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upload_stream_writes_source_atomically(client: "object") -> None:
    """POST /jobs/upload streams the raw body to source.<ext> atomically.

    After the request completes the job dir contains ``source.<ext>`` and
    the job is ``status='queued'`` (enqueue flipped it). The worker is off
    (``run_worker=False``) so the job is not picked up.
    """
    pytest.skip("W0 stub — implemented in Task 2")