"""Pydantic model for the on-disk ``diarization.json`` file (D-05, D-15).

The diarization stage runs in Phase 7 (when the user opts in via
``manifest.diarization_enabled``). For Phase 1 the model only ensures
the file is structurally a Diarization payload so the file-as-truth
resume rule can re-run any stage whose output is invalid.

The model is **lax for output / internal storage** (D-15): the
``segments`` field is typed as ``list[dict]`` because Phase 7 will
replace the dict with a typed :class:`DiarizationSegment` model;
keeping the field as ``list[dict]`` for Phase 1 means deserialising
existing files never fails on a field-shape mismatch.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Diarization(BaseModel):
    """The diarization output for a single job.

    Phase 7 replaces the ``list[dict]`` segments with a typed
    ``list[DiarizationSegment]``; for Phase 1 the dict is the minimal
    contract. The model is used by
    :func:`app.jobs.resume.parse_stage_file` (with ``model_cls=
    Diarization``) to validate ``diarization.json``: a file that
    fails this validation is treated as "stage not complete" so the
    resume rule re-runs the diarization stage.
    """

    schema_version: int = 1
    job_id: str
    segments: list[dict] = Field(default_factory=list)


__all__ = ["Diarization"]
