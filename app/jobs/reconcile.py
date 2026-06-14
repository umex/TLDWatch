"""Startup reconciliation: walk every job folder and heal DB/FS drift.

The manifest is the source of truth (D-03); the DB row is a
projection. In normal operation :func:`app.jobs.manifest.update_stage`
writes the manifest FIRST and updates the DB row LAST (write-
manifest-first, commit-DB-last). A crash between those two steps
leaves a DB row that lags the manifest. The next boot runs
:func:`reconcile_all` to bring the DB row back in sync with the
manifest (Codex HIGH #1 follow-up).

What ``reconcile_all`` does:

1. Walks every ``<data_dir>/jobs/<id>/`` directory.
2. For each one, reads the manifest (or records the folder as a
   ``missing_manifest`` - a leftover from a crash; the folder is
   NOT auto-removed because the user may have data we cannot
   inspect).
3. Reads the full projected state from the DB row (status,
   current_stage, stage_timestamps_json, language, duration_s,
   source_*, summary_kinds_json).
4. UPDATEs the DB row iff any projected field differs from the
   manifest's value. Plan 01-04 H4: the UPDATE projects ALL
   metadata columns (not just current_stage/stage_timestamps_json),
   and the ``updated_at`` is the latest non-None stage timestamp
   (via :func:`_latest_ts`).

Returns a small summary dict ``{scanned, updated, missing_manifests}``
suitable for logging.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.manifest import _latest_ts, read_manifest, stage_to_status
from app.models.settings import Settings
from app.storage.fs import data_dir

_log = logging.getLogger(__name__)


async def reconcile_all(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Walk every per-job folder and UPDATE drifted DB rows.

    ``session_factory`` is the engine's :class:`async_sessionmaker`.
    A new short-lived session is opened per job to keep the
    transaction scope small and to allow other requests to make
    progress in parallel.

    Plan 01-04 H4: the SELECT reads the full projected state, the
    drift check compares every projected field, and the UPDATE
    writes every projected column. The ``updated_at`` is the latest
    non-None stage timestamp (via :func:`_latest_ts`) so a healed
    row reflects the most-recent stage transition.
    """
    jobs_root = data_dir(settings) / "jobs"
    if not jobs_root.is_dir():
        _log.info("reconcile: jobs root %s missing; nothing to do", jobs_root)
        return {"scanned": 0, "updated": 0, "missing_manifests": []}

    summary: dict[str, Any] = {
        "scanned": 0,
        "updated": 0,
        "missing_manifests": [],
    }

    for entry in sorted(os.listdir(jobs_root)):
        sub = jobs_root / entry
        if not sub.is_dir():
            continue
        summary["scanned"] += 1
        try:
            manifest = await read_manifest(settings, entry)
        except FileNotFoundError:
            _log.warning(
                "reconcile: folder %s has no manifest; recording as missing", entry
            )
            summary["missing_manifests"].append(entry)
            continue

        # Compute the projected values from the manifest. These are
        # what the DB row should look like AFTER reconciliation.
        new_ts_json = json.dumps(manifest.stage_timestamps.model_dump())
        new_status = stage_to_status(manifest.current_stage, manifest)
        new_summary_kinds_json = json.dumps(manifest.summary_kinds)
        new_updated_at = _latest_ts(manifest.stage_timestamps)

        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT current_stage, stage_timestamps_json, status, "
                    "language, duration_s, source_type, source_path, "
                    "source_sha256, summary_kinds_json "
                    "FROM jobs WHERE id = :id"
                ),
                {"id": entry},
            )
            row = result.fetchone()
            if row is None:
                # Manifest exists for a job that is not in the DB.
                # This is the inverse drift (DB-first path that
                # crashed before the manifest write, or a hand-
                # copied folder). We do not INSERT here - the DB
                # INSERT is the index; an orphan manifest is a
                # signal for the operator. Logged and skipped.
                _log.warning(
                    "reconcile: manifest exists for unknown job id %s; skipping",
                    entry,
                )
                continue
            (
                db_stage,
                db_ts_json,
                db_status,
                db_language,
                db_duration_s,
                db_source_type,
                db_source_path,
                db_source_sha256,
                db_summary_kinds_json,
            ) = row

            # Drift detection: compare every projected field. The DB
            # stores ``summary_kinds_json`` as a JSON-encoded string;
            # NULL on the row maps to ``[]`` for comparison.
            db_summary_kinds_json_normalised = (
                db_summary_kinds_json if db_summary_kinds_json else "[]"
            )
            drifted = (
                db_stage != manifest.current_stage
                or db_ts_json != new_ts_json
                or db_status != new_status
                or db_language != manifest.language
                or db_duration_s != manifest.duration_s
                or db_source_type != manifest.source_type
                or db_source_path != manifest.source_path
                or db_source_sha256 != manifest.source_sha256
                or db_summary_kinds_json_normalised != new_summary_kinds_json
            )
            if not drifted:
                continue

            await session.execute(
                text(
                    "UPDATE jobs SET status = :status, "
                    "current_stage = :stage, "
                    "stage_timestamps_json = :ts_json, updated_at = :now, "
                    "source_type = :source_type, source_path = :source_path, "
                    "source_sha256 = :source_sha256, duration_s = :duration_s, "
                    "language = :language, "
                    "summary_kinds_json = :summary_kinds_json "
                    "WHERE id = :id"
                ),
                {
                    "status": new_status,
                    "stage": manifest.current_stage,
                    "ts_json": new_ts_json,
                    "now": new_updated_at,
                    "source_type": manifest.source_type,
                    "source_path": manifest.source_path,
                    "source_sha256": manifest.source_sha256,
                    "duration_s": manifest.duration_s,
                    "language": manifest.language,
                    "summary_kinds_json": new_summary_kinds_json,
                    "id": entry,
                },
            )
            await session.commit()
            summary["updated"] += 1
            _log.info(
                "reconcile: healed %s (stage %s -> %s, status %s -> %s)",
                entry,
                db_stage,
                manifest.current_stage,
                db_status,
                new_status,
            )

    _log.info(
        "reconcile: scanned=%d updated=%d missing_manifests=%d",
        summary["scanned"],
        summary["updated"],
        len(summary["missing_manifests"]),
    )
    return summary


__all__ = ["reconcile_all"]
