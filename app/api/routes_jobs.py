"""``POST /jobs`` + read endpoints ``GET /jobs`` and ``GET /jobs/{id}``.

Internal control endpoints (POST /jobs/{id}/stage and
POST /jobs/{id}/stale-check) are added in Plan 01-03; they are
internal control endpoints. Phase 4 (orchestrator) replaces them
with authenticated, worker-bound endpoints. For Phase 1, loopback-only
access via TrustedHostMiddleware is the security boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.jobs.service import LIST_LIMIT_CAP, LIST_LIMIT_DEFAULT, create_job, get_job, list_jobs
from app.models.job import CreateJobRequest, JobResponse
from app.models.manifest import JobManifest
from app.models.settings import Settings

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "Job created. The on-disk manifest is the rich "
            "snapshot of the new job; the API response carries the "
            "summary fields only.",
            "model": JobManifest,
        }
    },
)
async def post_job(
    payload: CreateJobRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    return await create_job(
        session,
        settings,
        source_type=payload.source_type,
        source_path=payload.source_path,
    )


@router.get("", response_model=list[JobResponse])
async def get_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=LIST_LIMIT_DEFAULT, ge=1),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[JobResponse]:
    """List jobs ordered by ``created_at`` DESC.

    Optional ``?status=`` filter, ``?limit=`` (silently capped at
    :data:`LIST_LIMIT_CAP`), and ``?offset=`` for pagination.
    """
    return await list_jobs(
        session,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_by_id(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    """Return one job by id, or 404 with ``{"detail": "job not found"}``."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
