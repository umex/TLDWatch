"""Manifest construction and atomic write helpers."""

from __future__ import annotations

from pathlib import Path

from app.models.common import StageTimestamps
from app.models.manifest import JobManifest
from app.models.settings import Settings
from app.storage.atomic import atomic_write_json
from app.storage.fs import manifest_path
from app.util.time import utcnow_iso


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
