"""Job service: the only module (besides ``app/storage``) that
imports the atomic-write helper.

Routes call :func:`create_job`, :func:`list_jobs`, and
:func:`get_job` via this service. The service writes the DB row,
creates the per-job directory, and writes the initial manifest
atomically. Ordering: DB INSERT first (the index), then folder +
manifest (the on-disk truth). A crash between the INSERT and the
manifest write leaves a DB row pointing at a missing folder; that
is reconcilable on boot by either the orchestrator (Phase 4) or a
re-run of the job. A crash between folder creation and manifest
write is mitigated because the manifest is written atomically.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.ids import new_job_id
from app.jobs.manifest import empty_manifest, write_manifest
from app.models.job import JobResponse, _row_to_response
from app.models.manifest import JobManifest  # noqa: F401  (re-exported for tests)
from app.models.settings import Settings
from app.storage.fs import ensure_job_dir
from app.util.time import utcnow_iso

# Pagination: silent cap per Codex MEDIUM ("List pagination is
# incomplete - silent cap of 200"). The cap protects the API from
# accidental large reads; clients that need more can page with
# ``offset``.
LIST_LIMIT_CAP = 200
LIST_LIMIT_DEFAULT = 50


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


async def list_jobs(
    session: AsyncSession,
    status: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> list[JobResponse]:
    """List jobs ordered newest-first, optionally filtered by status.

    ``limit`` is silently capped at :data:`LIST_LIMIT_CAP` to prevent
    accidental large reads; ``offset`` is clamped to ``>= 0``.
    """
    effective_limit = min(max(int(limit), 1), LIST_LIMIT_CAP)
    effective_offset = max(int(offset), 0)

    base_query = (
        sa.select(
            sa.column("id"),
            sa.column("status"),
            sa.column("created_at"),
            sa.column("source_type"),
            sa.column("source_path"),
            sa.column("source_sha256"),
            sa.column("current_stage"),
            sa.column("duration_s"),
            sa.column("language"),
            sa.column("summary_kinds_json"),
            sa.column("updated_at"),
            sa.column("error"),
        )
        .select_from(sa.table("jobs"))
        .order_by(sa.column("created_at").desc())
        .limit(effective_limit)
        .offset(effective_offset)
    )
    if status is not None:
        base_query = base_query.where(sa.column("status") == status)

    result = await session.execute(base_query)
    return [_row_to_response(row) for row in result.fetchall()]


async def get_job(session: AsyncSession, job_id: str) -> JobResponse | None:
    """Return the job with the given id, or ``None`` if not found."""
    query = (
        sa.select(
            sa.column("id"),
            sa.column("status"),
            sa.column("created_at"),
            sa.column("source_type"),
            sa.column("source_path"),
            sa.column("source_sha256"),
            sa.column("current_stage"),
            sa.column("duration_s"),
            sa.column("language"),
            sa.column("summary_kinds_json"),
            sa.column("updated_at"),
            sa.column("error"),
        )
        .select_from(sa.table("jobs"))
        .where(sa.column("id") == job_id)
        .limit(1)
    )
    result = await session.execute(query)
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_response(row)
