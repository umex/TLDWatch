"""Streaming upload idempotency test -- plan 05-01 Task 2 (D-11, D-07).

Wave 0 stub: skipped until Task 2 implements the streaming upload route.
The full back-end suite stays green while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_redrop_same_key_collapses_to_existing(client: "object") -> None:
    """Re-POST with the same Idempotency-Key collapses to the existing job.

    First call returns 201, second returns 200 with the same job id, and
    exactly one job row is associated with the key (no orphan duplicate).
    """
    pytest.skip("W0 stub — implemented in Task 2")