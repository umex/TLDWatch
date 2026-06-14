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
3. Reads the current DB row's ``current_stage`` and
   ``stage_timestamps_json``.
4. UPDATEs the DB row iff the manifest's ``current_stage`` or
   ``stage_timestamps_json`` differs from the DB row. The
   ``updated_at`` column is also refreshed.

Returns a small summary dict ``{scanned, updated, missing_manifests}``
suitable for logging.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.manifest import read_manifest
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

        new_ts_json = json.dumps(manifest.stage_timestamps.model_dump())
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT current_stage, stage_timestamps_json "
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
            db_stage = row[0]
            db_ts_json = row[1]
            if db_stage == manifest.current_stage and db_ts_json == new_ts_json:
                continue
            await session.execute(
                text(
                    "UPDATE jobs SET current_stage = :stage, "
                    "stage_timestamps_json = :ts_json, updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "stage": manifest.current_stage,
                    "ts_json": new_ts_json,
                    "now": manifest.stage_timestamps.queued,
                    "id": entry,
                },
            )
            await session.commit()
            summary["updated"] += 1
            _log.info(
                "reconcile: healed %s (stage %s -> %s)",
                entry,
                db_stage,
                manifest.current_stage,
            )

    _log.info(
        "reconcile: scanned=%d updated=%d missing_manifests=%d",
        summary["scanned"],
        summary["updated"],
        len(summary["missing_manifests"]),
    )
    return summary


__all__ = ["reconcile_all"]
