"""Sync retry helper used to harden Windows-flavoured filesystem operations.

The :func:`retry_windows` helper catches a configurable set of transient
exceptions (default: :class:`PermissionError` and :class:`OSError`),
sleeps with linear backoff, and re-raises the last exception once the
attempt budget is exhausted. Non-retriable exceptions propagate
immediately. It is used to wrap ``os.replace`` and similar filesystem
operations in the atomic-write helper so a transient Windows file
lock (antivirus, Search Indexer) does not crash a request handler.
"""

from __future__ import annotations

import time
from typing import Any, Callable


def retry_windows(
    func: Callable[..., Any],
    *args: Any,
    attempts: int = 3,
    backoff_s: float = 0.1,
    retriable_exceptions: tuple[type[BaseException], ...] = (PermissionError, OSError),
    **kwargs: Any,
) -> Any:
    """Call ``func(*args, **kwargs)`` retrying on retriable exceptions.

    The total number of attempts is ``attempts``; the first attempt
    happens immediately, the next ones are spaced by ``backoff_s *
    (attempt + 1)`` seconds. If every attempt raises, the last exception
    propagates. Non-retriable exceptions propagate immediately without
    consuming further attempts.
    """
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return func(*args, **kwargs)
        except retriable_exceptions as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(backoff_s * (attempt + 1))
    # All attempts failed - re-raise the last retriable exception.
    assert last_exc is not None
    raise last_exc
