"""Tests for :func:`app.storage.db.apply_migrations` idempotency (Plan 01-04 T9).

A re-run of ``apply_migrations`` is a no-op: the seven migration
files have already been applied, so the runner should NOT raise,
NOT duplicate the version rows, and NOT re-execute the DDL.
Additionally, a partial-apply scenario (column was added in a
prior run, but the version row was missing) is recovered: the
second run records the missing version row.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.models.diagnostics import GpuBackend
from app.models.settings import Settings
from app.storage.db import apply_migrations, make_engine


@pytest.mark.asyncio
async def test_apply_migrations_three_times() -> None:
    """apply_migrations is idempotent across three consecutive calls."""
    td = Path(tempfile.mkdtemp(prefix="tan-mig-"))
    s = Settings(data_dir=str(td), backend=GpuBackend.CPU)
    e = make_engine(s)

    # First call applies all 7 migrations.
    await apply_migrations(e)
    db_path = td / "app.db"

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    con.close()

    # Second and third calls: idempotent.
    await apply_migrations(e)
    await apply_migrations(e)

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6, 7], (
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

    # Re-apply: every statement is a duplicate-column error, the
    # all-duplicate branch fires, and the version row is recorded.
    await apply_migrations(e)

    con = sqlite3.connect(db_path)
    after = con.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    assert after == before + 1, (before, after)
    assert sorted(
        r[0] for r in con.execute("SELECT version FROM schema_version").fetchall()
    ) == [1, 2, 3, 4, 5, 6, 7]
    con.close()
