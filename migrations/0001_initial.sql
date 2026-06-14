-- Migration 0001: initial schema.
-- Idempotent: every statement is CREATE ... IF NOT EXISTS so re-running is safe.
-- Hand-rolled migration runner (see migrations/README.md) records this file
-- in schema_version only after the DDL has applied successfully.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    source_type TEXT,
    source_path TEXT,
    current_stage TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
