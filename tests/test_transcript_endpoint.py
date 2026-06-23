"""Transcript read endpoint tests -- plan 05-01 Task 2 (D-14).

Wave 0 stub: skipped until Task 2 implements the transcript read route
(``GET /jobs/{id}/transcript``). The full back-end suite stays green
while the stubs skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_transcript_returns_200_when_present(client: "object") -> None:
    """GET /jobs/{id}/transcript returns 200 + the Transcript JSON when present."""
    pytest.skip("W0 stub — implemented in Task 2")