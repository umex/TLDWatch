"""Streaming upload idempotency test -- plan 05-01 Task 2 (D-11, D-07).

Integration test asserting a re-drop with the same ``Idempotency-Key``
collapses to the existing job (no orphan duplicate). Reuses the
``_count_jobs_with_key`` helper pattern from ``tests/test_idempotency.py``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


def _count_jobs_with_key(key: str) -> int:
    """Return the number of jobs rows associated with ``key``."""
    import sqlite3

    from app.main import app

    db_path = Path(app.state.settings.data_dir) / "app.db"
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT count(*) FROM jobs WHERE id = ("
            "SELECT job_id FROM idempotency_keys WHERE idempotency_key = ?)",
            (key,),
        ).fetchone()
        return int(row[0])
    finally:
        con.close()


@pytest.mark.asyncio
async def test_redrop_same_key_collapses_to_existing(
    client: httpx.AsyncClient,
) -> None:
    """Re-POST with the same Idempotency-Key collapses to the existing job.

    First call returns 201, second returns 200 with the same job id, and
    exactly one job row is associated with the key (no orphan duplicate).
    """
    headers = {
        "Idempotency-Key": "redrop-key-1",
        "X-Filename": "video.mp4",
        "Content-Type": "application/octet-stream",
    }

    r1 = await client.post("/jobs/upload", content=b"\x00" * 256, headers=headers)
    assert r1.status_code == 201, r1.text
    job_id_a = r1.json()["id"]

    r2 = await client.post("/jobs/upload", content=b"\x00" * 256, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == job_id_a  # SAME job, not a new one

    # No orphan: exactly one job row for this key.
    assert _count_jobs_with_key("redrop-key-1") == 1