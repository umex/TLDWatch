from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.common import StageTimestamps

JobStatus = Literal[
    "queued",
    "starting",
    "ingesting",
    "transcribing",
    "diarizing",
    "summarizing",
    "done",
    "failed",
    "cancelled",
]

# StageName literal is duplicated here (instead of imported from
# app.jobs.resume) to avoid a circular import: app.jobs.resume
# imports from app.models.manifest which is sibling of this module.
StageNameLiteral = Literal[
    "ingested", "transcribed", "diarized", "summarized", "done"
]


class CreateJobRequest(BaseModel):
    """Payload for ``POST /jobs``.

    Strict input: any extra keys or wrong types are rejected at the API
    boundary. This catches front-end bugs early (PITFALLS pitfall 7).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    source_type: str | None = None
    source_path: str | None = None


class ManifestPatch(BaseModel):
    """Allowlisted, strict patch for the on-disk manifest.

    The plan truth statement (Codex HIGH #7): the patch ONLY forwards
    the user-mutable fields. The protected fields
    (``current_stage``, ``job_id``, ``schema_version``,
    ``stage_timestamps``, ``status``, ``error``) are owned by the
    helper that applies the patch (:func:`app.jobs.manifest.update_stage`)
    and CANNOT be set via this model.

    - ``strict=True`` rejects wrong types (``source_type: 123`` -> 422).
    - ``extra="forbid"`` rejects unknown keys (``unknown_field: x`` -> 422)
      and also catches the protected fields (they are not on this
      model, so they are extras).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    source_type: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    duration_s: float | None = None
    language: str | None = None
    summary_kinds: list[str] | None = None


class StageUpdateRequest(BaseModel):
    """Payload for ``POST /jobs/{id}/stage``.

    Strict input; ``stage`` is the new value for ``manifest.current_stage``,
    and ``manifest_patch`` (optional) carries the user-mutable fields the
    caller wants to change at the same time.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    stage: StageNameLiteral
    manifest_patch: ManifestPatch | None = None


class StaleCheckRequest(BaseModel):
    """Payload for ``POST /jobs/{id}/stale-check``."""

    model_config = ConfigDict(strict=True, extra="forbid")

    threshold_s: int = 600


class StaleCheckResponse(BaseModel):
    """Response for ``POST /jobs/{id}/stale-check``."""

    stale: bool
    marked: bool


class JobResponse(BaseModel):
    """Response payload for job endpoints.

    Strict output for the API boundary; the ``id`` is a UUIDv4 string and
    ``created_at`` is a timezone-aware UTC ``datetime`` (the
    ``+00:00`` offset is preserved on the wire as a real suffix, not
    the ``Z`` shorthand, so the timestamp is unambiguously parseable
    by strict ISO 8601 consumers).

    Fields added in Plan 01-02 (``source_sha256``, ``duration_s``,
    ``language``, ``summary_kinds``, ``updated_at``, ``error``) are
    all optional and default to None / empty list so existing code
    paths and tests that construct a minimal response keep working.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    status: JobStatus
    created_at: datetime
    source_type: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    current_stage: str | None = None
    duration_s: float | None = None
    language: str | None = None
    summary_kinds: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    error: str | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        # Pydantic v2 defaults to the ``Z`` shorthand for UTC; we
        # emit the full ``+00:00`` offset so consumers using strict
        # ISO 8601 parsers round-trip cleanly.
        return value.isoformat()

    @field_serializer("updated_at")
    def _serialize_updated_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()


# Re-export the timestamp container for convenience to downstream modules
# that need to construct manifests without importing the common module
# directly. Avoids a circular import through ``app.jobs.manifest``.
__all__ = [
    "CreateJobRequest",
    "JobResponse",
    "JobStatus",
    "ManifestPatch",
    "StageNameLiteral",
    "StageTimestamps",
    "StageUpdateRequest",
    "StaleCheckRequest",
    "StaleCheckResponse",
    "Field",
]


def _row_to_response(row: Any) -> JobResponse:
    """Build a :class:`JobResponse` from a SQLAlchemy row.

    Handles the JSON-encoded ``summary_kinds_json`` column by
    decoding it to ``list[str]`` (or ``[]`` if the column is NULL
    / empty). Other NULL columns are mapped to ``None`` (or
    ``[]`` for ``summary_kinds``).
    """
    raw_kinds = row.summary_kinds_json
    if raw_kinds:
        kinds = json.loads(raw_kinds)
    else:
        kinds = []
    return JobResponse(
        id=row.id,
        status=row.status,
        created_at=datetime.fromisoformat(row.created_at),
        source_type=row.source_type,
        source_path=row.source_path,
        source_sha256=row.source_sha256,
        current_stage=row.current_stage,
        duration_s=row.duration_s,
        language=row.language,
        summary_kinds=kinds,
        updated_at=datetime.fromisoformat(row.updated_at)
        if row.updated_at
        else None,
        error=row.error,
    )
