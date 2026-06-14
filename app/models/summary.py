"""Pydantic models for the on-disk ``summary-<kind>.json`` files (D-05).

Each ``Summary`` corresponds to one of the four template kinds
(``meeting``, ``investment``, ``concept``, ``quick_recap``) per SUM-01.
The ``SummaryKind`` literal is the only allowed discriminator and is
also the suffix in the filename (``data/jobs/<id>/summary-meeting.json``,
etc.).

The model is **lax for output / internal storage** (D-15). Phase 8
swaps the ``sections: dict[str, str]`` field for per-kind typed
schemas - for Phase 1 the dict is the minimal contract.

Plan 01-03 adds :func:`validate_summary_kind` so the path helper
(:func:`app.storage.fs.summary_path`) can reject path-traversal or
arbitrary strings BEFORE constructing a path into the per-job folder
(Codex MEDIUM strict path validation).
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

SummaryKind = Literal["meeting", "investment", "concept", "quick_recap"]
_ALLOWED_SUMMARY_KINDS: frozenset[str] = frozenset(get_args(SummaryKind))


def validate_summary_kind(kind: str) -> str:
    """Return ``kind`` iff it is one of the four :data:`SummaryKind` literals.

    Raises :class:`ValueError` for any other input (including path
    traversal-like strings such as ``"../../etc/passwd"``). The
    return value is the input unchanged on success, so the call
    site can use the return value directly to build the filename.
    """
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"invalid summary kind: {kind!r}")
    if kind not in _ALLOWED_SUMMARY_KINDS:
        raise ValueError(
            f"unsupported summary kind {kind!r}; allowed: "
            f"{sorted(_ALLOWED_SUMMARY_KINDS)}"
        )
    return kind


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


__all__ = ["Summary", "SummaryKind", "validate_summary_kind"]
