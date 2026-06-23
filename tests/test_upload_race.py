"""Streaming upload worker-race test -- plan 05-01 Task 2 (INGEST-01, Pitfall 1).

Wave 0 stub: skipped until Task 2 implements the streaming upload route.
The full back-end suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_worker_invisible_to_uploading_job(tmp_data_dir: "object") -> None:
    """A job in ``status='uploading'`` is invisible to ``pull_next``.

    ``pull_next`` selects only ``status='queued'`` rows, so a mid-upload
    job is never picked up. After the upload route calls ``enqueue`` the
    status flips to ``'queued'`` and ``pull_next`` returns the job id.
    """
    pytest.skip("W0 stub — implemented in Task 2")