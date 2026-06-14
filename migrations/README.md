# Migrations

This directory holds a hand-rolled, single-process migration runner
for the local SQLite database. There is no Alembic and no autogenerate
- the schema is small and the changes are owned by the phase that
needs them.

## Filename convention

`NNNN_description.sql` with a four-digit, zero-padded numeric prefix.
Files are applied in filename order, which (because of the zero
padding) is the same as numeric order. The numeric prefix is parsed
by the runner and stored in the `schema_version` table as the
`version` column.

## Transactional model

Each `.sql` file is applied as a single SQL statement bundle inside
one SQLite transaction. The runner uses `INSERT INTO
schema_version` to record the version **only after** the file's DDL
applies successfully. If the file's statements raise, the transaction
rolls back and no row is recorded - the next boot re-attempts the
file from scratch.

## Per-statement guard rule (from Plan 01-02 onward)

> Each migration file MUST add at most one column or one table.
> Multi-statement migration files are forbidden because partial
> application cannot be safely skipped (skipping the whole file
> leaves some statements unapplied; re-running it errors on the
> statements that already executed). For Phase 1, `0001_initial.sql`
> is the exception (it creates the initial schema) - every migration
> from 0002 onward must be a single `ALTER TABLE` or single
> `CREATE`.

The runner in `app/storage/db.py::apply_migrations` catches the
**"duplicate column"** `OperationalError` from SQLite on
`ALTER TABLE ADD COLUMN` and treats that specific error as a no-op
(continue to the next statement, do NOT abort the migration). This
makes partial application safe: if migration 0003's column was
added but the `schema_version` row was not committed, the next run
skips the statement (catches the duplicate column error) and
records the version. Any other error re-raises so the migration
aborts and the server refuses to start (D-08).

### Why we rejected the per-file `GUARDS` approach

The earlier design considered a per-file `migrations/_guards.py`
that listed `(table, column)` tuples per migration and skipped the
whole file if any column existed. **We rejected this approach** for
partial-application fragility:

- A migration file with two `ALTER TABLE ADD COLUMN` statements
  could partially apply (one column created, the other not), and
  the per-file guard would skip the whole file on the next boot,
  leaving the second column permanently missing.
- A per-file guard with a single column has no benefit over the
  per-statement guard the runner already implements.

The per-statement guard handles the partial-application case
correctly: each `ALTER TABLE` is judged independently. The
`_guards.py` file is NOT present in this repo (and must not be
re-added without revisiting this design decision).

## Boot-time behaviour

On every backend boot, the runner compares the on-disk `*.sql`
filenames to the rows in `schema_version` and applies any not yet
recorded. A failure logs loudly and refuses to start the server - the
schema is always up-to-date on boot (D-08).
