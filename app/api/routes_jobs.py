"""``POST /jobs`` route - end-to-end job creation.

Internal control endpoints (POST /jobs/{id}/stage and
POST /jobs/{id}/stale-check) are added in Plan 01-03; they are
internal control endpoints. Phase 4 (orchestrator) replaces them
with authenticated, worker-bound endpoints. For Phase 1, loopback-only
access via TrustedHostMiddleware is the security boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.jobs.service import create_job
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
