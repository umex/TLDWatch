from __future__ import annotations

from datetime import datetime, timezone


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with a ``+00:00`` offset.

    This is the ONLY function in the codebase that produces a "now" timestamp.
    All other modules must call this helper instead of constructing a
    datetime directly.
    """
    return datetime.now(timezone.utc).isoformat()
