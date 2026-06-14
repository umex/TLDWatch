-- Migration 0005: add the JSON-encoded list of summary kinds requested
-- for this job. Stored as TEXT to keep the migration a single
-- column-add (Phase 8 may add a typed extraction helper).
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches
-- the "duplicate column" OperationalError on re-apply.

ALTER TABLE jobs ADD COLUMN summary_kinds_json TEXT;
