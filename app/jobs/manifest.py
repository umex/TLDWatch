"""Manifest construction, atomic write, read, mtime, and stage-update helpers.

The manifest is the per-job on-disk snapshot of a job's state. The
DB row is a projection of the manifest (D-03). The write-manifest-
first / commit-DB-last ordering in :func:`update_stage` is the
consistency protocol that keeps the two from drifting; a crash
between the manifest write and the DB write is self-healed on
the next boot by :mod:`app.jobs.reconcile` (Plan 01-03).

Plan 01-04 H3+H4: ``update_stage`` writes ``status`` AND the full
projected metadata (``language``, ``duration_s``, ``source_*``,
``summary_kinds_json``) in the same SQL UPDATE. The ``stage_to_status``
helper is the single source of truth for the stage-to-status mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common import StageTimestamps
from app.models.manifest import JobManifest
from app.models.settings import Settings
from app.storage.atomic import atomic_write_json
from app.storage.fs import manifest_path
from app.util.time import utcnow_iso

# Per-stage default :class:`JobStatus` values. The map is exhaustive
# over the "active processing" stages; the "diarized" and "summarized"
# stages are CONDITIONAL on the manifest's diarization_enabled and
# summary_kinds fields, so they are NOT in the map (the
# :func:`stage_to_status` helper handles them inline). The terminal
# statuses (``failed`` / ``cancelled``) are NOT derived from
# ``current_stage`` either - they are set by :func:`mark_failed` /
# :func:`cancel_job` directly.
_STAGE_STATUS_MAP: dict[str | None, str] = {
    None: "queued",
    "ingested": "ingesting",
    "transcribed": "transcribing",
    "done": "done",
}


def stage_to_status(stage: str | None, manifest: JobManifest) -> str:
    """Map ``current_stage`` + manifest to a :data:`JobStatus` value.

    Mapping table (the single source of truth, mirrored in Plan
    01-04's "Stage-to-Status Mapping Table"):

    - ``stage is None``                           -> ``"queued"``
    - ``"ingested"``                              -> ``"ingesting"``
    - ``"transcribed"``                           -> ``"transcribing"``
    - ``"diarized"`` + ``diarization_enabled``    -> ``"diarizing"``
    - ``"diarized"`` + NOT diarization_enabled    -> ``"transcribing"`` (defensive)
    - ``"summarized"`` + non-empty summary_kinds  -> ``"summarizing"``
    - ``"summarized"`` + empty summary_kinds      -> ``"transcribing"`` (defensive)
    - ``"done"``                                  -> ``"done"``
    - unknown stage                               -> ``"queued"`` (defensive)

    The terminal statuses (``"failed"`` / ``"cancelled"``) are NOT
    derived here - they are set by :func:`mark_failed` /
    :func:`cancel_job` directly.
    """
    if stage is None:
        return "queued"
    if stage == "diarized":
        if manifest.diarization_enabled:
            return "diarizing"
        return "transcribing"  # defensive fallback
    if stage == "summarized":
        if len(manifest.summary_kinds) > 0:
            return "summarizing"
        return "transcribing"  # defensive fallback
    return _STAGE_STATUS_MAP.get(stage, "queued")


def _latest_ts(stage_timestamps: StageTimestamps) -> str:
    """Return the latest non-None timestamp across all stage timestamps.

    Used by :mod:`app.jobs.reconcile` for the ``updated_at`` column
    so a healed row reflects the most-recent stage transition, not
    the original queued timestamp (Codex review fix). Falls back to
    the queued timestamp if every other stage is None (a freshly-
    queued job has only the queued timestamp set).
    """
    candidates = [
        stage_timestamps.queued,
        stage_timestamps.ingested,
        stage_timestamps.transcribed,
        stage_timestamps.diarized,
        stage_timestamps.summarized,
        stage_timestamps.done,
    ]
    non_none = [ts for ts in candidates if ts is not None]
    if not non_none:
        return stage_timestamps.queued
    # ISO 8601 strings sort lexicographically when they share the
    # same timezone suffix (all are produced by utcnow_iso with
    # ``+00:00``), so ``max`` is the latest.
    return max(non_none)


def empty_manifest(job_id: str) -> JobManifest:
    """Build a freshly-queued :class:`JobManifest` for a new job."""
    return JobManifest(
        schema_version=1,
        job_id=job_id,
        status="queued",
        current_stage=None,
        stage_timestamps=StageTimestamps(queued=utcnow_iso()),
    )


async def write_manifest(settings: Settings, manifest: JobManifest) -> Path:
    """Atomically write the manifest for ``manifest.job_id`` to disk.

    Uses :func:`app.storage.atomic.atomic_write_json` (tmp + fsync +
    os.replace, with the Windows retry helper) so a partial write can
    never leave a corrupt manifest on disk.
    """
    path = manifest_path(settings, manifest.job_id)
    await atomic_write_json(path, manifest.model_dump(mode="json"))
    return path


async def read_manifest(settings: Settings, job_id: str) -> JobManifest:
    """Read and validate the manifest for ``job_id``.

    Raises :class:`FileNotFoundError` (a known error type that the
    route layer maps to a 404) if the manifest is missing. The error
    message names the job id so a missing manifest is debuggable
    from the API response.
    """
    path = manifest_path(settings, job_id)
    if not path.exists():
        raise FileNotFoundError(f"manifest not found for job {job_id}")
    return JobManifest.model_validate_json(path.read_text(encoding="utf-8"))


def manifest_mtime(settings: Settings, job_id: str) -> float | None:
    """Return the manifest file's mtime in epoch seconds, or ``None``.

    Used by the staleness check in :mod:`app.jobs.cleanup` as a
    fallback when no stage files exist yet.
    """
    try:
        return manifest_path(settings, job_id).stat().st_mtime
    except FileNotFoundError:
        return None


async def update_stage(
    settings: Settings,
    session: AsyncSession,
    job_id: str,
    stage: str,
    manifest_patch: "ManifestPatch | None" = None,  # noqa: F821
) -> JobManifest:
    """Apply a stage transition with write-manifest-first, commit-DB-last.

    Ordering (Codex HIGH #1):

    1. Read the current manifest via :func:`read_manifest` (raises
       :class:`FileNotFoundError` -> 404 in the route).
    2. Build a deep copy with ``current_stage = stage`` and a fresh
       ``stage_timestamps[stage] = utcnow_iso()`` (PROTECTED - the
       caller cannot override these via the patch).
    3. If ``manifest_patch`` is provided, apply ONLY the allowlisted
       user-mutable fields via ``model_copy(update=...)``. The
       :class:`app.models.job.ManifestPatch` model excludes the
       protected fields by construction, so this is safe.
    4. Compute the projected ``status`` via :func:`stage_to_status`
       and set ``new_manifest.status`` so the on-disk manifest and
       the DB row agree (Plan 01-04 H3).
    5. Atomically write the new manifest to disk
       (:func:`write_manifest` -> :func:`atomic_write_json` which
       wraps ``os.replace`` in :func:`retry_windows`).
    6. UPDATE the DB row LAST with the full projection: ``status``,
       ``current_stage``, ``stage_timestamps_json``, ``updated_at``,
       and the projected metadata columns (``source_type``,
       ``source_path``, ``source_sha256``, ``duration_s``,
       ``language``, ``summary_kinds_json``). Plan 01-04 H3+H4.
       A failure at this step is recoverable on next boot by
       :func:`app.jobs.reconcile.reconcile_all` (the manifest on
       disk is authoritative; the DB row is the projection).
    7. Return the new :class:`JobManifest`.
    """
    # Imported here to avoid a top-level circular import
    # (app.models.job imports from app.models.manifest for the
    # JobManifest type; this module imports the same).
    from app.models.job import ManifestPatch

    current = await read_manifest(settings, job_id)
    new_manifest = current.model_copy(deep=True)
    # PROTECTED: current_stage comes from the function arg, never the patch.
    new_manifest.current_stage = stage
    # PROTECTED: stage_timestamps are set by this helper, never the patch.
    new_ts = new_manifest.stage_timestamps.model_copy(update={stage: utcnow_iso()})
    new_manifest = new_manifest.model_copy(update={"stage_timestamps": new_ts})

    if manifest_patch is not None:
        # The ManifestPatch model is strict + extra=forbid; its fields
        # are the user-mutable subset. ``exclude_unset=True`` lets the
        # caller send a partial patch (only the fields they want to
        # change) without overwriting existing manifest values.
        updates = manifest_patch.model_dump(exclude_unset=True)
        new_manifest = new_manifest.model_copy(update=updates)

    # H3: compute the projected status from the new manifest and
    # write it into the manifest so the on-disk file and the DB row
    # agree on status.
    projected_status = stage_to_status(stage, new_manifest)
    new_manifest = new_manifest.model_copy(update={"status": projected_status})

    # Write-manifest-first.
    await write_manifest(settings, new_manifest)

    # Commit-DB-last. H3+H4: write the full projection (status +
    # metadata) in the same UPDATE. If this fails the manifest is
    # still authoritative and ``reconcile_all`` will heal the drift
    # on next boot.
    await session.execute(
        text(
            "UPDATE jobs SET status = :status, current_stage = :stage, "
            "stage_timestamps_json = :ts_json, updated_at = :now, "
            "source_type = :source_type, source_path = :source_path, "
            "original_filename = :original_filename, "
            "source_sha256 = :source_sha256, duration_s = :duration_s, "
            "language = :language, summary_kinds_json = :summary_kinds_json "
            "WHERE id = :id"
        ),
        {
            "status": projected_status,
            "stage": stage,
            "ts_json": json.dumps(new_manifest.stage_timestamps.model_dump()),
            "now": utcnow_iso(),
            "source_type": new_manifest.source_type,
            "source_path": new_manifest.source_path,
            "original_filename": new_manifest.original_filename,
            "source_sha256": new_manifest.source_sha256,
            "duration_s": new_manifest.duration_s,
            "language": new_manifest.language,
            "summary_kinds_json": json.dumps(new_manifest.summary_kinds),
            "id": job_id,
        },
    )
    await session.commit()
    return new_manifest


__all__ = [
    "empty_manifest",
    "manifest_mtime",
    "read_manifest",
    "stage_to_status",
    "update_stage",
    "write_manifest",
]
