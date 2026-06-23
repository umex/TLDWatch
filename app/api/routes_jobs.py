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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.api.idempotency import resolve_or_create
from app.jobs.cleanup import mark_stale
from app.jobs.ids import validate_job_id
from app.jobs.queue import cancel as queue_cancel
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
)
async def post_job(
    request: Request,
    payload: CreateJobRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    """Create a new job, or collapse a duplicate ``Idempotency-Key`` to the existing job.

    Plan 04-03 (SC-5, D-07, Fix 7):

    - No ``Idempotency-Key`` header -> create a new job (201, existing
      behavior).
    - Valid ``Idempotency-Key`` + first call -> reserve the key +
      create a new job under the reserved id (201).
    - Valid ``Idempotency-Key`` + duplicate call -> the key INSERT
      collides (IntegrityError); the handler re-reads the existing job
      and returns it (200, NOT 201) with no orphan duplicate (Fix 7 --
      Codex HIGH).
    - Invalid / oversized ``Idempotency-Key`` -> 422 BEFORE any DB
      write (T-04-01, Codex MEDIUM -- exact exception path).

    The status code is set per-response via the ``Response`` dependency
    (201 for new, 200 for duplicate); the route's declared 201 is the
    default for the no-key + first-key paths.
    """
    try:
        response, status_code = await resolve_or_create(
            request,
            session,
            settings,
            lambda job_id=None: create_job(
                session,
                settings,
                source_type=payload.source_type,
                source_path=payload.source_path,
                job_id=job_id,
            ),
        )
    except ValueError:
        # validate_idempotency_key rejected the header (T-04-01).
        # 422 BEFORE any DB write (Codex MEDIUM -- exact exception path).
        raise HTTPException(status_code=422, detail="invalid Idempotency-Key")
    return Response(
        content=response.model_dump_json(),
        media_type="application/json",
        status_code=status_code,
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
    """Cancel a job via the cooperative ``queue.cancel`` path (WR-04, D-06).

    The route calls ``queue.cancel(job_id, session, settings)`` -- the
    cooperative cancel implemented in plan 04-02 -- and maps the returned
    ``{status, id}`` dict to a :class:`JobResponse`:

    - ``{}`` (job not found) -> 404.
    - ``queued``: ``queue.cancel`` runs ``cancel_job`` (DB-first + rmtree) +
      ``_work_signal.set``; the route returns 200 with the cancelled row.
    - ``running`` (starting / ingesting / transcribing): ``queue.cancel`` only
      sets the ``_running`` threading.Event cancel flag; the orchestrator's
      ``JobCancelled`` path does the ``cancel_job`` + rmtree at the next chunk
      boundary (no destructive out-from-under rmtree -- WR-04). The route
      returns 200 with the current row (still ``transcribing`` at the moment
      of return -- the orchestrator flips it asynchronously).
    - ``terminal`` (done / failed / cancelled): ``queue.cancel`` is a no-op
      returning the row unchanged (D-06 idempotent); the route returns 200
      with the row (NOT 404 -- a second cancel is a no-op).

    Returns 400 if the job id is not a valid UUID.
    """
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc

    result = await queue_cancel(canonical_id, session, settings)
    if not result:  # {} -> job not found
        raise HTTPException(status_code=404, detail="job not found")
    refreshed = await get_job(session, canonical_id)
    if refreshed is None:  # pragma: no cover - queue.cancel just SELECTed the row
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
