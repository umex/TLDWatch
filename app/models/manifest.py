from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import StageTimestamps


class JobManifest(BaseModel):
    """File-on-disk job manifest, written atomically by every stage mutator.

    The manifest is the rich "one read = full picture" snapshot of a job
    (D-05). It is always kept consistent with the per-job folder contents.
    Lax for output: deserialising existing files should never fail because
    of an unknown future field.

    Plan 01-03 adds ``diarization_enabled`` (default ``False`` - diarization
    is opt-in per D-11; the settings panel in Phase 7 flips it to True).
    The default keeps existing manifest JSON files from breaking (the
    field is missing, Pydantic fills in the default).
    """

    schema_version: int = 1
    job_id: str
    source_type: str | None = None
    source_path: str | None = None
    # Plan 05-04: the original dropped filename (display-only). None for
    # jobs created via POST /jobs (no upload). source_path still points at
    # the in-job-dir source.<ext> file (D-04 unchanged); this field is a
    # pure additive display addition. Default None keeps existing manifest
    # JSON files loadable (Pydantic fills the default -- same pattern as
    # ``diarization_enabled``).
    original_filename: str | None = None
    source_sha256: str | None = None
    duration_s: float | None = None
    language: str | None = None
    summary_kinds: list[str] = Field(default_factory=list)
    diarization_enabled: bool = False
    status: str = "queued"
    current_stage: str | None = None
    stage_timestamps: StageTimestamps
    error: str | None = None


__all__ = ["JobManifest"]
