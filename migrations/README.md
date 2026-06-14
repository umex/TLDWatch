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

> Each migration file SHOULD add at most one column or one table.
> Multi-statement migration files are forbidden because partial
> application cannot be safely skipped (skipping the whole file
> leaves some statements unapplied; re-running it errors on the
> statements that already executed). For Phase 1, `0001_initial.sql`
> is the exception (it creates the initial schema) - every migration
> from 0002 onward must be a single ALTER or single CREATE.

## Boot-time behaviour

On every backend boot, the runner compares the on-disk `*.sql`
filenames to the rows in `schema_version` and applies any not yet
recorded. A failure logs loudly and refuses to start the server - the
schema is always up-to-date on boot (D-08).
