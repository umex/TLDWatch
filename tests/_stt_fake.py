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

Two segment-emission modes are supported:

- ``segments`` (the original 03-01 mode): a fixed list of
  :class:`SimpleNamespace` (``start`` / ``end`` / ``text`` /
  ``avg_logprob``) returned unchanged on every call (used by 03-01's
  adapter tests).
- ``segments_per_chunk`` (added in 03-02 for the chunker tests): when
  set, ``transcribe()`` emits N evenly-spaced :class:`SttSegment` spanning
  the actual audio slice length (so the stitch test can assert offsets and
  the full-coverage test can assert end_s spans the input duration --
  mirrors real Whisper's small ~5-30 s segments).

``call_count``, ``transcribe_calls`` and ``transcribe_kwargs`` are exposed
for chunker tests that assert the chunker split a long audio window into
sub-threshold pieces and passed the right per-chunk kwargs (language,
condition_on_previous_text). ``detect_language_call_count`` is exposed for
the first-30 s language-detect test (D-07). ``transcribe_side_effect`` and
``decode_audio_result`` are test knobs for the non-OOM re-raise test and
for injecting a pre-decoded audio array without hitting PyAV.

03-02 additions: ``decode_audio`` (Protocol method), ``segments_per_chunk``
mode, ``transcribe_kwargs`` recording, ``detect_language_call_count``,
``transcribe_side_effect``, ``decode_audio_result``.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Callable

from app.jobs.errors import JobCancelled  # Phase 4: fakes import from the neutral module (Fix 5)
from app.models.stt.protocol import ChunkProgress  # Phase 4: progress callback payload

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
        segments_per_chunk: int | None = None,
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
        self._segments_per_chunk = segments_per_chunk
        self.call_count = 0
        self.transcribe_calls: list = []
        # 03-02: record per-call kwargs so the chunker tests can assert
        # the chunker passed the right language / condition_on_previous_text
        # to every chunk (D-07, Pitfall 8 planner decision).
        self.transcribe_kwargs: list[dict] = []
        self.detect_language_call_count = 0
        self.loaded = False
        # 03-02 test knobs (mutated by tests via attribute assignment).
        # ``transcribe_side_effect``: if set, ``transcribe`` raises this
        # instead of its normal behavior (used by the non-OOM re-raise
        # test -- a RuntimeError without the "out of memory" substring).
        self.transcribe_side_effect: BaseException | None = None
        # ``decode_audio_result``: if set, ``decode_audio`` returns this
        # instead of synthesizing a zeros array (lets the chunker tests
        # inject a pre-built long-audio array without hitting PyAV).
        self.decode_audio_result: object | None = None

    def load(self) -> None:
        self.loaded = True

    def transcribe(
        self,
        audio,
        language: str | None = None,
        vad_filter: bool = True,
        condition_on_previous_text: bool = True,
        *,
        progress_cb: "Callable[[ChunkProgress], None] | None" = None,
        cancel_flag: "threading.Event | None" = None,
    ):
        import math

        self.call_count += 1
        self.transcribe_calls.append(audio)
        self.transcribe_kwargs.append(
            {
                "language": language,
                "vad_filter": vad_filter,
                "condition_on_previous_text": condition_on_previous_text,
            }
        )
        # Non-OOM side-effect knob (test_oom_non_oom_runtime_error_reraises).
        # Recorded BEFORE the raise so call_count reflects the attempt.
        if self.transcribe_side_effect is not None:
            raise self.transcribe_side_effect
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

        # Phase 4 D-06: cooperative cancel. The FakeAdapter honors the
        # cancel flag between "chunks" -- here that means before emitting
        # the result. The chunker's own loop also checks cancel_flag at
        # the loop top; this in-adapter check lets a single-call fast
        # path (no chunker loop) observe a pre-call cancel too, mirroring
        # the chunker's fast-path guard.
        if cancel_flag is not None and cancel_flag.is_set():
            # job_id is not threaded through to the adapter; use a stable
            # sentinel -- the orchestrator's tests observe JobCancelled
            # via the chunker path, not via this in-adapter raise.
            raise JobCancelled("fake-adapter")

        # segments_per_chunk mode (03-02): emit N evenly-spaced segments
        # spanning the actual audio slice length. Mirrors real Whisper's
        # small segments so the chunker's overlap-dedupe drops only the
        # segments fully inside the overlap region (no over-drop).
        if self._segments_per_chunk is not None and isinstance(audio, np.ndarray):
            chunk_seconds = len(audio) / SAMPLE_RATE
            if chunk_seconds <= 0 or self._segments_per_chunk <= 0:
                segments = []
            else:
                step = chunk_seconds / self._segments_per_chunk
                segments = [
                    self._SttSegment(
                        start_s=i * step,
                        end_s=(i + 1) * step,
                        text=f"seg {i}",
                        confidence=0.9,
                    )
                    for i in range(self._segments_per_chunk)
                ]
            # Phase 4 D-09: emit one progress event per chunk the fake
            # "transcribes". The fake does not chunk further itself, so
            # chunks_done == chunks_total == 1 per call -- the chunker
            # loop emits the cumulative progress; this per-call emit is
            # a test knob so a test can assert the adapter saw the
            # progress_cb (used by the orchestrator's cancel test).
            if progress_cb is not None:
                progress_cb(
                    ChunkProgress(chunks_done=1, chunks_total=1, chunk_start_s=0.0)
                )
            return self._SttTranscription(
                segments=segments,
                language=self._language,
                language_probability=self._language_probability,
                duration=chunk_seconds,
            )

        # Original 03-01 mode: fixed configured segments (Segment ->
        # SttSegment mapping with confidence = exp(avg_logprob)).
        segments = [
            self._SttSegment(
                start_s=seg.start,
                end_s=seg.end,
                text=seg.text.strip(),
                confidence=math.exp(seg.avg_logprob),
            )
            for seg in self._segments_cfg
        ]
        if progress_cb is not None:
            progress_cb(
                ChunkProgress(chunks_done=1, chunks_total=1, chunk_start_s=0.0)
            )
        return self._SttTranscription(
            segments=segments,
            language=self._language,
            language_probability=self._language_probability,
            duration=self._duration,
        )

    def detect_language(self, audio):
        self.detect_language_call_count += 1
        return (self._language, self._language_probability)

    def decode_audio(self, path: str):
        """03-02 Protocol addition: return a pre-set array or a zeros stub.

        If ``decode_audio_result`` is set, return it (lets chunker tests
        inject a pre-built long-audio array without hitting PyAV).
        Otherwise return a 30 s silence zeros array (the default stub).
        """
        if self.decode_audio_result is not None:
            return self.decode_audio_result
        return np.zeros(SAMPLE_RATE * 30, dtype="float32")

    def unload(self) -> None:
        self.loaded = False