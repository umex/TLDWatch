"""Streaming upload memory-bound test -- plan 05-01 Task 2 (INGEST-01).

Wave 0 stub: skipped until Task 2 implements the streaming upload route.
The full back-end suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upload_does_not_buffer_in_memory(client: "object") -> None:
    """Uploading a >100MB fixture does not grow process memory proportionally.

    The ``request.stream()`` + ``aiofiles`` path must NOT buffer the whole
    body in process memory (Pitfall 2 / SC-1). ``tracemalloc`` peak during
    the upload is well below the file size.
    """
    pytest.skip("W0 stub — implemented in Task 2")