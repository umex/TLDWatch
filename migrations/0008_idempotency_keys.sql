-- Migration 0008: idempotency_keys table (plan 04-03, SC-5, D-07).
--
-- Stores the Idempotency-Key -> job_id mapping so a duplicate POST /jobs
-- with the same key collapses to the existing job instead of spawning a
-- duplicate. The column is named ``idempotency_key`` (NOT ``key`` -- Fix 7
-- Codex HIGH -- ``key`` is SQL-reserved-ish and avoided). The PRIMARY KEY
-- on ``idempotency_key`` enforces uniqueness (PRIMARY KEY implies UNIQUE
-- in SQLite), so a concurrent duplicate race raises IntegrityError on
-- collision (caught by resolve_or_create -- no orphan duplicate, Fix 7).
-- The index on ``created_at`` supports the janitor's ``DELETE WHERE
-- created_at < :cutoff`` sweep (Codex LOW).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS
-- make a re-apply a no-op. The migration runner auto-discovers this file
-- by glob -- NO change to app/storage/db.py is needed.

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_created_at
    ON idempotency_keys(created_at);