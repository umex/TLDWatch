from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import StageTimestamps


class JobManifest(BaseModel):
    """File-on-disk job manifest, written atomically by every stage mutator.

    The manifest is the rich "one read = full picture" snapshot of a job
    (D-05). It is always kept consistent with the per-job folder contents.
    Lax for output: deserialising existing files should never fail because
    of an unknown future field.
    """

    schema_version: int = 1
    job_id: str
    source_type: str | None = None
    source_path: str | None = None
    source_sha256: str | None = None
    duration_s: float | None = None
    language: str | None = None
    summary_kinds: list[str] = Field(default_factory=list)
    status: str = "queued"
    current_stage: str | None = None
    stage_timestamps: StageTimestamps
    error: str | None = None


__all__ = ["JobManifest"]
