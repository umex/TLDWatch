"""Filesystem path helpers and the bootstrap settings-file resolver.

The bootstrap settings path is the ONE stable, fixed path in the app:
``<project_root>/data/settings.json``. It is resolved via
``Path(__file__).resolve().parent.parent / "data" / "settings.json"``,
so it is the same absolute path for every run - even after the
``data_dir`` setting is changed. This eliminates the circular
bootstrap where the settings file lived inside the directory it
pointed to (Codex HIGH).

Plan 01-03 adds the per-stage file path helpers
(``transcript_path``, ``diarization_path``, ``summary_path``,
``edits_path``, ``source_path``), the ``list_stage_files`` /
``last_stage_mtime`` helpers, and the ``validate_source_ext`` /
``validate_summary_kind`` allowlists. These are the ONLY way to
construct a path under ``data/jobs/<id>/`` - no other module in the
codebase may concatenate a path into a per-job folder (the
boundary check is enforced by ``grep -rE "Path\\(['\\\"]data/jobs"
app/api/ tests/`` which must return no matches).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.models.settings import Settings


# Allowlist of media extensions accepted by ``validate_source_ext``
# (D-03). Lower-case, no leading dot. Covers the formats the front-end
# ingest page accepts; later phases may extend the set.
ALLOWED_SOURCE_EXTS: frozenset[str] = frozenset(
    {"mp4", "mkv", "webm", "mov", "mp3", "wav", "m4a", "flac", "ogg"}
)

# Filenames recognised as "stage files" by ``list_stage_files`` and
# ``last_stage_mtime``. Source files are matched by the ``source.*``
# prefix (any extension - the allowlist is enforced at write time by
# ``source_path`` / ``validate_source_ext``).
_STAGE_FILE_NAMES: tuple[str, ...] = (
    "manifest.json",
    "transcript.json",
    "diarization.json",
    "edits.json",
)
_SOURCE_FILE_PREFIX = "source."


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


# --- Per-stage file path helpers (Plan 01-03) ------------------------------
#
# Each helper validates its input (job_id is implicitly validated by the
# route layer via ``app.jobs.ids.validate_job_id``; the file-suffix helpers
# validate the suffix via ``validate_source_ext`` / ``validate_summary_kind``
# before constructing the path) and returns a path inside the job
# folder. Callers must NOT construct these paths by string concatenation.


def transcript_path(settings: Settings, job_id: str) -> Path:
    """Return the transcript file path: ``<job_dir>/transcript.json``."""
    return job_dir(settings, job_id) / "transcript.json"


def diarization_path(settings: Settings, job_id: str) -> Path:
    """Return the diarization file path: ``<job_dir>/diarization.json``."""
    return job_dir(settings, job_id) / "diarization.json"


def summary_path(settings: Settings, job_id: str, kind: str) -> Path:
    """Return the summary file path: ``<job_dir>/summary-<kind>.json``.

    Validates ``kind`` via :func:`app.models.summary.validate_summary_kind`
    BEFORE constructing the path - a bad kind raises :class:`ValueError`
    (strict path validation, Codex MEDIUM).
    """
    # Imported lazily to avoid a circular import at module load time
    # (app.models.summary is a leaf module and does not import
    # app.storage.fs, so the lazy import is purely for ordering
    # robustness).
    from app.models.summary import validate_summary_kind

    normalised = validate_summary_kind(kind)
    return job_dir(settings, job_id) / f"summary-{normalised}.json"


def edits_path(settings: Settings, job_id: str) -> Path:
    """Return the edits file path: ``<job_dir>/edits.json``."""
    return job_dir(settings, job_id) / "edits.json"


def source_path(settings: Settings, job_id: str, ext: str) -> Path:
    """Return the source file path: ``<job_dir>/source.<ext>``.

    Validates ``ext`` via :func:`validate_source_ext` BEFORE
    constructing the path - a bad extension (path-traversal,
    absolute path, or non-allowlisted type) raises
    :class:`ValueError`.
    """
    normalised = validate_source_ext(ext)
    return job_dir(settings, job_id) / f"source.{normalised}"


# --- Validation helpers (Plan 01-03) ---------------------------------------


def validate_source_ext(ext: str) -> str:
    """Return the normalised (lowercase, no leading dot) source extension.

    Rejects:

    - empty string
    - any path-traversal characters (``..``, ``/``, ``\\``, ``:``,
      ``*``, ``?``, ``"``, ``<``, ``>``, ``|``)
    - any extension not in :data:`ALLOWED_SOURCE_EXTS` (lowercase, no
      leading dot)

    On success returns the normalised extension in lowercase without
    a leading dot (e.g. ``"mp4"``, ``"MP4"`` -> ``"mp4"``,
    ``".mp4"`` -> ``"mp4"``).
    """
    if not isinstance(ext, str) or not ext:
        raise ValueError(f"invalid source extension: {ext!r}")
    # Reject any path-traversal / path-injection characters. We use
    # substring containment because the allowlist is the smaller check
    # and the result is a clearer error if the bad chars are seen
    # first.
    bad_chars = ("..", "/", "\\", ":", "*", "?", '"', "<", ">", "|")
    for bad in bad_chars:
        if bad in ext:
            raise ValueError(f"invalid source extension: {ext!r}")
    # Strip a leading dot, lowercase.
    if ext.startswith("."):
        ext = ext[1:]
    normalised = ext.lower()
    if normalised not in ALLOWED_SOURCE_EXTS:
        raise ValueError(
            f"unsupported source extension {ext!r}; allowed: "
            f"{sorted(ALLOWED_SOURCE_EXTS)}"
        )
    return normalised


# --- File enumeration helpers (Plan 01-03) ---------------------------------


def list_stage_files(settings: Settings, job_id: str) -> list[Path]:
    """Return the absolute paths of every stage file that currently exists.

    Matches the fixed stage filenames (``manifest.json``,
    ``transcript.json``, ``diarization.json``, ``edits.json``) plus
    any ``source.*`` file (the actual extension is unknown - the
    allowlist is enforced at write time, not read time). Returns an
    empty list if the job directory does not exist.
    """
    d = job_dir(settings, job_id)
    if not d.is_dir():
        return []
    found: list[Path] = []
    for name in os.listdir(d):
        if name in _STAGE_FILE_NAMES or name.startswith(_SOURCE_FILE_PREFIX):
            found.append(d / name)
    return found


def last_stage_mtime(settings: Settings, job_id: str) -> float | None:
    """Return the most recent mtime (epoch seconds) across stage files.

    Returns ``None`` if no stage files exist (used by the staleness
    check in :mod:`app.jobs.cleanup`).
    """
    files = list_stage_files(settings, job_id)
    if not files:
        return None
    return max(p.stat().st_mtime for p in files)
