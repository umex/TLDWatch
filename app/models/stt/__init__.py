"""STT adapter package (Phase 3, D-06).

Re-exports the Protocol + result types + the
:class:`FasterWhisperAdapter` concrete implementation. The concrete
adapter module has NO top-level ``faster_whisper`` / ``ctranslate2`` import
(both are lazy inside ``FasterWhisperAdapter.load``) so importing this
package top does not pull the GPU deps.

``FasterWhisperAdapter`` is re-exported lazily via ``__getattr__`` so the
package top imports cleanly during the TDD RED phase (Task 1) before
``adapter.py`` exists, and so importing ``app.models.stt`` does not
eagerly load the concrete implementation when only the Protocol is
needed.
"""

from __future__ import annotations

from app.models.stt.protocol import STTAdapter, SttSegment, SttTranscription

__all__ = [
    "FasterWhisperAdapter",
    "STTAdapter",
    "SttSegment",
    "SttTranscription",
]


def __getattr__(name: str):
    if name == "FasterWhisperAdapter":
        from app.models.stt.adapter import FasterWhisperAdapter

        return FasterWhisperAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")