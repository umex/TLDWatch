"""Lifecycle cleanup helpers: cancel_job, mark_failed, is_stale, mark_stale.

Ordering rules (Codex HIGH #8 / D-13):

- ``cancel_job`` is DB-first, then rmtree. The DB UPDATE is
  committed BEFORE the folder is deleted. If the rmtree fails
  (Windows file lock, antivirus), the row is still marked
  cancelled and a future call can retry the folder cleanup -
  the opposite order (rmtree first, DB second) can leak a
  cancelled row with no folder to inspect.
- ``mark_failed`` keeps the folder so the operator / a future
  retry can inspect the partial outputs.
- ``mark_stale`` is a soft-failure: a 0-second threshold marks
  every touched job as failed with ``error="stalled"``; a huge
  threshold is a no-op. Used by ``POST /jobs/{id}/stale-check``
  for admin / test flows.
"""

from __future__ import annotations

import logging
import shutil
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.manifest import manifest_mtime
from app.models.settings import Settings
from app.storage.fs import job_dir, last_stage_mtime
from app.storage.retry import retry_windows
from app.util.time import utcnow_iso

_log = logging.getLogger(__name__)


async def cancel_job(session: AsyncSession, settings: Settings, job_id: str) -> bool:
    """Mark ``job_id`` cancelled and remove its per-job folder.

    Returns ``True`` if a row was marked cancelled, ``False`` if no
    such job exists (caller maps to 404).

    Ordering: DB UPDATE first, commit, then ``shutil.rmtree`` the
    folder. The rmtree is wrapped in :func:`retry_windows` to
    survive transient Windows file locks; on exhaustion the
    failure is logged at WARNING but the function still returns
    ``True`` - the row is already cancelled and a future call can
    retry the folder cleanup.
    """
    # DB-first.
    result = await session.execute(
        text(
            "UPDATE jobs SET status = 'cancelled', updated_at = :now "
            "WHERE id = :id"
        ),
        {"now": utcnow_iso(), "id": job_id},
    )
    await session.commit()
    rowcount = result.rowcount if result is not None else 0
    if not rowcount:
        return False

    # Then rmtree, retried. We use ``ignore_errors=True`` so a
    # permission error that exhausts the retry budget is logged
    # and swallowed - the row is already cancelled and the
    # operator / next call can clean the folder up.
    folder = job_dir(settings, job_id)
    try:
        retry_windows(
            shutil.rmtree,
            str(folder),
            attempts=3,
            backoff_s=0.2,
            retriable_exceptions=(PermissionError, OSError),
            ignore_errors=True,
        )
    except Exception:  # pragma: no cover - defensive logging only
        _log.exception("unexpected error in cancel_job rmtree for %s", job_id)
    return True


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> bool:
    """Mark ``job_id`` failed with ``error``; keeps the folder intact.

    Returns ``True`` if a row was updated, ``False`` if no such job
    exists.
    """
    result = await session.execute(
        text(
            "UPDATE jobs SET status = 'failed', error = :error, "
            "updated_at = :now WHERE id = :id"
        ),
        {"error": error, "now": utcnow_iso(), "id": job_id},
    )
    await session.commit()
    return bool(result.rowcount if result is not None else 0)


def is_stale(settings: Settings, job_id: str, threshold_s: int = 600) -> bool:
    """Return True iff the last activity on the job is older than ``threshold_s``.

    Looks at the max mtime across stage files; falls back to the
    manifest mtime; returns ``False`` if neither is available (no
    activity to be stale about).
    """
    mtime = last_stage_mtime(settings, job_id)
    if mtime is None:
        mtime = manifest_mtime(settings, job_id)
    if mtime is None:
        return False
    return (time.time() - mtime) > threshold_s


async def mark_stale(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    threshold_s: int = 600,
) -> tuple[bool, bool]:
    """Mark ``job_id`` failed with ``error='stalled'`` if it is stale.

    Returns ``(stale, marked)``:

    - ``stale`` is the result of :func:`is_stale`.
    - ``marked`` is True iff the row was actually updated.
    """
    stale = is_stale(settings, job_id, threshold_s=threshold_s)
    if not stale:
        return False, False
    marked = await mark_failed(session, job_id, "stalled")
    return True, marked


__all__ = ["cancel_job", "is_stale", "mark_failed", "mark_stale"]
