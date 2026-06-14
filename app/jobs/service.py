"""Job service: the only module (besides ``app/storage``) that
imports the atomic-write helper.

Routes call :func:`create_job` via this service. The service writes
the DB row, creates the per-job directory, and writes the initial
manifest atomically. Ordering: DB INSERT first (the index), then
folder + manifest (the on-disk truth). A crash between the INSERT
and the manifest write leaves a DB row pointing at a missing folder;
that is reconcilable on boot by either the orchestrator (Phase 4) or
a re-run of the job. A crash between folder creation and manifest
write is mitigated because the manifest is written atomically.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.ids import new_job_id
from app.jobs.manifest import empty_manifest, write_manifest
from app.models.job import JobResponse
from app.models.manifest import JobManifest  # noqa: F401  (re-exported for tests)
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir
from app.util.time import utcnow_iso


async def create_job(
    session: AsyncSession,
    settings: Settings,
    source_type: str | None = None,
    source_path: str | None = None,
) -> JobResponse:
    """Create a new job end-to-end: DB row, per-job folder, manifest."""
    job_id = new_job_id()
    now_iso = utcnow_iso()

    await session.execute(
        text(
            "INSERT INTO jobs "
            "(id, created_at, status, source_type, source_path, current_stage) "
            "VALUES (:id, :created_at, :status, :source_type, :source_path, :current_stage)"
        ),
        {
            "id": job_id,
            "created_at": now_iso,
            "status": "queued",
            "source_type": source_type,
            "source_path": source_path,
            "current_stage": None,
        },
    )
    await session.commit()

    await ensure_job_dir(settings, job_id)
    await write_manifest(settings, empty_manifest(job_id))

    return JobResponse(
        id=job_id,
        status="queued",
        created_at=datetime.fromisoformat(now_iso),
        source_type=source_type,
        current_stage=None,
    )
