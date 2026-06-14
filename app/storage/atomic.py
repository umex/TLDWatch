"""Atomic file-write helpers used by every stage mutator.

The contract is: write to a uniquely-named temp file in the SAME
directory as the target, ``fsync`` it, close the handle, then
``os.replace`` it onto the target path. ``os.replace`` is wrapped in
:func:`app.storage.retry.retry_windows` to survive transient
``PermissionError``/``OSError`` thrown by Windows antivirus or the
Search Indexer when they briefly hold a file open.

The temp filename uses the prefix ``.tmp_`` (e.g.,
``manifest.json.tmp_abc123``) so the temp file is distinct from any
user-visible name and is covered by the ``*.tmp_*`` gitignore pattern.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import aiofiles

from app.storage.retry import retry_windows


def _make_temp_path(target: Path) -> Path:
    return target.parent / f".tmp_{uuid.uuid4().hex[:8]}"


async def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically.

    The file is created in ``path.parent`` with a unique temp name,
    fully flushed and ``fsync``-ed, then atomically renamed onto
    ``path`` via :func:`os.replace` (retried to survive transient
    Windows file locks). On any failure the temp file is removed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _make_temp_path(path)
    try:
        async with aiofiles.open(tmp_path, "wb") as handle:
            await handle.write(data)
            await handle.flush()
            os.fsync(handle.fileno())
        # The rename is the step that fails under transient Windows file
        # locks (antivirus, Search Indexer); the aiofiles write itself
        # is to a unique temp name and does not contend.
        retry_windows(os.replace, tmp_path, path)
    except BaseException:
        # Best-effort cleanup of the temp file. We do not wrap this
        # in a try/except nesting pyramid - if cleanup fails the
        # process is already in an error path.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


async def atomic_write_json(path: Path, payload: dict) -> None:
    """Write ``payload`` as pretty-printed JSON to ``path`` atomically."""
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    await atomic_write_bytes(path, encoded)
