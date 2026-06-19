"""FakeAdapter: a deterministic :class:`app.models.stt.protocol.STTAdapter`
implementation used by the chunker (03-02) and CLI (03-03) tests.

This fake is the REASON the Protocol exists (D-06): chunker + CLI tests
depend on it, never on ``faster_whisper``. Two OOM modes are supported so
the chunker's full-coverage OOM test (03-02) can exercise recursive
halving without pulling in a real GPU model:

- ``oom_on_call``: the Nth ``transcribe()`` call raises
  ``RuntimeError("CUDA failed with error out of memory")`` — matches the
  real faster-whisper / ctranslate2 OOM message (RESEARCH Pitfall 5:
  match the ``"out of memory"`` substring).
- ``oom_above_seconds``: a ``transcribe()`` call whose ``audio`` array is
  longer than this threshold (seconds) OOMs — so a window ABOVE the
  threshold OOMs and recursive halving succeeds on pieces below it.

``call_count`` and ``transcribe_calls`` are exposed for chunker tests that
assert the chunker split a long audio window into sub-threshold pieces.
"""

from __future__ import annotations

from types import SimpleNamespace

# Sample rate used by faster-whisper (16 kHz). Importing numpy lazily keeps
# the module importable on CPU-only environments per the lazy-import
# discipline, but the fake is only consumed by tests where numpy is
# present. We import it at module scope here (tests/_stt_fake.py is NOT in
# the import boundary scan — that scan only covers ``app/``).
import numpy as np  # type: ignore[import-not-found]

SAMPLE_RATE = 16000


class FakeAdapter:
    """Deterministic :class:`STTAdapter` fake for chunker / CLI tests."""

    def __init__(
        self,
        segments: list | None = None,
        language: str = "en",
        language_probability: float = 0.99,
        duration: float = 30.0,
        oom_on_call: int | None = None,
        oom_above_seconds: float | None = None,
    ) -> None:
        # Lazy import to avoid a circular reference at module import time
        # (protocol.py is in the import boundary but tests/_stt_fake.py
        # is not, so importing it here is safe).
        from app.models.stt.protocol import SttSegment, SttTranscription

        self._SttSegment = SttSegment
        self._SttTranscription = SttTranscription
        # Default to a single deterministic segment matching the real
        # mock fixture's shape (start=1.0, end=3.0, text="hi").
        self._segments_cfg = segments if segments is not None else [
            SimpleNamespace(start=1.0, end=3.0, text="hi", avg_logprob=-0.1)
        ]
        self._language = language
        self._language_probability = language_probability
        self._duration = duration
        self._oom_on_call = oom_on_call
        self._oom_above_seconds = oom_above_seconds
        self.call_count = 0
        self.transcribe_calls: list = []
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def transcribe(
        self,
        audio,
        language: str | None = None,
        vad_filter: bool = True,
        condition_on_previous_text: bool = True,
    ):
        import math

        self.call_count += 1
        self.transcribe_calls.append(audio)
        # OOM-on-call mode: raise on the Nth transcribe.
        if self._oom_on_call is not None and self.call_count == self._oom_on_call:
            raise RuntimeError("CUDA failed with error out of memory")
        # OOM-on-large-window mode: raise if the audio is longer than the
        # threshold. ``audio`` may be a numpy array (chunker passes
        # pre-decoded arrays) — fall back to a no-op if it is not an
        # ndarray (e.g. a path string in CLI smoke tests).
        if self._oom_above_seconds is not None and isinstance(audio, np.ndarray):
            seconds = len(audio) / SAMPLE_RATE
            if seconds > self._oom_above_seconds:
                raise RuntimeError("CUDA failed with error out of memory")
        segments = [
            self._SttSegment(
                start_s=seg.start,
                end_s=seg.end,
                text=seg.text.strip(),
                confidence=math.exp(seg.avg_logprob),
            )
            for seg in self._segments_cfg
        ]
        return self._SttTranscription(
            segments=segments,
            language=self._language,
            language_probability=self._language_probability,
            duration=self._duration,
        )

    def detect_language(self, audio):
        return (self._language, self._language_probability)

    def unload(self) -> None:
        self.loaded = False