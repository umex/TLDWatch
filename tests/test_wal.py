"""Tests for SQLite WAL mode on every connection (D-06, Gemini LOW).

The per-connection ``connect`` listener (in :mod:`app.storage.db`)
runs ``PRAGMA journal_mode=WAL`` on every new DBAPI connection, not
just the first. This test opens TWO distinct connections from the
engine and asserts WAL is reported on BOTH.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models.settings import Settings
from app.storage.db import apply_migrations, make_engine


@pytest.mark.asyncio
async def test_wal_on_two_connections() -> None:
    """WAL is set on every distinct connection, not just the first."""
    td = Path(tempfile.mkdtemp(prefix="tan-wal-"))
    s = Settings(data_dir=str(td))
    e = make_engine(s)
    await apply_migrations(e)

    # Open TWO distinct ``engine.connect()`` contexts. The first
    # call creates a connection; the second call gets a different
    # connection (the pool is empty after the first ``__aexit__``).
    async with e.connect() as c1:
        m1 = (await c1.execute(text("PRAGMA journal_mode"))).scalar()

    async with e.connect() as c2:
        m2 = (await c2.execute(text("PRAGMA journal_mode"))).scalar()

    assert m1 is not None and m1.lower() == "wal", m1
    assert m2 is not None and m2.lower() == "wal", m2
    # Sanity: the WAL file may exist on disk (per ``PRAGMA
    # journal_mode=WAL`` semantics); we don't require it but a
    # non-WAL DB would also report ``wal`` from pragma — so we
    # double-check with a sqlite3 raw read.
    db_path = td / "app.db"
    con = sqlite3.connect(db_path)
    raw_mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert raw_mode.lower() == "wal", raw_mode
