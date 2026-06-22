"""In-process asyncio EventBus (pub/sub + drop-oldest backpressure).

Phase 4 plan 04-01 (D-08): the orchestrator publishes per-job progress
events (``stage_changed``, ``progress``, ``done``, ``failed``,
``cancelled``); the WS handler (plan 04-03) subscribes a per-job
``asyncio.Queue`` and streams events to the connected client. The bus
is a thin registry of subscriber queues keyed by ``job_id``.

Design (RESEARCH § Pattern 1):

- ``subscribe(job_id)`` returns a fresh ``asyncio.Queue(maxsize=32)`` and
  appends it to the per-job subscriber list. A job may have multiple
  subscribers (multiple WS clients); ``publish`` fans out to all.
- ``publish`` is SYNC (it is called from
  ``loop.call_soon_threadsafe(bus.publish, ...)`` -- never awaited).
  On ``asyncio.QueueFull`` it drops the OLDEST event
  (``get_nowait`` then ``put_nowait``) so the publisher never blocks
  and the subscriber sees the newest events (drop-oldest backpressure,
  Pitfall 2). This is the T-04-bus mitigation.
- ``unsubscribe(job_id, q)`` removes the queue and deletes the per-job
  list when empty so the registry does not grow unboundedly.
- ``has_subscribers(job_id)`` is a test hook.

Thread-safety: the bus is touched from the asyncio loop ONLY (publish
is marshalled via ``call_soon_threadsafe``), so no lock is needed. A
``call_soon_threadsafe`` schedule guarantees the publish runs on the
loop thread, and ``asyncio.Queue`` is not safe to touch from off-loop
-- the ``call_soon_threadsafe`` indirection is what keeps this safe
(T-04-thread mitigation).
"""

from __future__ import annotations

import asyncio


class EventBus:
    """In-process pub/sub bus keyed by ``job_id`` (D-08)."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, job_id: str) -> "asyncio.Queue":
        """Create a ``maxsize=32`` subscriber queue for ``job_id`` and return it."""
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: "asyncio.Queue") -> None:
        """Remove ``q`` from ``job_id``'s subscribers; clean up the empty list."""
        subs = self._subs.get(job_id)
        if subs is None:
            return
        try:
            subs.remove(q)
        except ValueError:
            pass
        if not subs:
            self._subs.pop(job_id, None)

    def publish(self, job_id: str, event: dict) -> None:
        """Fan-out ``event`` to every subscriber queue for ``job_id`` (drop-oldest).

        SYNC (never awaited). Called via
        ``loop.call_soon_threadsafe(bus.publish, ...)`` from the
        orchestrator's worker-thread progress callback. On
        ``asyncio.QueueFull`` the OLDEST event is dropped
        (``get_nowait`` then ``put_nowait``) so the publisher never
        blocks and the subscriber keeps receiving the newest events
        (Pitfall 2). Any race-condition exception (e.g. a queue that
        was concurrently unsubscribed) is swallowed so a torn-down
        subscriber can never crash the publisher.
        """
        for q in self._subs.get(job_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop-oldest: evict the head then retry the put. The
                # subscriber misses the oldest event but keeps receiving
                # the newest ones -- the right trade-off for a
                # progress stream (a stale percent is worse than a
                # dropped old one).
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:  # pragma: no cover - racing subscriber
                    pass
            except Exception:  # pragma: no cover - defensive logging only
                # A concurrently torn-down queue or a closed loop should
                # never crash the publisher.
                pass

    def has_subscribers(self, job_id: str) -> bool:
        """Return True iff ``job_id`` has at least one live subscriber (test hook)."""
        return bool(self._subs.get(job_id))


__all__ = ["EventBus"]