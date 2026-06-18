"""Filesystem path helpers for the on-disk model cache (Plan 02-02).

These helpers are the ONLY way to construct a path under
``<data_dir>/models/`` -- no other module in the codebase may
concatenate a path into the models tree (mirrors the
``app.storage.fs`` per-job folder boundary). Every category + spec
gets a stable, sandboxed on-disk path:

- ``<data_dir>/models/<category>/<sanitized_repo_id>/<file>``
- The ``repo_id`` is filesystem-sandboxed: ``/`` becomes ``--`` so
  ``Systran/faster-whisper-large-v3`` lives at
  ``models/stt/Systran--faster-whisper-large-v3/`` (a flat directory,
  not a deep nested tree -- Pitfall 4 mitigation: no user-input
  spaces, no path traversal).

``category`` is validated as a :class:`ModelCategory` member (raises
:class:`ValueError` if not) mirroring ``validate_source_ext`` in
``app.storage.fs``.
"""

from __future__ import annotations

from pathlib import Path

from app.models.diagnostics import ModelCategory, ModelSpec
from app.models.settings import Settings
from app.storage.fs import data_dir


def data_models_dir(settings: Settings) -> Path:
    """Return the models cache root: ``<data_dir>/models``."""
    return data_dir(settings) / "models"


async def ensure_models_dir(settings: Settings) -> Path:
    """Create and return the models cache root (mirrors ``ensure_job_dir``)."""
    path = data_models_dir(settings)
    path.mkdir(parents=True, exist_ok=True)
    return path


def category_models_dir(settings: Settings, category: ModelCategory) -> Path:
    """Return ``<data_models_dir>/<category.value>``.

    Validates ``category`` is a :class:`ModelCategory` member (raises
    :class:`ValueError` otherwise) mirroring ``validate_source_ext``.
    """
    if not isinstance(category, ModelCategory):
        raise ValueError(
            f"invalid model category: {category!r}; must be a ModelCategory member "
            f"(one of {[c.value for c in ModelCategory]})"
        )
    return data_models_dir(settings) / category.value


def spec_dir(settings: Settings, category: ModelCategory, repo_id: str) -> Path:
    """Return the per-repo directory: ``<category_models_dir>/<sanitized repo_id>``.

    The ``repo_id`` is filesystem-sandboxed: ``/`` becomes ``--`` so
    ``Systran/faster-whisper-large-v3`` lives at
    ``models/stt/Systran--faster-whisper-large-v3/`` (Pitfall 4 --
    flat directory, no path traversal from a project-controlled
    ``repo_id``).
    """
    return category_models_dir(settings, category) / repo_id.replace("/", "--")


def spec_file_path(settings: Settings, category: ModelCategory, spec: ModelSpec) -> Path:
    """Return the on-disk file path for ``spec`` under ``category``.

    If ``spec.file`` is set, the file is ``<spec_dir>/<spec.file>``;
    otherwise the file is ``<spec_dir>/<sanitized repo_id>.bin`` (the
    fallback for repos that expose a single default filename).
    """
    filename = spec.file or f"{spec.repo_id.replace('/', '--')}.bin"
    return spec_dir(settings, category, spec.repo_id) / filename


__all__ = [
    "category_models_dir",
    "data_models_dir",
    "ensure_models_dir",
    "spec_dir",
    "spec_file_path",
]