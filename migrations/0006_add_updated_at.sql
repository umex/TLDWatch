-- Migration 0006: add the wall-clock timestamp of the last update to
-- this row. Updated by every stage mutator after the manifest is
-- rewritten.
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches
-- the "duplicate column" OperationalError on re-apply.

ALTER TABLE jobs ADD COLUMN updated_at TEXT;
