-- Migration 0003: add the audio / video duration in seconds.
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches
-- the "duplicate column" OperationalError on re-apply.

ALTER TABLE jobs ADD COLUMN duration_s REAL;
