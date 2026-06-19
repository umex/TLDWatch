"""Tests for ``app.models.stt.chunker`` (Phase 3 plan 03-02, INGEST-05).

Seven cases (TDD RED first, then GREEN in Task 2):

- ``test_short_audio_single_call`` (D-02 fast path, INGEST-05): audio
  <=30 min is transcribed via a single ``adapter.transcribe()`` call --
  ``FakeAdapter.call_count == 1`` and the returned ``Transcript.segments``
  match the fake's segments unchanged (no chunking, no offset).
- ``test_oom_halve_and_retry`` (RESEARCH Pitfall 5 / Codex HIGH): a
  >30 min audio with ``oom_on_call=1`` -- the first chunk's transcribe
  raises ``RuntimeError("CUDA failed with error out of memory")``;
  ``transcribe_file`` splits that chunk and retries BOTH halves; the
  test asserts the chunker eventually succeeds (>=2 transcribe calls
  for the OOMing chunk) and returns a non-empty ``Transcript``.
- ``test_oom_halve_covers_full_audio`` (Codex HIGH full-coverage fix):
  ``oom_above_seconds=420`` (7 min) over a 45-min audio chunked at
  15-min windows -- every window OOMs, is split into 7.5-min halves
  (still > 420 -> OOMs again -> split to 225 s -> succeeds); the
  assembled ``Transcript`` spans the FULL 45-min duration (first
  start_s == 0.0 AND last end_s within epsilon of 45*60). The
  split-both-halves retry covers the full duration with no dropped
  remainder (Codex HIGH fix -- the prior shrink-only retry dropped
  the second half).
- ``test_oom_non_oom_runtime_error_reraises`` (RESEARCH Pitfall 5):
  a ``RuntimeError("flash attention dtype mismatch -- cuBLAS version
  mismatch")`` (no "out of memory" substring) is re-raised unchanged --
  the chunker does NOT split on a non-OOM RuntimeError.
- ``test_stitch_offset_and_overlap_dedupe`` (D-02, INGEST-05):
  deterministic FakeAdapter over a 45-min audio with 15-min windows +
  30 s overlap -- the assembled segment timestamps are monotonically
  non-decreasing, no two segments overlap (end_s of N <= start_s of
  N+1 -- no duplicated text), the first segment's start_s == 0.0, and
  the last segment's end_s ~= 45*60 (continuous, full-coverage, no
  timestamp mutation -- Codex HIGH stitch fix).
- ``test_chunked_path_detects_language_on_first_30s`` (D-07, INGEST-06):
  ``FakeAdapter.detect_language`` returning ``("en", 0.99)`` over a
  >30 min audio -- ``transcribe_file`` calls ``detect_language`` once
  on the first 30 s slice and passes ``language="en"`` to every
  chunk's ``transcribe``.
- ``test_chunked_path_condition_on_previous_text_false`` (RESEARCH
  Pitfall 8 planner decision): the >30 min chunked path passes
  ``condition_on_previous_text=False`` to every chunk; the <=30 min
  single-call path passes ``condition_on_previous_text=True``.

The tests import the constants ``WINDOW_SECONDS``, ``OVERLAP_SECONDS``,
``FLOOR_SECONDS``, ``SAMPLE_RATE``, ``SINGLE_CALL_THRESHOLD_SECONDS`` from
``app.models.stt.chunker`` so the tests and the implementation agree on
the chunking strategy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# RED until Task 2 implements app.models.stt.chunker. The import below
# is the RED gate: pytest collects and fails on ImportError.
from app.models.stt.chunker import (  # noqa: E402
    FLOOR_SECONDS,
    OVERLAP_SECONDS,
    SAMPLE_RATE,
    SINGLE_CALL_THRESHOLD_SECONDS,
    WINDOW_SECONDS,
    transcribe_file,
)
from app.models.transcript import Transcript  # noqa: E402
from tests._stt_fake import FakeAdapter  # noqa: E402


def _long_audio(duration_min: float):
    """Return a numpy zeros array of ``duration_min`` minutes at 16 kHz mono float32."""
    import numpy as np  # type: ignore[import-not-found]

    return np.zeros(int(duration_min * 60 * SAMPLE_RATE), dtype="float32")


def _fake_adapter(
    segments_per_chunk: int = 2,
    oom_on_call: int | None = None,
    oom_above_seconds: float | None = None,
    language: str = "en",
    language_probability: float = 0.99,
) -> FakeAdapter:
    """Build a ``FakeAdapter`` yielding deterministic segments scaled per chunk.

    ``segments_per_chunk`` evenly-spaced segments are produced per
    ``transcribe()`` call, spanning the actual audio slice length (so
    the stitch test can assert offsets and the full-coverage test can
    assert end_s spans the input duration). The fake records the
    ``language`` / ``condition_on_previous_text`` kwargs per call so
    the planner-decision tests can assert on them.
    """
    return FakeAdapter(
        segments=None,
        language=language,
        language_probability=language_probability,
        duration=30.0,
        oom_on_call=oom_on_call,
        oom_above_seconds=oom_above_seconds,
        segments_per_chunk=segments_per_chunk,
    )


# ---------------------------------------------------------------------------
# Case 1: short audio <=30 min is a single adapter.transcribe() call.
# ---------------------------------------------------------------------------


def test_short_audio_single_call():
    """D-02 fast path: <=30 min audio -> single transcribe() call, no chunking."""
    adapter = _fake_adapter(segments_per_chunk=3)
    audio = _long_audio(20)  # 20 min < 30 min threshold
    # Use a fake "path" -- the FakeAdapter.decode_audio returns a zeros
    # array sized to the SAMPLE_RATE; transcribe_file calls decode_audio
    # to get the audio array, so we patch the fake's decode_audio to
    # return our 20-min array directly.
    adapter.decode_audio_result = audio
    result = transcribe_file(adapter, "ignored.wav", language="en")
    assert isinstance(result, Transcript)
    # Fast path: exactly one transcribe call (no chunking, no offset).
    assert adapter.call_count == 1
    # The single chunk's segments are not offset (chunk_start == 0).
    assert result.segments[0].start_s == pytest.approx(0.0)
    # With 3 segments spanning 20 min, each segment is ~400 s wide.
    # The last segment's end_s must equal the chunk's duration (20*60).
    assert result.segments[-1].end_s == pytest.approx(20 * 60, abs=5.0)
    assert result.language == "en"


# ---------------------------------------------------------------------------
# Case 2: OOM on the first chunk's first call -> split + retry BOTH halves.
# ---------------------------------------------------------------------------


def test_oom_halve_and_retry():
    """RESEARCH Pitfall 5 / Codex HIGH: OOM -> split chunk + retry both halves."""
    adapter = _fake_adapter(segments_per_chunk=2, oom_on_call=1)
    adapter.decode_audio_result = _long_audio(45)  # 45 min, 3 chunks
    result = transcribe_file(adapter, "ignored.wav", language="en")
    assert isinstance(result, Transcript)
    # The first chunk was called at least twice: the initial OOMing
    # call (call_count == 1 -> raises) plus the retries on the split
    # halves. After the first OOM, oom_on_call is exhausted (it only
    # triggers at call_count == 1), so the halves succeed.
    assert adapter.call_count >= 2
    # Final transcript is non-empty (split-both-halves covered the chunk).
    assert len(result.segments) > 0


# ---------------------------------------------------------------------------
# Case 3: OOM above threshold -> recursive halving covers the FULL audio.
# ---------------------------------------------------------------------------


def test_oom_halve_covers_full_audio():
    """Codex HIGH full-coverage: recursive halving drops no remainder.

    With ``oom_above_seconds=420`` (7 min), every 15-min (900 s) window
    OOMs and is recursively split: 900 -> 450 (still > 420 -> OOMs) ->
    225 (below 420 -> succeeds). The split-both-halves retry covers
    the FULL 45-min duration with no dropped remainder -- the prior
    shrink-only retry dropped the second half of a failed window.
    """
    # segments_per_chunk=60 -> small (~15 s / 3.75 s) segments so the
    # overlap-dedupe drops ONLY segments fully inside the overlap region
    # (mirrors real Whisper's ~5-30 s segments). With 1 large segment per
    # sub-chunk, the dedupe would over-drop and the gap check below would
    # fail at chunk boundaries.
    adapter = _fake_adapter(segments_per_chunk=60, oom_above_seconds=420)
    adapter.decode_audio_result = _long_audio(45)  # 45 min
    result = transcribe_file(adapter, "ignored.wav", language="en")
    assert isinstance(result, Transcript)
    segs = result.segments
    assert len(segs) > 0
    # First segment starts at 0.0 (no dropped prefix).
    assert segs[0].start_s == pytest.approx(0.0, abs=1e-6)
    # Last segment end_s ~= 45*60 (full coverage -- Codex HIGH assertion).
    # Tolerance of 10 s allows for the final chunk's tail width.
    assert segs[-1].end_s >= 45 * 60 - 10, (
        f"last end_s={segs[-1].end_s} did not cover full 45 min (expected ~ {45 * 60})"
    )
    # Monotonic coverage: no gap larger than the overlap window (30 s)
    # between consecutive segments at chunk boundaries.
    for prev, nxt in zip(segs, segs[1:]):
        # start_s is non-decreasing.
        assert nxt.start_s >= prev.start_s - 1e-6, (
            f"segments not monotonic: prev.start_s={prev.start_s} > nxt.start_s={nxt.start_s}"
        )
        # No gap larger than the overlap window (coverage continuity).
        gap = nxt.start_s - prev.end_s
        assert gap <= OVERLAP_SECONDS + 1e-6, (
            f"gap {gap}s > overlap {OVERLAP_SECONDS}s between segments"
        )


# ---------------------------------------------------------------------------
# Case 4: non-OOM RuntimeError is re-raised unchanged (no split).
# ---------------------------------------------------------------------------


def test_oom_non_oom_runtime_error_reraises():
    """RESEARCH Pitfall 5: a non-OOM RuntimeError is re-raised, NOT split."""
    # Build a FakeAdapter whose transcribe always raises a non-OOM
    # RuntimeError (no "out of memory" substring).
    adapter = FakeAdapter(
        segments=None,
        language="en",
        language_probability=0.99,
        duration=30.0,
        oom_on_call=None,
        oom_above_seconds=None,
        segments_per_chunk=2,
    )
    adapter.transcribe_side_effect = RuntimeError(
        "flash attention dtype mismatch -- cuBLAS version mismatch"
    )
    adapter.decode_audio_result = _long_audio(20)  # 20 min -> single call path
    with pytest.raises(RuntimeError, match="cuBLAS version mismatch"):
        transcribe_file(adapter, "ignored.wav", language="en")
    # The chunker did NOT split -- the single-call path made exactly
    # one transcribe() call before re-raising.
    assert adapter.call_count == 1


# ---------------------------------------------------------------------------
# Case 5: stitch offsets segments + overlap-dedupe (no timestamp mutation).
# ---------------------------------------------------------------------------


def test_stitch_offset_and_overlap_dedupe():
    """D-02, INGEST-05: stitched segments are monotonic, non-overlapping, full-coverage."""
    # segments_per_chunk=60 -> ~15 s segments per 900 s chunk (and ~1.5 s
    # per 90 s last chunk), so the overlap-dedupe drops only the segments
    # fully inside the 30 s overlap region -- mirrors real Whisper's
    # small segments and gives clean contiguous coverage (gap == 0 at
    # chunk boundaries, no over-drop).
    adapter = _fake_adapter(segments_per_chunk=60)  # small segments per chunk
    adapter.decode_audio_result = _long_audio(45)  # 45 min, 15-min windows + 30 s overlap
    result = transcribe_file(adapter, "ignored.wav", language="en")
    assert isinstance(result, Transcript)
    segs = result.segments
    assert len(segs) > 0
    # First segment starts at 0.0 (chunk 0 keeps all its segments).
    assert segs[0].start_s == pytest.approx(0.0, abs=1e-6)
    # Last segment end_s ~= 45*60 (full coverage).
    assert segs[-1].end_s == pytest.approx(45 * 60, abs=10.0)
    # Monotonically non-decreasing start_s.
    for prev, nxt in zip(segs, segs[1:]):
        assert nxt.start_s >= prev.start_s - 1e-6, (
            f"start_s not monotonic: {prev.start_s} -> {nxt.start_s}"
        )
        # No two segments overlap (end_s of N <= start_s of N+1).
        assert prev.end_s <= nxt.start_s + 1e-6, (
            f"segments overlap: prev.end_s={prev.end_s} > nxt.start_s={nxt.start_s}"
        )


# ---------------------------------------------------------------------------
# Case 6: chunked path detects language on the first 30 s, passes to all chunks.
# ---------------------------------------------------------------------------


def test_chunked_path_detects_language_on_first_30s():
    """D-07, INGEST-06: detect_language is called once on the first 30 s."""
    adapter = _fake_adapter(segments_per_chunk=2, language="es", language_probability=0.95)
    adapter.decode_audio_result = _long_audio(45)  # 45 min -> chunked path
    # language=None triggers the first-30 s detect path.
    result = transcribe_file(adapter, "ignored.wav", language=None)
    assert isinstance(result, Transcript)
    # detect_language called exactly once (on the first 30 s).
    assert adapter.detect_language_call_count == 1
    # Every chunk's transcribe received the detected language.
    assert len(adapter.transcribe_kwargs) > 0
    for kwargs in adapter.transcribe_kwargs:
        assert kwargs.get("language") == "es"
    assert result.language == "es"


# ---------------------------------------------------------------------------
# Case 7: condition_on_previous_text=False per chunk; True for the fast path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("duration_min,expected", [
    (45, False),  # >30 min chunked path -> condition_on_previous_text=False
    (20, True),   # <=30 min single-call path -> condition_on_previous_text=True
])
def test_chunked_path_condition_on_previous_text_false(duration_min, expected):
    """RESEARCH Pitfall 8 planner decision: per-path condition_on_previous_text."""
    adapter = _fake_adapter(segments_per_chunk=2)
    adapter.decode_audio_result = _long_audio(duration_min)
    transcribe_file(adapter, "ignored.wav", language="en")
    assert len(adapter.transcribe_kwargs) > 0
    for kwargs in adapter.transcribe_kwargs:
        assert kwargs.get("condition_on_previous_text") is expected, (
            f"duration={duration_min}min: expected condition_on_previous_text={expected}, "
            f"got {kwargs.get('condition_on_previous_text')}"
        )