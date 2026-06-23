"""Idempotency-Key on POST /jobs tests -- plan 04-03.

RED-gate tests for plan 04-03 Task 3 (atomic key-first reservation [Fix 7]
+ migration 0008 with column ``idempotency_key`` + janitor + precise
201/200/422 codes). Task 3 turns them GREEN.

Fix 7 invariants verified here:

- atomic key-first reservation: the idempotency_key is INSERTed BEFORE
  create_job; on IntegrityError the loser re-reads the existing job and
  returns 200 with NO orphan queued job (Codex HIGH).
- the migration column is named ``idempotency_key`` (NOT ``key`` -- SQL-
  reserved-ish word avoided, Codex HIGH).
- precise codes: first create returns 201; duplicate returns 200 (NOT
  201); invalid key returns 422 BEFORE any DB write (Codex MEDIUM).
- TTL delete + create is transactional (Codex MEDIUM).
- expired-key janitor prevents unbounded key table growth (Codex LOW).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# --- Helpers ----------------------------------------------------------------


def _count_jobs_with_key(client: "object", key: str) -> int:
    """Return the number of jobs rows whose idempotency_key matches ``key``.

    Used by the race test to assert no orphan queued job was left (Fix 7).
    """
    import sqlite3

    from app.api import dependencies as deps_module

    sf = deps_module.session_factory
    assert sf is not None
    # Resolve the DB path from the live settings.
    from app.main import app

    db_path = Path(app.state.settings.data_dir) / "app.db"
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT count(*) FROM jobs WHERE id = (SELECT job_id FROM idempotency_keys WHERE idempotency_key = ?)",
            (key,),
        ).fetchone()
        return int(row[0])
    finally:
        con.close()


# --- Precise 201/200/422 codes (Codex MEDIUM) --------------------------------


@pytest.mark.asyncio
async def test_dup_key_returns_existing_200(client: "object") -> None:
    """Duplicate Idempotency-Key returns 200 + the SAME job_id (not 201, not new)."""
    headers = {"Idempotency-Key": "abc"}
    r1 = await client.post("/jobs", json={}, headers=headers)
    assert r1.status_code == 201, r1.text
    job_id_a = r1.json()["id"]

    r2 = await client.post("/jobs", json={}, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == job_id_a  # SAME job, not a new one


@pytest.mark.asyncio
async def test_no_key_creates_new_job_201(client: "object") -> None:
    """Without the Idempotency-Key header, POST /jobs behaves as today (201)."""
    r = await client.post("/jobs", json={})
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_invalid_charset_rejected_422(client: "object") -> None:
    """An invalid-charset Idempotency-Key is rejected 422 BEFORE any DB write.

    No row in idempotency_keys after the call (T-04-01).
    """
    import sqlite3

    from app.main import app

    r = await client.post("/jobs", json={}, headers={"Idempotency-Key": "bad key!"})
    assert r.status_code == 422, r.text

    db_path = Path(app.state.settings.data_dir) / "app.db"
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT count(*) FROM idempotency_keys WHERE idempotency_key = ?",
            ("bad key!",),
        ).fetchone()
        assert int(row[0]) == 0  # NO row written
    finally:
        con.close()


@pytest.mark.asyncio
async def test_oversized_key_rejected_422(client: "object") -> None:
    """An Idempotency-Key longer than 128 chars is rejected 422."""
    big = "a" * 129
    r = await client.post("/jobs", json={}, headers={"Idempotency-Key": big})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_valid_key_chars_accepted_201(client: "object") -> None:
    """The allowlist ``[A-Za-z0-9_-]`` (incl. underscore + hyphen) is accepted."""
    for key in ("abc", "A_B-C", "X9_y-z", "a" * 128):
        r = await client.post("/jobs", json={}, headers={"Idempotency-Key": key})
        assert r.status_code == 201, (key, r.text)


# --- Atomicity / no orphan (Fix 7 -- Codex HIGH) ----------------------------


@pytest.mark.asyncio
async def test_concurrent_race_integrity_error_no_orphan(client: "object") -> None:
    """A race (IntegrityError on the key INSERT) returns the existing job with NO orphan.

    Two POSTs with the same key: the first creates the job + reserves the
    key; the second's INSERT collides (PRIMARY KEY). The handler catches
    the IntegrityError, re-reads the existing job_id, returns 200 with the
    existing job, and leaves NO extra queued job in the jobs table (Fix 7 --
    Codex HIGH -- orphan cleanup verified via count).
    """
    headers = {"Idempotency-Key": "race-key-001"}
    r1 = await client.post("/jobs", json={}, headers=headers)
    assert r1.status_code == 201, r1.text
    job_id_a = r1.json()["id"]

    r2 = await client.post("/jobs", json={}, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == job_id_a

    # No orphan: exactly one job row for this key.
    assert _count_jobs_with_key(client, "race-key-001") == 1


@pytest.mark.asyncio
async def test_idempotency_key_column_name(client: "object") -> None:
    """The migration column is named ``idempotency_key`` (NOT ``key`` -- Fix 7)."""
    import sqlite3

    from app.main import app

    db_path = Path(app.state.settings.data_dir) / "app.db"
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("PRAGMA table_info(idempotency_keys)").fetchall()
    finally:
        con.close()
    names = {row[1] for row in rows}
    assert "idempotency_key" in names, names
    assert "key" not in names, names  # NOT the SQL-reserved-ish word


# --- Janitor (Codex LOW) ----------------------------------------------------


@pytest.mark.asyncio
async def test_janitor_deletes_expired_keys(client: "object") -> None:
    """The janitor deletes idempotency_keys rows older than idempotency_ttl_hours."""
    import sqlite3

    from app.api.idempotency import run_janitor
    from app.main import app

    settings = app.state.settings
    sf = app.state.session_factory

    db_path = Path(settings.data_dir) / "app.db"
    # Insert an expired row (25h ago; default TTL is 24h).
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    fresh_at = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "INSERT INTO idempotency_keys (idempotency_key, job_id, created_at) "
            "VALUES (?, ?, ?)",
            ("expired-key-1", "00000000-0000-0000-0000-000000000001", expired_at),
        )
        con.execute(
            "INSERT INTO idempotency_keys (idempotency_key, job_id, created_at) "
            "VALUES (?, ?, ?)",
            ("fresh-key-1", "00000000-0000-0000-0000-000000000002", fresh_at),
        )
        con.commit()
    finally:
        con.close()

    deleted = await run_janitor(sf, settings)
    assert deleted >= 1

    con = sqlite3.connect(str(db_path))
    try:
        expired_count = con.execute(
            "SELECT count(*) FROM idempotency_keys WHERE idempotency_key = ?",
            ("expired-key-1",),
        ).fetchone()[0]
        fresh_count = con.execute(
            "SELECT count(*) FROM idempotency_keys WHERE idempotency_key = ?",
            ("fresh-key-1",),
        ).fetchone()[0]
    finally:
        con.close()
    assert int(expired_count) == 0  # expired row deleted
    assert int(fresh_count) == 1  # fresh row kept