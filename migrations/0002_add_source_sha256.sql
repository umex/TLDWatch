-- Migration 0002: add the SHA-256 of the source file.
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches
-- the "duplicate column" OperationalError on re-apply.

ALTER TABLE jobs ADD COLUMN source_sha256 TEXT;
