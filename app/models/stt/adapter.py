"""FasterWhisperAdapter: the ONLY faster_whisper / ctranslate2 import site (SC-4).

This module is the concrete implementation of
:class:`~app.models.stt.protocol.STTAdapter` that wraps
``faster_whisper.WhisperModel``. It is the SINGLE place in ``app/`` that
imports ``faster_whisper`` or ``ctranslate2`` -- the boundary check
``grep -rE "from faster_whisper|import faster_whisper|import ctranslate2" app/``
matches only ``app/models/stt/adapter.py`` (SC-4, mirrors the Phase 2
``huggingface_hub`` boundary in ``app/models/manager.py`` lines 37-39).

``faster_whisper`` and ``ctranslate2`` are imported ONLY inside this module
(the boundary check ``grep -rE "from faster_whisper|import faster_whisper|import ctranslate2" app/`` matches only app/models/stt/adapter.py -- SC-4,
mirrors the Phase 2 huggingface_hub boundary in app/models/manager.py).

D-08 int8 verification: after ``load()``, the adapter reads
``self._model.model.compute_type`` (the inner
``ctranslate2.models.Whisper`` exposes the property) and fails LOUD
(``RuntimeError``) if the loaded compute_type is not in the ``_ACCEPTED``
equivalence set for the requested type. This is the load-bearing OOM
defense that keeps large-v3 at ~2 GB on the 8 GB laptop (D-04). The
``_ACCEPTED`` table accepts the documented CUDA ``int8 -> int8_float16``
substitution (Pitfall 2 -- proven by ``test_int8_equivalence_accepted``,
no false positive) AND rejects a silent ``float32`` fallback (Pitfall 3 /
Phase 2 Pitfall 12 analogue -- proven by
``test_int8_verification_fails_loud``).

The adapter is a PURE TRANSFORM: it receives already-resolved
``model_path`` / ``device`` / ``compute_type`` values (from
:func:`~app.models.backend.device_for` + the model manager). It does NOT
call :func:`~app.settings.service.current` or
:meth:`~app.models.backend.BackendProvider.device_for` itself -- keeping
it a pure transform the chunker / CLI can compose freely.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from app.models.stt.protocol import SttSegment, SttTranscription

_log = logging.getLogger(__name__)


# D-08 compute_type equivalence table (RESEARCH Pattern 2).
#
# Source: https://opennmt.net/CTranslate2/quantization.html +
# verified ``get_supported_compute_types('cpu', 0) == {'int8','int8_float32','float32'}``.
#
# This table is the dual-purpose guard:
#   - it accepts the documented ``int8 -> int8_float16`` CUDA substitution
#     (Pitfall 2) so it does NOT false-positive on CUDA (proven by
#     ``test_int8_equivalence_accepted``);
#   - it fails on a silent ``float32`` fallback (Pitfall 3) so a load that
#     silently dropped to ``float32`` raises ``RuntimeError`` (proven by
#     ``test_int8_verification_fails_loud`` -- the Phase 2 Pitfall 12
#     analogue).
_ACCEPTED: dict[str, set[str]] = {
    "int8": {"int8", "int8_float16", "int8_float32"},
    "int8_float16": {"int8_float16"},
    "int8_float32": {"int8_float32"},
    "float16": {"float16", "int8_float16"},
}


class SttInt8VerificationError(RuntimeError):
    """Raised when the loaded compute_type silently fell back from the requested type (D-08).

    Mirrors the typed-error pattern in :mod:`app.models.manager` lines
    65-133. A plain ``RuntimeError`` with the ``"int8 verification failed"``
    prefix would also satisfy the tests; this subclass is for callers that
    want to catch the failure specifically.
    """


class FasterWhisperAdapter:
    """Concrete :class:`~app.models.stt.protocol.STTAdapter` for faster-whisper.

    The ONLY ``faster_whisper`` / ``ctranslate2`` import site in ``app/``.
    Imports are LAZY (inside ``load()``) so importing this module does not
    pull the GPU deps and so the conftest ``mock_stt_adapter`` fixture can
    patch ``faster_whisper.WhisperModel`` before it is imported.
    """

    def __init__(self, model_path: str, device: str, compute_type: str) -> None:
        """Store the resolved values (pure transform -- no ``current()`` / ``device_for``).

        :param model_path: already-resolved on-disk model path (from the
            model manager).
        :param device: already-resolved device argument for
            ``faster_whisper`` (from ``BackendProvider.device_for`` --
            ``"cuda"`` / ``"cpu"``).
        :param compute_type: already-resolved compute_type (from the
            settings / presets resolver -- ``"int8"`` / ``"int8_float16"``
            / etc.).
        """
        self._model_path = model_path
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None  # loaded lazily in load()

    def load(self) -> None:
        """Load the WhisperModel and run D-08 int8 verification (fail-loud)."""
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        import ctranslate2  # type: ignore[import-not-found]

        supported = ctranslate2.get_supported_compute_types(self._device, 0)
        _log.info(
            "CT2 supported compute_types on %s: %s",
            self._device,
            supported,
        )

        self._model = WhisperModel(
            self._model_path,
            device=self._device,
            compute_type=self._compute_type,
        )

        # D-08 int8 verification: the inner ctranslate2.models.Whisper
        # exposes ``compute_type`` as a property -- read it after load and
        # fail loud if it silently fell back.
        actual = self._model.model.compute_type
        accepted = _ACCEPTED.get(self._compute_type, {self._compute_type})
        if actual not in accepted:
            raise SttInt8VerificationError(
                f"int8 verification failed: requested compute_type={self._compute_type!r} "
                f"but loaded={actual!r} supported={supported} "
                f"(silent fallback -- Phase 2 Pitfall 12 analogue)"
            )
        _log.info(
            "STT adapter loaded: requested compute_type=%s, loaded compute_type=%s, device=%s",
            self._compute_type,
            actual,
            self._device,
        )

    def transcribe(
        self,
        audio: Any,
        language: str | None = None,
        vad_filter: bool = True,
        condition_on_previous_text: bool = True,
    ) -> SttTranscription:
        """Transcribe ``audio`` and map faster-whisper segments to SttSegment.

        :param audio: a path OR a ``numpy.ndarray`` of float32 mono 16 kHz
            audio (the chunker passes pre-decoded arrays).
        :param language: ``None`` triggers faster-whisper auto-detect on
            the first 30 s (D-07, INGEST-06); the detected language is
            recorded on the returned :class:`SttTranscription`.
        """
        # Leave chunk_length at the default 30 (Pitfall: do NOT set a
        # non-30 value -- the chunker handles long-form chunking itself).
        segments_iter, info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
        )
        # Pitfall 7: the segments generator is lazy -- materialize before
        # the underlying iterator is exhausted / before we touch ``info``.
        materialized = list(segments_iter)
        segments: list[SttSegment] = []
        for seg in materialized:
            # Pitfall 6: faster-whisper Segment is a dataclass -- use
            # attribute access (``seg.start`` etc.), not dict indexing.
            # confidence is an exp(logprob) PROXY in [0,1], not a calibrated
            # probability (RESEARCH A5 / Codex LOW); documented here so a
            # future caller does not treat it as a calibrated score.
            confidence = math.exp(seg.avg_logprob) if seg.avg_logprob is not None else None
            segments.append(
                SttSegment(
                    start_s=float(seg.start),
                    end_s=float(seg.end),
                    text=seg.text.strip(),
                    confidence=confidence,
                )
            )
        return SttTranscription(
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            duration=float(info.duration),
        )

    def detect_language(self, audio: Any) -> tuple[str, float]:
        """Detect the dominant language of ``audio`` (returns (lang, probability))."""
        # Verified signature: ``detect_language(audio, vad_filter=True)``
        # returns ``(lang, probability, all_lang_probs)`` -- we drop the
        # third element per the Protocol.
        lang, probability, _all = self._model.detect_language(audio, vad_filter=True)
        return (lang, probability)

    def unload(self) -> None:
        """Release the loaded model (idempotent, mirrors ``ModelManager.unload`` D-03).

        NOTE (Codex LOW): setting ``_model = None`` releases the Python
        reference but may not immediately return VRAM to the allocator; if
        # VRAM retention is observed in practice, a later enhancement may
        # add ``gc.collect()`` + ``torch.cuda.empty_cache()`` -- deferred
        # until observed, out of scope for this plan.
        """
        self._model = None


__all__ = ["FasterWhisperAdapter", "SttInt8VerificationError"]