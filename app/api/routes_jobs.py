"""Job routes: ``POST /jobs`` + reads + internal control endpoints.

Phase 1 endpoints (loopback-only, TrustedHostMiddleware is the
boundary in Phase 1):

- ``POST /jobs`` - create a new job end-to-end
- ``GET /jobs`` - list jobs newest-first
- ``GET /jobs/{id}`` - one job, 404 on miss
- ``POST /jobs/{id}/cancel`` - mark cancelled, delete folder
- ``POST /jobs/{id}/stage`` - advance the stage and optionally
  patch the manifest
- ``POST /jobs/{id}/stale-check`` - mark failed if idle > threshold

The three ``/jobs/{id}/*`` routes are internal control endpoints
added in Plan 01-03. Phase 4 (orchestrator) replaces them with
authenticated, worker-bound endpoints. For Phase 1, loopback-only
access via TrustedHostMiddleware is the security boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.jobs.cleanup import cancel_job, mark_stale
from app.jobs.ids import validate_job_id
from app.jobs.manifest import update_stage
from app.jobs.service import LIST_LIMIT_CAP, LIST_LIMIT_DEFAULT, create_job, get_job, list_jobs
from app.models.job import (
    CreateJobRequest,
    JobResponse,
    StageUpdateRequest,
    StaleCheckRequest,
    StaleCheckResponse,
)
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


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def post_cancel(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    """Cancel a job: mark the DB row cancelled and delete the per-job folder.

    The DB UPDATE happens first; the folder delete is best-effort
    and the row is marked cancelled even if the folder delete
    fails (a future call can retry). Returns 400 if the job id is
    not a valid UUID, 404 if no such job exists.
    """
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc

    ok = await cancel_job(session, settings, canonical_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    refreshed = await get_job(session, canonical_id)
    if refreshed is None:  # pragma: no cover - cancel_job just updated the row
        raise HTTPException(status_code=404, detail="job not found")
    return refreshed


@router.post(
    "/{job_id}/stage",
    response_model=JobManifest,
    responses={
        404: {"description": "job or manifest not found"},
        422: {"description": "ManifestPatch validation failed"},
    },
)
async def post_stage(
    job_id: str,
    payload: StageUpdateRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobManifest:
    """Advance the job's stage and optionally patch the manifest.

    - 400 if the job id is not a valid UUID.
    - 404 if the job's manifest does not exist on disk.
    - 422 if the :class:`ManifestPatch` is invalid (extra fields
      or wrong types).
    - 200 with the new :class:`JobManifest` on success.
    """
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc

    try:
        manifest = await update_stage(
            settings, session, canonical_id, payload.stage, payload.manifest_patch
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="manifest not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return manifest


@router.post(
    "/{job_id}/stale-check",
    response_model=StaleCheckResponse,
)
async def post_stale_check(
    job_id: str,
    payload: StaleCheckRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> StaleCheckResponse:
    """Mark a job failed with ``error='stalled'`` if it is stale.

    Returns 404 if the job does not exist; 200 with
    ``{stale, marked}`` on success. The lookup happens BEFORE
    the UUID is validated so a non-UUID id like ``missing-id``
    still returns 404 (consistent with ``GET /jobs/{id}``).
    """
    existing = await get_job(session, job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")

    stale, marked = await mark_stale(
        session, settings, job_id, payload.threshold_s
    )
    return StaleCheckResponse(stale=stale, marked=marked)
