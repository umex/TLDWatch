"""SQLite engine, session factory, and migration runner.

Every connection is forced into WAL mode with foreign keys and
``synchronous=NORMAL`` via a per-connection ``connect`` listener - not
just the first connection - so the test that opens two connections
sees ``journal_mode=wal`` on both (D-06, Gemini LOW).

Migrations live in ``<project_root>/migrations/`` and are applied
in filename order by a hand-rolled runner that records each file in
the ``schema_version`` table after the file's DDL has applied
successfully (D-07, D-08).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.settings import Settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR_NAME = "migrations"


def _sqlite_url(settings: Settings) -> str:
    """Build a forward-slash SQLite URL aiosqlite accepts on Windows."""
    db_path = Path(settings.data_dir).resolve() / "app.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
    """Connect-listener: enforce WAL + foreign keys + synchronous per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def make_engine(settings: Settings) -> AsyncEngine:
    """Build the :class:`AsyncEngine` and register the per-connection listener."""
    engine = create_async_engine(
        _sqlite_url(settings),
        echo=False,
        future=True,
    )
    event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragmas)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an :class:`AsyncSession` factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _split_sql_statements(raw: str) -> list[str]:
    """Split a multi-statement SQL file into individual non-empty statements.

    SQLite's aiosqlite driver (and SQLAlchemy's ``text()``) execute one
    statement per ``execute()`` call. Our migration files contain only
    DDL with no semicolons inside string literals, so a simple
    semicolon-split with comment stripping is sufficient and avoids
    pulling in a full SQL parser.
    """
    out: list[str] = []
    for line in raw.splitlines():
        # Drop full-line SQL comments so their semicolons do not split
        # the stream. Inline ``--`` comments are not produced by our
        # generator; a full-line strip is enough.
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        out.append(line)
    body = "\n".join(out)
    return [s.strip() for s in body.split(";") if s.strip()]


def _migrations_dir() -> Path:
    # Project root: <repo>/migrations/ (sibling of the app/ package).
    return Path(__file__).resolve().parent.parent.parent / MIGRATIONS_DIR_NAME


async def apply_migrations(engine: AsyncEngine) -> None:
    """Apply any unapplied ``migrations/*.sql`` files in filename order."""
    migrations_dir = _migrations_dir()
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {migrations_dir}")

    # Sort by filename. The four-digit prefix in ``NNNN_description.sql``
    # gives lexicographic == numeric ordering, which is the convention
    # the runner relies on.
    sql_files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())

    async with engine.begin() as conn:  # transactional context
        # Bootstrap: ensure the ``schema_version`` table exists. We do
        # this unconditionally here (not via a 0000 migration) so the
        # first boot works even with an empty database.
        await conn.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
        )
        result = await conn.execute(sa.text("SELECT version FROM schema_version"))
        applied = {row[0] for row in result.fetchall()}

        for sql_file in sql_files:
            try:
                version = int(sql_file.stem.split("_", 1)[0])
            except (ValueError, IndexError) as exc:
                raise RuntimeError(
                    f"migration filename must be NNNN_description.sql: {sql_file.name}"
                ) from exc
            if version in applied:
                continue

            logger.info("applying migration %s", sql_file.name)
            # SQLAlchemy's ``text()`` executes a single statement per
            # ``execute()``; SQLite's aiosqlite driver enforces the same
            # constraint. Split the file into individual statements on
            # semicolons (a robust-enough split for our DDL-only files
            # which do not embed semicolons inside string literals).
            raw = sql_file.read_text(encoding="utf-8")
            for stmt in _split_sql_statements(raw):
                if not stmt:
                    continue
                await conn.execute(sa.text(stmt))
            applied_at = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                sa.text(
                    "INSERT INTO schema_version (version, applied_at) "
                    "VALUES (:version, :applied_at)"
                ),
                {"version": version, "applied_at": applied_at},
            )
