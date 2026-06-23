"""Streaming upload atomic-cleanup test -- plan 05-01 Task 2 (INGEST-01).

Wave 0 stub: skipped until Task 2 implements the streaming upload route.
The full back-end suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_aborted_upload_leaves_no_source(client: "object") -> None:
    """Aborting the request mid-stream leaves no ``source.<ext>`` in the job dir.

    Only the ``.tmp_*`` scratch file may be created, and the route's
    ``except BaseException: os.unlink(tmp)`` cleans it up.
    """
    pytest.skip("W0 stub — implemented in Task 2")