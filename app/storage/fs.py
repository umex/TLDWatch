"""Filesystem path helpers and the bootstrap settings-file resolver.

The bootstrap settings path is the ONE stable, fixed path in the app:
``<project_root>/data/settings.json``. It is resolved via
``Path(__file__).resolve().parent.parent / "data" / "settings.json"``,
so it is the same absolute path for every run - even after the
``data_dir`` setting is changed. This eliminates the circular
bootstrap where the settings file lived inside the directory it
pointed to (Codex HIGH).
"""

from __future__ import annotations

from pathlib import Path

from app.models.settings import Settings


def bootstrap_settings_path() -> Path:
    """Return the absolute, STABLE path of the bootstrap settings file.

    Resolves to ``<project_root>/data/settings.json`` regardless of the
    process working directory. Patching ``settings.data_dir`` does not
    move this file.
    """
    return Path(__file__).resolve().parent.parent.parent / "data" / "settings.json"


def data_dir(settings: Settings) -> Path:
    """Return the configured data directory as a :class:`Path`."""
    return Path(settings.data_dir)


def job_dir(settings: Settings, job_id: str) -> Path:
    """Return the per-job directory: ``<data_dir>/jobs/<job_id>``."""
    return data_dir(settings) / "jobs" / job_id


async def ensure_job_dir(settings: Settings, job_id: str) -> Path:
    """Create and return the per-job directory."""
    path = job_dir(settings, job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path(settings: Settings, job_id: str) -> Path:
    """Return the manifest file path for a given job."""
    return job_dir(settings, job_id) / "manifest.json"
