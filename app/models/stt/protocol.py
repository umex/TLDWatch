"""STTAdapter Protocol + result types (D-06, SC-4).

This module is the **GPU-abstraction seam** between the rest of the
application and the STT inference package. Everything outside
:mod:`app.models.stt` depends on :class:`STTAdapter` (the Protocol),
NEVER on ``faster_whisper`` / ``ctranslate2`` directly (SC-4 — mirrors the
Phase 2 ``BackendProvider`` seam in :mod:`app.models.backend` and the
``huggingface_hub`` boundary in :mod:`app.models.manager`).

The concrete :class:`~app.models.stt.adapter.FasterWhisperAdapter` is the
ONLY module in ``app/`` that imports ``faster_whisper`` / ``ctranslate2``
— the boundary check
``grep -rE "from faster_whisper|import faster_whisper|import ctranslate2" app/``
matches only ``app/models/stt/adapter.py``.

Layering note (addresses Codex MEDIUM on SttSegment vs TranscriptSegment
drift): :class:`SttSegment` is the STT-layer Protocol contract per D-06.
It intentionally mirrors :class:`~app.models.transcript.TranscriptSegment`'s
field shape but is a SEPARATE type so the STT Protocol stays decoupled from
the storage-layer ``Transcript`` schema. The chunker (03-02) performs the
single ``SttSegment -> TranscriptSegment`` conversion at the seam. This is
deliberate layering, not drift — collapsing the two would couple the STT
contract to the storage schema and would force every STT backend to know
about ``speaker`` (a diarization-stage concern, Phase 7).

Forward disclosure (addresses Codex LOW on the Wave-1 interface being
modified in Wave 2): plan 03-02 EXTENDS this Protocol with
``decode_audio(self, path: str) -> numpy.ndarray`` so the chunker can decode
audio without importing ``faster_whisper`` (SC-4). That addition is a
strict superset — existing implementations remain valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.models.transcript import TranscriptSegment  # noqa: F401  (re-exported below)

if TYPE_CHECKING:
    import numpy.ndarray  # type: ignore[import-not-found]


@dataclass
class SttSegment:
    """A single timed STT segment (STT-layer contract per D-06).

    The fields mirror :class:`~app.models.transcript.TranscriptSegment`'s
    shape (``start_s`` / ``end_s`` / ``text`` / ``confidence``) but this is
    a separate type — see the module docstring for the layering rationale.
    ``speaker`` is intentionally absent here; that is a diarization-stage
    (Phase 7) concern and the chunker fills it in on the
    ``TranscriptSegment`` copy.
    """

    start_s: float
    end_s: float
    text: str
    confidence: float | None


@dataclass
class SttTranscription:
    """The full result of one ``transcribe()`` call.

    ``language`` / ``language_probability`` come from faster-whisper's
    auto-detect on the first 30 s when the caller passes ``language=None``
    (D-07, INGEST-06). ``duration`` is the source audio duration in seconds.
    """

    segments: list[SttSegment]
    language: str
    language_probability: float
    duration: float


class STTAdapter(Protocol):
    """Speech-to-text adapter interface (D-06).

    ``load()`` is lazy: it is called once before the first ``transcribe`` /
    ``detect_language`` call and may be heavy (model download + VRAM
    allocation). ``unload()`` is idempotent (mirrors ``ModelManager.unload``
    D-03) and releases the loaded model.

    ``transcribe(audio, ...)`` accepts a path OR a ``numpy.ndarray`` of
    float32 mono 16 kHz audio (the chunker passes pre-decoded arrays so it
    can re-use the decode for chunking). ``language=None`` triggers
    faster-whisper's auto-detect (D-07, INGEST-06) and the detected
    language is recorded on the returned :class:`SttTranscription`.

    The adapter is a PURE TRANSFORM: it receives already-resolved
    ``model_path`` / ``device`` / ``compute_type`` values (from
    :func:`~app.models.backend.device_for` + the model manager). It does
    NOT call :func:`~app.settings.service.current` or
    :meth:`~app.models.backend.BackendProvider.device_for` itself — keeping
    it a pure transform the chunker / CLI can compose freely.

    NOTE: plan 03-02 extends this Protocol with
    ``decode_audio(self, path: str) -> numpy.ndarray``. That is a strict
    superset addition; existing implementations remain valid.
    """

    def load(self) -> None: ...
    def transcribe(
        self,
        audio: "str | object",
        language: str | None = None,
        vad_filter: bool = True,
        condition_on_previous_text: bool = True,
    ) -> SttTranscription: ...
    def detect_language(self, audio: "object") -> tuple[str, float]: ...
    def decode_audio(self, path: str) -> "numpy.ndarray":
        """Decode ``path`` into a mono float32 16 kHz numpy array (D-01 PyAV).

        Added in plan 03-02 so the chunker can decode audio without
        importing ``faster_whisper`` (SC-4). The concrete implementation
        lives in :class:`~app.models.stt.adapter.FasterWhisperAdapter`
        (the ONLY ``faster_whisper`` import site); the
        :class:`~tests._stt_fake.FakeAdapter` provides a test double.
        """
        ...
    def unload(self) -> None: ...


__all__ = ["STTAdapter", "SttSegment", "SttTranscription"]