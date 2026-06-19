"""SC-4 forbidden-import boundary gate for the STT adapter.

``faster_whisper`` and ``ctranslate2`` are imported ONLY inside
``app/models/stt/adapter.py`` — the rest of ``app/`` depends on the
:class:`~app.models.stt.protocol.STTAdapter` Protocol, never on the
package. This test enforces that invariant with a regex restricted to
import-statement lines (Codex LOW: avoid brittle matches on future
comments mentioning the import).

This test is RED during Task 1 (adapter.py does not exist yet) and turns
GREEN when Task 2 creates adapter.py with the lazy imports.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_IMPORT_RE = re.compile(r"^\s*(from faster_whisper|import faster_whisper|import ctranslate2)", re.MULTILINE)


def _app_root() -> Path:
    """Return the ``app/`` directory relative to this test file."""
    here = Path(__file__).resolve().parent
    return here.parent / "app"


def test_import_boundary() -> None:
    """SC-4: only ``app/models/stt/adapter.py`` imports faster_whisper / ctranslate2."""
    app_root = _app_root()
    matches: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _IMPORT_RE.search(text):
            # Normalize to forward slashes for stable cross-platform matching.
            matches.append(str(path.relative_to(app_root.parent)).replace("\\", "/"))
    assert matches == ["app/models/stt/adapter.py"], (
        f"SC-4 boundary violated: expected only app/models/stt/adapter.py to "
        f"import faster_whisper / ctranslate2, got {matches!r}"
    )