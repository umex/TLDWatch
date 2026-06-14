"""UUID helpers for job identifiers.

This module is the SINGLE point of UUID validation in the codebase.
Later phases call :func:`validate_job_id` before constructing any
filesystem path under a job directory (Codex MEDIUM).
"""

from __future__ import annotations

import uuid


def new_job_id() -> str:
    """Return a fresh UUIDv4 string."""
    return str(uuid.uuid4())


def validate_job_id(job_id: str) -> str:
    """Return the canonical lowercase form of ``job_id``.

    Raises :class:`ValueError` if the string is not a valid UUID. The
    returned string is always the canonical lowercase
    ``xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`` form.
    """
    return str(uuid.UUID(job_id))
