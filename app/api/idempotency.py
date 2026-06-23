"""Idempotency-Key handling for ``POST /jobs`` -- plan 04-03.

Three functions (SC-5, D-07, Fix 7):

1. ``validate_idempotency_key`` -- pure header validation (T-04-01).
   Caps length at 128 and restricts the charset to ``[A-Za-z0-9_-]`` so a
   malicious / oversized header cannot reach the DB. Returns ``None`` when
   no key was sent (the caller proceeds as today). Raises ``ValueError``
   on invalid input; the route layer maps that to HTTP 422 BEFORE any DB
   write (Codex MEDIUM -- exact exception path).

2. ``resolve_or_create`` -- the atomic key-first reservation (Fix 7 --
   Codex HIGH). The idempotency_key is INSERTed BEFORE ``create_job``
   runs; on ``IntegrityError`` (T-04-03 race -- another request with the
   same key landed first) the loser re-reads the existing ``job_id`` and
   returns the existing job with 200, and the winner creates the job
   under the reserved id. This ordering ensures a race NEVER leaves an
   orphan queued job: the key is reserved first; if a collision happens,
   the loser rolls back and returns the existing job; the winner creates
   the job under the reserved id. Expired-key DELETE + new-key INSERT
   happen in the SAME transaction (Codex MEDIUM -- TTL transactional).

3. ``run_janitor`` -- periodic cleanup of expired idempotency_keys rows
   (Codex LOW). DELETEs rows older than ``idempotency_ttl_hours`` so the
   table does not grow unboundedly. Wired as an asyncio task in the
   lifespan (started guarded by ``settings.run_worker``, cancelled on
   teardown alongside the worker + watchdog).

Strict-in / lax-out (D-15): the Idempotency-Key is a raw HTTP header
(strict-in validation via the regex). ``JobResponse`` output is lax-out
(already the case). No Pydantic model for the header -- it is a raw
``str`` from ``request.headers``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.service import create_job, get_job
from app.models.job import JobResponse
from app.models.settings import Settings
from app.util.time import utcnow_iso

_log = logging.getLogger(__name__)

# T-04-01: allowlist charset + 128-char cap. The regex is anchored so a
# key with a space, bang, or any non-token char is rejected. The 128 cap
# is checked separately so an oversized key is rejected before the regex
# (clearer error + cheaper).
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_KEY_LEN = 128


def validate_idempotency_key(key: str | None) -> str | None:
    """Validate the ``Idempotency-Key`` header (T-04-01).

    Returns ``None`` when ``key is None`` (no idempotency requested -- the
    caller proceeds as today, creating a new job). Returns the key
    unchanged when valid. Raises ``ValueError`` when the key is empty,
    longer than 128 chars, or contains characters outside
    ``[A-Za-z0-9_-]``. The route layer catches ``ValueError`` and returns
    HTTP 422 BEFORE any DB write (Codex MEDIUM).

    Pure function (no DB access) -- unit-testable directly.
    """
    if key is None:
        return None
    if not isinstance(key, str):
        raise ValueError("Idempotency-Key must be a string")
    if len(key) > _MAX_KEY_LEN:
        raise ValueError(
            f"Idempotency-Key too long: {len(key)} > {_MAX_KEY_LEN}"
        )
    if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise ValueError(
            "Idempotency-Key must match [A-Za-z0-9_-]{1,128}"
        )
    return key


async def resolve_or_create(
    request,
    session: AsyncSession,
    settings: Settings,
    create_job_fn,
) -> tuple[JobResponse, int]:
    """Resolve an idempotent POST /jobs to an existing job, or create a new one.

    Returns ``(JobResponse, status_code)`` where ``status_code`` is:

    - 201 for a newly-created job (first call with this key, or no key).
    - 200 for a duplicate key that resolves to an existing job.

    Raises ``ValueError`` when the ``Idempotency-Key`` header is invalid;
    the route layer maps that to HTTP 422 BEFORE any DB write (Codex
    MEDIUM).

    Fix 7 (Codex HIGH -- atomic key-first reservation):

    1. Read + validate the header. ``None`` -> no idempotency -> create
       a new job as today (201).
    2. If a key is present:

       a. DELETE expired rows with this key FIRST (Codex MEDIUM -- TTL
          delete + create transactional) so an expired key is reaped in
          the SAME transaction as the new reservation.
       b. INSERT the idempotency_keys row with a freshly-generated
          ``pending_job_id`` BEFORE ``create_job`` runs. This RESERVES
          the key. If the INSERT raises ``IntegrityError`` (T-04-03 race
          -- another request with the same key landed first): catch,
          SELECT the existing ``job_id``, fetch the existing job,
          rollback the pending reservation, return ``(existing, 200)``.
       c. If the INSERT succeeded (key reserved): commit the
          reservation. Then call ``create_job_fn(job_id=pending_job_id)``.
          If ``create_job`` raises: DELETE the idempotency_keys row (so
          the key is not orphaned) and re-raise. If ``create_job``
          succeeds: commit. Return ``(response, 201)``.

    This ordering ensures a race never leaves an orphan queued job: the
    key is reserved FIRST; if a collision happens, the loser rolls back
    and returns the existing job; the winner creates the job under the
    reserved id (Fix 7 -- no orphan duplicate on race).
    """
    raw_key = request.headers.get("Idempotency-Key")
    # validate_idempotency_key raises ValueError on invalid input; the
    # route layer catches that and returns 422. ``None`` passes through.
    key = validate_idempotency_key(raw_key)

    if key is None:
        # No idempotency requested -- behave as today.
        response = await create_job_fn(job_id=None)
        return response, 201

    # --- Atomic key-first reservation (Fix 7) ---
    import uuid

    from app.jobs.ids import new_job_id

    pending_job_id = new_job_id()
    now = utcnow_iso()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=settings.idempotency_ttl_hours)
    ).isoformat()

    # (a) Reap expired rows with this key in the SAME transaction (Codex
    # MEDIUM -- TTL delete + create transactional).
    await session.execute(
        text(
            "DELETE FROM idempotency_keys "
            "WHERE idempotency_key = :key AND created_at < :cutoff"
        ),
        {"key": key, "cutoff": cutoff},
    )

    # (b) Reserve the key with the pending job_id.
    try:
        await session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(idempotency_key, job_id, created_at) "
                "VALUES (:key, :job_id, :now)"
            ),
            {"key": key, "job_id": pending_job_id, "now": now},
        )
        await session.commit()
    except (SAIntegrityError, Exception) as exc:
        # Distinguish IntegrityError (PRIMARY KEY collision -- race) from
        # a real DB error. The broad ``Exception`` catch is defensive;
        # only IntegrityError is the expected race path. Anything else
        # re-raises so the caller surfaces a 5xx (do NOT mask a real DB
        # failure as a duplicate).
        if not _is_integrity_error(exc):
            raise
        # Race: another request won the key. Rollback the pending
        # reservation (nothing to roll back -- the INSERT failed -- but
        # rollback clears the session state) and re-read the existing
        # job_id.
        await session.rollback()
        result = await session.execute(
            text(
                "SELECT job_id FROM idempotency_keys "
                "WHERE idempotency_key = :key"
            ),
            {"key": key},
        )
        row = result.fetchone()
        if row is None:
            # Edge case: the winning row was deleted between the
            # collision and the SELECT (e.g. janitor). Fall through to
            # create a new job with no key reservation (the caller
            # gets a 201; the NEXT duplicate call will reserve cleanly).
            _log.warning(
                "idempotency race for %s: key gone after collision; "
                "creating a new job",
                key,
            )
            response = await create_job_fn(job_id=None)
            return response, 201
        existing_job_id = row[0]
        existing_job = await get_job(session, existing_job_id)
        if existing_job is None:
            # Orphan key (the job row was deleted but the key row
            # remained). Clean up and create a new job.
            _log.warning(
                "idempotency race for %s: existing job %s gone; "
                "cleaning up orphan key and creating a new job",
                key,
                existing_job_id,
            )
            await session.execute(
                text("DELETE FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key},
            )
            await session.commit()
            response = await create_job_fn(job_id=None)
            return response, 201
        return existing_job, 200

    # (c) Key reserved -- create the job under the reserved id. If
    # create_job fails, DELETE the orphan key reservation so a retry
    # with the same key does not resolve to a non-existent job.
    try:
        response = await create_job_fn(job_id=pending_job_id)
        return response, 201
    except Exception:
        try:
            await session.execute(
                text("DELETE FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key},
            )
            await session.commit()
        except Exception:  # pragma: no cover - defensive logging only
            _log.exception(
                "idempotency cleanup failed for %s after create_job error",
                key,
            )
        raise


def _is_integrity_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a PRIMARY KEY / UNIQUE collision.

    Handles both SQLAlchemy's wrapped ``IntegrityError`` and the raw
    ``sqlite3.IntegrityError`` (the path a monkeypatched INSERT might
    raise in the race test).
    """
    if isinstance(exc, SAIntegrityError):
        return True
    try:
        import sqlite3

        if isinstance(exc, sqlite3.IntegrityError):
            return True
    except Exception:  # pragma: no cover - sqlite3 always importable
        pass
    return False


async def run_janitor(
    session_factory: async_sessionmaker,
    settings: Settings,
) -> int:
    """Delete idempotency_keys rows older than ``idempotency_ttl_hours`` (Codex LOW).

    Returns the deleted count. Called periodically by the lifespan
    janitor task (started guarded by ``settings.run_worker``, cancelled
    on teardown). The TTL delete is a single statement; the
    ``resolve_or_create`` flow does its own transactional expired-key
    reaping at insert time (Codex MEDIUM -- TTL transactional), so the
    janitor only needs to sweep keys whose jobs completed (no
    subsequent insert will reap them).
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=settings.idempotency_ttl_hours)
    ).isoformat()
    async with session_factory() as session:
        result = await session.execute(
            text("DELETE FROM idempotency_keys WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await session.commit()
        return result.rowcount or 0


__all__ = ["validate_idempotency_key", "resolve_or_create", "run_janitor"]