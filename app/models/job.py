from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.common import StageTimestamps

JobStatus = Literal[
    "queued",
    "ingesting",
    "transcribing",
    "diarizing",
    "summarizing",
    "done",
    "failed",
    "cancelled",
]


class CreateJobRequest(BaseModel):
    """Payload for ``POST /jobs``.

    Strict input: any extra keys or wrong types are rejected at the API
    boundary. This catches front-end bugs early (PITFALLS pitfall 7).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    source_type: str | None = None
    source_path: str | None = None


class JobResponse(BaseModel):
    """Response payload for job endpoints.

    Strict output for the API boundary; the ``id`` is a UUIDv4 string and
    ``created_at`` is a timezone-aware UTC ``datetime`` (the
    ``+00:00`` offset is preserved on the wire as a real suffix, not
    the ``Z`` shorthand, so the timestamp is unambiguously parseable
    by strict ISO 8601 consumers).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    status: JobStatus
    created_at: datetime
    source_type: str | None = None
    current_stage: str | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        # Pydantic v2 defaults to the ``Z`` shorthand for UTC; we
        # emit the full ``+00:00`` offset so consumers using strict
        # ISO 8601 parsers round-trip cleanly.
        return value.isoformat()


# Re-export the timestamp container for convenience to downstream modules
# that need to construct manifests without importing the common module
# directly. Avoids a circular import through ``app.jobs.manifest``.
__all__ = ["CreateJobRequest", "JobResponse", "JobStatus", "StageTimestamps", "Field"]
