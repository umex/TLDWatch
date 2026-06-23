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

import os

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.api.idempotency import resolve_or_create
from app.jobs.cleanup import mark_stale
from app.jobs.ids import validate_job_id
from app.jobs.manifest import read_manifest, update_stage, write_manifest
from app.jobs.queue import cancel as queue_cancel
from app.jobs.queue import enqueue
from app.jobs.service import (
    LIST_LIMIT_CAP,
    LIST_LIMIT_DEFAULT,
    create_job,
    create_upload_job,
    get_job,
    list_jobs,
)
from app.models.job import (
    CreateJobRequest,
    JobResponse,
    StageUpdateRequest,
    StaleCheckRequest,
    StaleCheckResponse,
)
from app.models.manifest import JobManifest
from app.models.settings import Settings
from app.models.transcript import Transcript
from app.storage.fs import source_path, transcript_path, validate_source_ext
from app.storage.retry import retry_windows

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


@router.post(
    "/upload",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    request: Request,
    x_filename: str = Header(..., alias="X-Filename"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Stream the raw request body to ``data/jobs/<id>/source.<ext>`` (D-11, SC-1).

    Phase 5 streaming upload endpoint (the "other half" of Phase 4 D-04's
    generalized ``ingested`` check -- the browser cannot supply a
    server-side ``source_path``, so this route writes the file directly).

    Flow (per RESEARCH Pattern 1 + Pitfall 1/2/3):

    1. Validate the extension BEFORE writing (T-05-01 -- path traversal
       reject + allowlist enforced by :func:`validate_source_ext`).
    2. Resolve idempotency + create the job in ``status='uploading'`` via
       the existing :func:`resolve_or_create` flow, passing
       :func:`create_upload_job` as the factory (Phase 4 D-07 reuse).
    3. Stream the raw body via ``request.stream()`` (the true streaming
       path -- NOT the SpooledTemporaryFile-backed file-upload helper,
       per Pitfall 2 / FastAPI issue #3136) to ``.tmp_<source.<ext>>``
       with ``aiofiles``, ``fsync``, then atomic ``os.replace`` (T-05-02)
       wrapped in :func:`retry_windows` for transient Windows
       AV/Search Indexer locks.
    4. On any failure (client disconnect, disk error) the
       ``except BaseException`` branch ``os.unlink``s the temp file so
       no partial ``source.<ext>`` is left on disk.
    5. Patch ``manifest.source_path`` + ``source_type='local'`` directly
       (Pitfall 3 -- do NOT call ``update_stage("ingested")``; that sets
       ``status='ingesting'`` which blocks the widened ``enqueue`` clause).
    6. :func:`enqueue` flips ``status='queued'`` (Task 1 widened the
       clause to accept ``'uploading'``) and wakes the worker. The
       orchestrator's generalized ``ingested`` check sees the
       in-job-dir ``source.<ext>`` and skips the ingest stage.

    Returns 201 + :class:`JobResponse` for a new job, or 200 + the
    existing job on a duplicate ``Idempotency-Key`` (Phase 4 D-07).
    """
    # 1. Validate the extension BEFORE writing (path-traversal safe).
    try:
        ext = validate_source_ext(
            x_filename.rsplit(".", 1)[-1] if "." in x_filename else ""
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid filename/extension")

    # 2. Resolve idempotency + create the job in status='uploading'.
    try:
        response, status_code = await resolve_or_create(
            request,
            session,
            settings,
            lambda job_id=None: create_upload_job(session, settings, job_id=job_id),
        )
    except ValueError:
        # validate_idempotency_key rejected the header (T-05-05).
        # 422 BEFORE any DB write.
        raise HTTPException(status_code=422, detail="invalid Idempotency-Key")
    job_id = response.id

    # 3. Stream the raw body to source.<ext>.tmp (NOT buffered in memory).
    final = source_path(settings, job_id, ext)  # job_dir/source.<ext>
    tmp = final.parent / f".tmp_{final.name}"
    try:
        async with aiofiles.open(tmp, "wb") as f:
            async for chunk in request.stream():  # true streaming ~64KB chunks
                await f.write(chunk)
            await f.flush()
            os.fsync(f.fileno())
        # 4. Atomic rename -> source.<ext> (retry on Windows AV locks).
        retry_windows(os.replace, tmp, final)
    except BaseException:
        # Clean up the temp file on any failure (client disconnect, disk
        # error, etc.) so no partial source.<ext> is left on disk (T-05-02).
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

    # 5. Patch manifest.source_path + source_type='local' (Pitfall 3 --
    #    do NOT call update_stage("ingested") which would set
    #    status='ingesting' and block enqueue).
    manifest = await read_manifest(settings, job_id)
    manifest = manifest.model_copy(
        update={"source_path": str(final), "source_type": "local"}
    )
    await write_manifest(settings, manifest)

    # 6. Enqueue -> status='queued', wake worker. The widened enqueue
    #    clause (Task 1) accepts 'uploading' rows.
    await enqueue(job_id, session)

    # Refresh the response so it reflects the post-enqueue status ('queued').
    # The ``response`` object built by create_upload_job carries the
    # pre-enqueue 'uploading' status; the caller (FE) needs the final
    # 'queued' status. ``get_job`` re-reads the DB row after enqueue's
    # commit. On the duplicate-key path (200) the existing job is already
    # 'queued' so the refresh is a no-op.
    refreshed = await get_job(session, job_id)
    if refreshed is not None:
        response = refreshed

    return Response(
        content=response.model_dump_json(),
        media_type="application/json",
        status_code=status_code,
    )


@router.get(
    "/{job_id}/transcript",
    response_model=Transcript,
    responses={404: {"description": "transcript not found"}},
)
async def get_transcript(
    job_id: str,
    settings: Settings = Depends(get_settings),
) -> Transcript:
    """Return the parsed :class:`Transcript` for ``job_id`` (D-14).

    Serves the on-disk ``transcript.json`` (Phase 3 schema) so the FE
    detail view can render it. Returns:

    - 200 + the :class:`Transcript` JSON when ``transcript.json`` exists.
    - 404 ``{"detail": "transcript not found"}`` when the job has no
      transcript yet (still queued / transcribing -- the FE shows a
      "Transcribing..." state).
    - 400 ``{"detail": "invalid job id"}`` for a malformed id.
    """
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc

    path = transcript_path(settings, canonical_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="transcript not found")
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


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
