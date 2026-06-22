"""Resume rule (D-12): given a job's manifest, decide the next stage to run.

The rule is file-as-truth: the resume walker looks at the actual files
in the per-job folder rather than at the DB row or the manifest's
``current_stage`` field. The DB row is a projection (D-03); the
manifest's ``current_stage`` is the last *successful* write to the
manifest. The files on disk are the source of truth for "did this
stage actually run".

Special cases:

- ``diarized`` is OPTIONAL - skipped if ``manifest.diarization_enabled``
  is ``False`` (Phase 1 default; Phase 7 flips to True when the user
  opts in).
- ``summarized`` is OPTIONAL - skipped if ``manifest.summary_kinds``
  is empty (the user did not request any summary template). When
  present, ``summarized`` is complete iff a ``summary-<kind>.json``
  file exists for EVERY kind in ``summary_kinds``.
- ``done`` is a DERIVED terminal state - there is no ``done.json``
  file. ``is_stage_complete("done", ...)`` returns True iff
  (a) every applicable prior stage is complete AND
  (b) ``manifest.current_stage == "done"``. The resume rule's
  ``None`` return means "all applicable stages complete - nothing
  to resume".

Plan 01-04 M1+M2:

- :func:`parse_stage_file` accepts a ``model_cls`` keyword argument;
  when provided, the file is validated against the Pydantic model and
  a :class:`ValidationError` makes the function return False (the
  resume rule then re-runs the stage).
- Zero-byte ``source.*`` files are rejected by the same size check
  the JSON branch already applied.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.models.diarization import Diarization
from app.models.manifest import JobManifest
from app.models.settings import Settings
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.storage.fs import (
    diarization_path,
    job_dir,
    source_path,
    summary_path,
    transcript_path,
)

StageName = Literal["ingested", "transcribed", "diarized", "summarized", "done"]

# The standard walk order from D-12. The first applicable incomplete
# stage is the resume point.
STAGE_ORDER: tuple[StageName, ...] = (
    "ingested",
    "transcribed",
    "diarized",
    "summarized",
    "done",
)


def is_stage_applicable(stage: StageName, manifest: JobManifest) -> bool:
    """Return whether ``stage`` applies to this job at all.

    - ``diarized`` is NOT applicable if ``manifest.diarization_enabled`` is
      ``False`` (diarization is opt-in per D-11).
    - ``summarized`` is NOT applicable if ``manifest.summary_kinds`` is
      empty (no summary templates requested).
    - All other stages are always applicable.
    """
    if stage == "diarized":
        return bool(manifest.diarization_enabled)
    if stage == "summarized":
        return len(manifest.summary_kinds) > 0
    return True


def parse_stage_file(
    path: Path, *, model_cls: type[BaseModel] | None = None
) -> bool:
    """Return True iff ``path`` exists, is non-empty, and parses correctly.

    Plan 01-04 M1+M2:

    - Zero-byte files are rejected (size check is at the top, so both
      the JSON branch AND the ``source.*`` branch apply it).
    - ``source.*`` files are media; existence + non-empty is enough.
    - When ``model_cls`` is provided, the file's JSON is validated via
      ``model_cls.model_validate_json``; a :class:`ValidationError`
      (or any :class:`ValueError` from JSON parsing) makes the
      function return False so the resume rule re-runs the stage.
    - When ``model_cls`` is None and the path is a JSON stage file,
      a plain JSON parse is enough (backward-compatible fallback).
    """
    if not path.exists():
        return False
    try:
        if path.stat().st_size == 0:
            return False
    except OSError:
        return False
    # ``source.*`` files are media; existence + non-empty is sufficient.
    if path.name.startswith("source."):
        return True
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if model_cls is not None:
        # Strict path: validate against the typed model. A
        # ValidationError (missing required fields, wrong types) makes
        # the file "not a complete stage output" so the resume rule
        # re-runs the stage.
        try:
            model_cls.model_validate_json(content)
        except (ValidationError, ValueError):
            return False
        return True
    # Backward-compatible fallback: a plain JSON parse is enough.
    try:
        json.loads(content)
    except ValueError:
        return False
    return True


def is_stage_complete(
    stage: StageName,
    settings: Settings,
    job_id: str,
    manifest: JobManifest,
) -> bool:
    """Return whether ``stage`` is complete for this job.

    Per-stage file-existence rule (D-11); Plan 01-04 M1+M2 adds
    Pydantic validation:

    - ``ingested``: ``source.<ext>`` exists AND is non-empty.
    - ``transcribed``: ``transcript.json`` exists AND parses as a
      :class:`Transcript`.
    - ``diarized``: ``diarization.json`` exists AND parses as a
      :class:`Diarization`.
    - ``summarized``: for every ``kind`` in ``manifest.summary_kinds``,
      ``summary-<kind>.json`` exists AND parses as a :class:`Summary`.
    - ``done``: True iff ``manifest.current_stage == "done"`` AND every
      applicable prior stage is complete. ``done`` is DERIVED, not
      file-backed - there is no ``done.json`` file.
    """
    if stage == "ingested":
        # D-04 (Phase 4): local-reference ingest records
        # ``manifest.source_path`` and references the file IN PLACE (no
        # copy into the job dir). FIRST check the manifest's source_path
        # resolves to a non-empty file; THEN fall back to the in-job-dir
        # ``source.<ext>`` variant (Phase 5 upload writes that; Phase 6
        # YouTube download writes that). The generalized check keeps
        # both ingest paths working from the same walker.
        sp = manifest.source_path
        if sp:
            try:
                p = Path(sp)
                if p.exists() and p.stat().st_size > 0:
                    return True
            except OSError:
                pass
        # Plan 01-04 M2: ``ingested`` requires a non-empty source file.
        # The path helpers iterate ``source.*`` to find any extension.
        d = job_dir(settings, job_id)
        if not d.is_dir():
            return False
        for p in d.glob("source.*"):
            if parse_stage_file(p):
                return True
        return False
    if stage == "transcribed":
        return parse_stage_file(
            transcript_path(settings, job_id), model_cls=Transcript
        )
    if stage == "diarized":
        return parse_stage_file(
            diarization_path(settings, job_id), model_cls=Diarization
        )
    if stage == "summarized":
        if not manifest.summary_kinds:
            return False
        for kind in manifest.summary_kinds:
            if not parse_stage_file(
                summary_path(settings, job_id, kind), model_cls=Summary
            ):
                return False
        return True
    if stage == "done":
        if manifest.current_stage != "done":
            return False
        # All applicable prior stages must also be complete.
        for prior in STAGE_ORDER:
            if prior == "done":
                break
            if not is_stage_applicable(prior, manifest):
                continue
            if not is_stage_complete(prior, settings, job_id, manifest):
                return False
        return True
    # Unknown stage: treat as not applicable -> not complete. The
    # ``STAGE_ORDER`` tuple is the exhaustive list of recognised
    # stages; a typo here is a programming error.
    return False


def infer_resume_point(
    settings: Settings,
    job_id: str,
    manifest: JobManifest,
) -> StageName | None:
    """Return the next stage to run, or ``None`` if nothing to resume.

    Walks :data:`STAGE_ORDER` in order; the first applicable stage
    that is NOT complete is the resume point. If the walk completes
    (every applicable stage is complete) the function returns
    ``None`` - meaning "all applicable stages complete, the job is
    effectively done from a resume perspective".
    """
    for stage in STAGE_ORDER:
        if not is_stage_applicable(stage, manifest):
            continue
        if not is_stage_complete(stage, settings, job_id, manifest):
            return stage
    return None


__all__ = [
    "STAGE_ORDER",
    "StageName",
    "infer_resume_point",
    "is_stage_applicable",
    "is_stage_complete",
    "parse_stage_file",
]
