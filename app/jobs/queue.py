"""SQLite-backed FIFO queue + single-worker loop + watchdog (plan 04-02).

The queue is the persistent spine that survives backend restarts (SC-2).
Queued jobs live in the ``jobs`` table; the worker drains them strictly
serially (D-10 -- one ``run_job`` at a time, no ``asyncio.gather`` of
multiple jobs). The implementation closes three operational correctness
gaps surfaced by the Codex + Ollama reviews:

- Fix 1 (hybrid Event + poll wakeup): the worker awaits
  ``asyncio.wait_for(_work_signal.wait(), timeout=2.0)``. The 2s poll
  timeout self-heals a missed signal -- if ``enqueue`` fires the signal
  BEFORE the worker reached ``wait()``, the signal is lost but the poll
  timeout re-polls the queue and picks the job up. Without this a missed
  signal would stall the queue indefinitely.
- Fix 6 (atomic claim): ``pull_next`` claims a queued job via a
  conditional ``UPDATE jobs SET status='starting' WHERE id=:id AND
  status='queued'`` and checks ``result.rowcount``. Only the worker whose
  UPDATE changed exactly one row proceeds; the other gets
  ``rowcount == 0`` and returns ``None``. This prevents two workers from
  running the same job (T-04-10).
- Codex MEDIUM (status-aware enqueue): ``enqueue`` only re-queues rows in
  a valid pre-active state (``status IN ('created','queued')``); rows in
  terminal or active states are untouched so a stale enqueue cannot
  resurrect a finished / in-flight job (T-04-12).

The watchdog (Task 3) and the cooperative cancel (Task 3) live in this
module too -- they share the ``_work_signal`` and the ``Settings.run_worker``
gate.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.orchestrator import run_job
from app.models.settings import Settings
from app.util.time import utcnow_iso

_log = logging.getLogger(__name__)

# Module-level wake signal for the worker loop. ``enqueue`` sets it after a
# commit; the worker awaits it (with a 2s poll timeout -- Fix 1) when
# ``pull_next`` returns None. A single module-level Event is safe because
# there is exactly one worker task (D-10 strict serial).
_work_signal: asyncio.Event = asyncio.Event()


async def enqueue(job_id: str, session) -> None:
    """Mark ``job_id`` as queued so the worker picks it up (status-aware).

    Codex MEDIUM (T-04-12): the conditional UPDATE only touches rows in a
    valid pre-active state (``status IN ('created','queued')``). A row in
    any terminal (``done`` / ``failed`` / ``cancelled``) or active
    (``starting`` / ``ingesting`` / ``transcribing``) state is left
    untouched so a stale enqueue cannot resurrect a finished or in-flight
    job.

    After the commit the worker is woken via ``_work_signal.set()``. The
    hybrid wakeup (Fix 1) means a missed signal is self-healed by the 2s
    poll timeout in ``run_worker``.
    """
    result = await session.execute(
        text(
            "UPDATE jobs SET status = 'queued', updated_at = :now "
            "WHERE id = :id AND status IN ('created','queued')"
        ),
        {"now": utcnow_iso(), "id": job_id},
    )
    await session.commit()
    if result.rowcount:
        _log.info("enqueue: job %s queued", job_id)
    else:
        _log.info(
            "enqueue: job %s not re-queued (terminal or active state)", job_id
        )
    _work_signal.set()


async def pull_next(session) -> str | None:
    """Atomically claim the next queued job in FIFO order (Fix 6).

    FIFO order is ``ORDER BY created_at`` (D-10). The claim is a
    conditional ``UPDATE jobs SET status='starting' WHERE id=:id AND
    status='queued'``; only the worker whose UPDATE changes exactly one
    row proceeds. If ``rowcount == 0`` another worker (or a cancel)
    changed the status between the SELECT and the UPDATE -- return None so
    the loop re-polls. The ``'starting'`` status is a transient claim
    state; 04-01's ``run_job`` immediately transitions it via
    :func:`update_stage` to the real ``ingesting`` / ``transcribing``
    stage.

    Returns the claimed job id, or ``None`` if no queued job is available
    (or the claim lost the race).
    """
    result = await session.execute(
        text(
            "SELECT id FROM jobs WHERE status = 'queued' "
            "ORDER BY created_at LIMIT 1"
        )
    )
    row = result.fetchone()
    if row is None:
        return None
    candidate_id = row[0]
    claim = await session.execute(
        text(
            "UPDATE jobs SET status = 'starting', updated_at = :now "
            "WHERE id = :id AND status = 'queued'"
        ),
        {"now": utcnow_iso(), "id": candidate_id},
    )
    await session.commit()
    if claim.rowcount == 1:
        return candidate_id
    # Lost the race (another worker claimed it or a cancel flipped it).
    # Return None so the loop re-polls; the queue is never stalled.
    return None


async def run_worker(
    settings: Settings,
    session_factory: async_sessionmaker,
    bus=None,
) -> None:
    """Drain the queue strictly serially (D-10) with hybrid wakeup (Fix 1).

    Single asyncio task; NO ``asyncio.gather`` of multiple jobs. Pulls the
    next queued job via :func:`pull_next` (atomic claim -- Fix 6) and drives
    it through :func:`app.jobs.orchestrator.run_job`. When no job is
    available, awaits ``_work_signal`` with a 2s poll timeout so a missed
    signal self-heals (Fix 1). ``run_job`` re-raises non-cancel exceptions
    after :func:`mark_failed`; the worker catches them so one failed job
    does not kill the loop (Rule 2 -- missing error handling would stall
    the whole queue on the first failure).

    Guarded by ``settings.run_worker`` (04-01 added the field): tests set it
    ``False`` and drive the worker manually; the lifespan (Task 4)
    auto-starts it when ``True``.
    """
    if not settings.run_worker:
        return
    _log.info("run_worker: starting (worker=1 strict serial, D-10)")
    while True:
        try:
            async with session_factory() as session:
                job_id = await pull_next(session)
        except Exception:  # pragma: no cover - defensive loop guard
            _log.exception("run_worker: pull_next failed; retrying after 1s")
            await asyncio.sleep(1.0)
            continue

        if job_id is None:
            # Fix 1: hybrid Event + poll wakeup. The 2s timeout self-heals a
            # missed signal (enqueue fired before the worker awaited).
            try:
                await asyncio.wait_for(_work_signal.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            _work_signal.clear()
            continue

        try:
            await run_job(settings, session_factory, job_id, bus=bus)
        except Exception as exc:  # noqa: BLE001
            # run_job already mark_failed + bus.publish("failed"); the
            # re-raise is so the worker can log / surface it. Do NOT kill
            # the loop -- one failed job must not stall the queue.
            _log.warning("run_worker: job %s failed: %s", job_id, exc)
        # Loop: pull the next queued job.