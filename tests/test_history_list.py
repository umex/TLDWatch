"""History list back-end test -- plan 05-01 Task 3 (JOB-03).

Wave 0 stub: skipped until Task 3 implements the history list contract
test. The full back-end suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_history_done_newest_first(client: "object") -> None:
    """GET /jobs?status=done returns only done jobs newest-first (JOB-03)."""
    pytest.skip("W0 stub — implemented in Task 3")