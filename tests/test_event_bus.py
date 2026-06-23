"""Tests for :mod:`app.jobs.progress` -- the in-process EventBus (D-08).

Three GREEN tests (Task 1a created the bus; this is the GREEN gate for
the bus specifically):

- ``test_subscribe_publish_roundtrip``: a subscribed queue receives
  every published event in order.
- ``test_drop_oldest_on_full``: when the queue is full, ``publish``
  drops the OLDEST event (``get_nowait`` then ``put_nowait``) so the
  newest events survive and the publisher never blocks (Pitfall 2 /
  T-04-bus mitigation).
- ``test_unsubscribe_cleans_up``: ``unsubscribe`` removes the queue and
  deletes the empty per-job list so ``has_subscribers`` flips to False.
"""

from __future__ import annotations

import asyncio

import pytest

from app.jobs.progress import EventBus


@pytest.mark.asyncio
async def test_subscribe_publish_roundtrip() -> None:
    """A subscribed queue receives every published event in order."""
    bus = EventBus()
    q = bus.subscribe("J-1")
    assert bus.has_subscribers("J-1") is True

    bus.publish("J-1", {"type": "stage_changed", "stage": "ingesting"})
    bus.publish("J-1", {"type": "progress", "chunks_done": 1, "chunks_total": 3})
    bus.publish("J-1", {"type": "done"})

    first = await asyncio.wait_for(q.get(), timeout=1.0)
    second = await asyncio.wait_for(q.get(), timeout=1.0)
    third = await asyncio.wait_for(q.get(), timeout=1.0)

    assert first["type"] == "stage_changed"
    assert second["chunks_done"] == 1
    assert third["type"] == "done"
    assert q.empty()


@pytest.mark.asyncio
async def test_drop_oldest_on_full() -> None:
    """On ``QueueFull``, ``publish`` drops the OLDEST event and keeps the newest.

    The queue is ``maxsize=32``; fill it exactly, then publish one more.
    The first event (the oldest) is evicted; the 32 newest survive and
    the 33rd (just published) is at the tail.
    """
    bus = EventBus()
    q = bus.subscribe("J-1")

    # Fill the queue to its max size (32).
    for i in range(32):
        bus.publish("J-1", {"type": "progress", "n": i})

    assert q.qsize() == 32

    # Publish one more -- the OLDEST (n=0) must be dropped to make room.
    bus.publish("J-1", {"type": "progress", "n": 999})
    assert q.qsize() == 32  # still full, but the head advanced

    # The oldest surviving event is now n=1 (n=0 was dropped).
    first = await asyncio.wait_for(q.get(), timeout=1.0)
    assert first["n"] == 1

    # The newest (n=999) is at the tail.
    last_n: int | None = None
    while not q.empty():
        last_n = (await asyncio.wait_for(q.get(), timeout=1.0))["n"]
    assert last_n == 999


@pytest.mark.asyncio
async def test_unsubscribe_cleans_up() -> None:
    """``unsubscribe`` removes the queue and drops the empty per-job list."""
    bus = EventBus()
    q = bus.subscribe("J-1")
    assert bus.has_subscribers("J-1") is True

    bus.unsubscribe("J-1", q)
    assert bus.has_subscribers("J-1") is False

    # Publishing after unsubscribe is a no-op (no crash, no delivery).
    bus.publish("J-1", {"type": "done"})
    assert q.empty()


@pytest.mark.asyncio
async def test_publish_to_no_subscribers_is_noop() -> None:
    """Publishing to a job with no subscribers does not crash."""
    bus = EventBus()
    bus.publish("J-unknown", {"type": "done"})
    assert bus.has_subscribers("J-unknown") is False


@pytest.mark.asyncio
async def test_multiple_subscribers_fan_out() -> None:
    """Multiple subscribers for the same job each receive every event."""
    bus = EventBus()
    q1 = bus.subscribe("J-1")
    q2 = bus.subscribe("J-1")

    bus.publish("J-1", {"type": "stage_changed", "stage": "transcribing"})

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1 == e2 == {"type": "stage_changed", "stage": "transcribing"}


# --- Plan 04-03 extensions: backpressure confirmation + isolation ------------


@pytest.mark.asyncio
async def test_drop_oldest_on_overflow() -> None:
    """Publishing 33 events to a maxsize=32 queue drops the OLDEST (not newest).

    Confirms 04-01's EventBus backpressure (T-04-04 mitigation): the
    subscriber misses the oldest event but keeps receiving the newest
    ones -- the right trade-off for a progress stream.
    """
    bus = EventBus()
    q = bus.subscribe("J-overflow")

    for i in range(33):
        bus.publish("J-overflow", {"type": "progress", "n": i})

    # The queue is capped at 32; the OLDEST (n=0) was dropped, so the
    # head is now n=1 and the tail is n=32.
    assert q.qsize() == 32
    first = await asyncio.wait_for(q.get(), timeout=1.0)
    assert first["n"] == 1  # n=0 was dropped (drop-oldest, NOT drop-newest)

    last_n: int | None = None
    while not q.empty():
        last_n = (await asyncio.wait_for(q.get(), timeout=1.0))["n"]
    assert last_n == 32  # the newest survived


@pytest.mark.asyncio
async def test_multiple_subscribers_isolated() -> None:
    """Two subscribers get their OWN queues; one event is delivered to both.

    The subscribers are independent: dropping / draining one queue does not
    affect the other. Confirms the EventBus keeps per-subscriber state.
    """
    bus = EventBus()
    q1 = bus.subscribe("J-iso")
    q2 = bus.subscribe("J-iso")

    bus.publish("J-iso", {"type": "progress", "n": 1})

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1 == e2 == {"type": "progress", "n": 1}
    # Both queues are now empty independently.
    assert q1.empty()
    assert q2.empty()