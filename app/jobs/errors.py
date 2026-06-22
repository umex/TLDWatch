"""Shared job exception types (Fix 5).

This is a NEUTRAL module: it imports NOTHING from the orchestrator or
the STT layer. :mod:`app.models.stt.chunker` imports
:class:`JobCancelled` from here (a HORIZONTAL import) so the STT layer
never imports upward into :mod:`app.jobs.orchestrator` (Fix 5 — the
upward import created a cycle / a layering violation the Codex review
flagged). :mod:`app.jobs.orchestrator` re-exports :class:`JobCancelled`
for convenience so existing call sites keep working, but the SOURCE OF
TRUTH lives here.

Single-exception module: the only symbol is :class:`JobCancelled`.
Keep it that way — adding orchestration concerns here would re-create
the layering problem this module exists to solve.
"""

from __future__ import annotations


class JobCancelled(Exception):
    """Raised by the chunker when ``cancel_flag`` is set at a chunk boundary (D-06).

    Carries the ``job_id`` so the orchestrator's exception handler can
    route the cancel to the right :func:`app.jobs.cleanup.cancel_job`
    call without inspecting the traceback. The chunker raises this from
    the worker thread; the orchestrator catches it on the asyncio side
    via the awaited :func:`loop.run_in_executor` future.
    """

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} cancelled")
        self.job_id = job_id


__all__ = ["JobCancelled"]