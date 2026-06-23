"""Tests for :func:`app.storage.db.apply_migrations` idempotency (Plan 01-04 T9).

A re-run of ``apply_migrations`` is a no-op: the migration files have
already been applied, so the runner should NOT raise, NOT duplicate the
version rows, and NOT re-execute the DDL. Additionally, a partial-apply
scenario (column was added in a prior run, but the version row was
missing) is recovered: the second run records the missing version row.

Plan 04-03: migration 0008 (idempotency_keys) added version 8 to the
expected set. ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS`` are no-ops on re-apply (no error), so the runner records version
8 cleanly on the first apply and never re-executes the DDL.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.storage.db import apply_migrations, make_engine

# The full set of migration versions applied by the runner. Updated in
# Plan 04-03 when migration 0008 (idempotency_keys) was added.
_APPLIED_VERSIONS = [1, 2, 3, 4, 5, 6, 7, 8]


@pytest.mark.asyncio
async def test_apply_migrations_three_times() -> None:
    """apply_migrations is idempotent across three consecutive calls."""
    td = Path(tempfile.mkdtemp(prefix="tan-mig-"))
    s = Settings(data_dir=str(td), backend=GpuBackend.CPU)
    e = make_engine(s)

    # First call applies all migrations.
    await apply_migrations(e)
    db_path = td / "app.db"

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r[0] for r in rows] == _APPLIED_VERSIONS
    con.close()

    # Second and third calls: idempotent.
    await apply_migrations(e)
    await apply_migrations(e)

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r[0] for r in rows] == _APPLIED_VERSIONS, (
        f"version rows duplicated after triple-apply: {rows}"
    )
    con.close()


@pytest.mark.asyncio
async def test_apply_migrations_recovers_missing_version_row() -> None:
    """If a column was added in a prior partial run but the version
    row was never recorded, a re-run of apply_migrations records the
    missing version row (T9 all-duplicate-column path)."""
    td = Path(tempfile.mkdtemp(prefix="tan-mig-partial-"))
    s = Settings(data_dir=str(td), backend=GpuBackend.CPU)
    e = make_engine(s)

    await apply_migrations(e)
    db_path = td / "app.db"

    # Simulate a partial prior run: column work was done, but the
    # version row was lost. We delete the MAX(version) row.
    con = sqlite3.connect(db_path)
    con.execute(
        "DELETE FROM schema_version WHERE version = (SELECT MAX(version) FROM schema_version)"
    )
    con.commit()
    before = con.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    con.close()

    # Re-apply: every statement is a duplicate-column error (or a
    # CREATE-TABLE/INDEX IF NOT EXISTS no-op for 0008), the
    # all-duplicate / no-error branch fires, and the version row is
    # recorded.
    await apply_migrations(e)

    con = sqlite3.connect(db_path)
    after = con.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    assert after == before + 1, (before, after)
    assert sorted(
        r[0] for r in con.execute("SELECT version FROM schema_version").fetchall()
    ) == _APPLIED_VERSIONS
    con.close()
