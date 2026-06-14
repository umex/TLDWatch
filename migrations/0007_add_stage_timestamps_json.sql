-- Migration 0007: add the JSON-encoded map of stage -> wall-clock
-- timestamp. Mirrors the manifest's stage_timestamps so the DB
-- index reflects the file-as-truth without a per-stage table.
-- Idempotent: a single ALTER TABLE ADD COLUMN; the runner catches
-- the "duplicate column" OperationalError on re-apply.

ALTER TABLE jobs ADD COLUMN stage_timestamps_json TEXT;
