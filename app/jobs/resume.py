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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from app.models.manifest import JobManifest
from app.models.settings import Settings
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


def parse_stage_file(path: Path) -> bool:
    """Return True iff ``path`` exists, is non-empty, and parses as JSON.

    For ``source.*`` files a JSON parse is not appropriate; the function
    always returns True when the file exists and is non-empty regardless
    of content. Used by D-12 to mark unparseable files for re-run.
    """
    if not path.exists():
        return False
    try:
        if path.stat().st_size == 0:
            return False
    except OSError:
        return False
    # ``source.*`` files are media; we only check existence + non-empty.
    if path.name.startswith("source."):
        return True
    try:
        with path.open("r", encoding="utf-8") as fh:
            json.load(fh)
        return True
    except (OSError, ValueError):
        return False


def is_stage_complete(
    stage: StageName,
    settings: Settings,
    job_id: str,
    manifest: JobManifest,
) -> bool:
    """Return whether ``stage`` is complete for this job.

    Per-stage file-existence rule (D-11):

    - ``ingested``: ``source_path(...)`` exists.
    - ``transcribed``: ``transcript_path(...)`` exists.
    - ``diarized``: ``diarization_path(...)`` exists.
    - ``summarized``: for every ``kind`` in ``manifest.summary_kinds``,
      ``summary_path(..., kind)`` exists.
    - ``done``: True iff ``manifest.current_stage == "done"`` AND every
      applicable prior stage is complete. ``done`` is DERIVED, not
      file-backed - there is no ``done.json`` file.
    """
    if stage == "ingested":
        return source_path(settings, job_id, "mp4").exists() or any(
            p.name.startswith("source.") for p in job_dir(settings, job_id).glob("source.*")
        )
    if stage == "transcribed":
        return parse_stage_file(transcript_path(settings, job_id))
    if stage == "diarized":
        return parse_stage_file(diarization_path(settings, job_id))
    if stage == "summarized":
        if not manifest.summary_kinds:
            return False
        for kind in manifest.summary_kinds:
            if not parse_stage_file(summary_path(settings, job_id, kind)):
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
