-- Migration 0009: persist the original dropped filename (plan 05-04).
-- Additive nullable TEXT column on jobs; HistoryRow displays it with a
-- basename(source_path) fallback. source_path still points at the
-- in-job-dir source.<ext> file (D-04 unchanged) -- original_filename is
-- a pure display field.
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches the
-- "duplicate column" OperationalError on re-apply (same convention as
-- 0002_add_source_sha256.sql).

ALTER TABLE jobs ADD COLUMN original_filename TEXT;