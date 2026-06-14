"""Pydantic models for the on-disk ``summary-<kind>.json`` files (D-05).

Each ``Summary`` corresponds to one of the four template kinds
(``meeting``, ``investment``, ``concept``, ``quick_recap``) per SUM-01.
The ``SummaryKind`` literal is the only allowed discriminator and is
also the suffix in the filename (``data/jobs/<id>/summary-meeting.json``,
etc.).

The model is **lax for output / internal storage** (D-15). Phase 8
swaps the ``sections: dict[str, str]`` field for per-kind typed
schemas - for Phase 1 the dict is the minimal contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SummaryKind = Literal["meeting", "investment", "concept", "quick_recap"]


class Summary(BaseModel):
    """The full output of one summary template for a single job.

    ``sections`` is keyed by section name (e.g. ``"action_items"``,
    ``"key_takeaways"``) and the value is the rendered text. The exact
    section names are template-specific; downstream code that needs
    the shape should branch on ``kind``.
    """

    schema_version: int = 1
    job_id: str
    kind: SummaryKind
    created_at: str  # ISO 8601 UTC with ``+00:00`` suffix (app.util.time.utcnow_iso)
    sections: dict[str, str] = Field(default_factory=dict)
    model: str | None = None


__all__ = ["Summary", "SummaryKind"]
