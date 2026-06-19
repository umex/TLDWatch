"""Tests for ``FasterWhisperAdapter`` (Phase 3 plan 03-01).

Cases:

- ``test_segment_mapping`` (TRANS-01): faster-whisper
  ``Segment{start,end,text,avg_logprob}`` maps to
  ``SttSegment{start_s,end_s,text,confidence}`` with
  ``confidence = exp(avg_logprob)`` (a PROXY, not a calibrated
  probability — see adapter docstring).
- ``test_language_autodetect_recorded`` (INGEST-06): ``language=None``
  triggers faster-whisper auto-detect and the detected language +
  probability are recorded on :class:`SttTranscription`.
- ``test_int8_verification_fails_loud`` (D-08 negative): a mock WhisperModel
  whose ``.model.compute_type`` returns ``"float32"`` while
  ``requested="int8_float16"`` -> ``load()`` raises ``RuntimeError``
  matching ``"int8 verification failed"`` (the silent-fallback fail-loud
  path).
- ``test_int8_equivalence_accepted`` (D-08 positive): a mock WhisperModel
  whose ``.model.compute_type`` returns ``"int8_float16"`` while
  ``requested="int8"`` -> ``load()`` does NOT raise (the documented CUDA
  ``int8 -> int8_float16`` substitution is accepted by ``_ACCEPTED``).
  Also asserts ``requested="int8_float16"`` + ``actual="int8_float16"`` is
  accepted.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest


def _adapter(mock_stt_adapter, model_path="/fake/model", device="cuda", compute_type="int8_float16"):
    """Build a ``FasterWhisperAdapter`` under the ``mock_stt_adapter`` seam."""
    from app.models.stt.adapter import FasterWhisperAdapter

    return FasterWhisperAdapter(model_path=model_path, device=device, compute_type=compute_type)


def test_segment_mapping(mock_stt_adapter, fake_audio_array):
    """TRANS-01: Segment{start,end,text,avg_logprob} -> SttSegment mapping."""
    adapter = _adapter(mock_stt_adapter, compute_type="int8_float16")
    adapter.load()
    result = adapter.transcribe(fake_audio_array, language=None)
    assert len(result.segments) == 1
    seg = result.segments[0]
    assert seg.start_s == pytest.approx(1.0)
    assert seg.end_s == pytest.approx(3.0)
    assert seg.text == "hi"
    # confidence = exp(avg_logprob) -- a proxy, not a calibrated probability.
    assert seg.confidence == pytest.approx(math.exp(-0.1))


def test_language_autodetect_recorded(mock_stt_adapter, fake_audio_array):
    """INGEST-06: language=None records faster-whisper's detected language."""
    adapter = _adapter(mock_stt_adapter, compute_type="int8_float16")
    adapter.load()
    result = adapter.transcribe(fake_audio_array, language=None)
    assert result.language == "en"
    assert result.language_probability == pytest.approx(0.99)


def test_int8_verification_fails_loud(mock_stt_adapter, fake_audio_array):
    """D-08 negative: silent float32 fallback fails loud on load.

    The mock WhisperModel's ``.model.compute_type`` returns ``"float32"``
    while ``requested="int8_float16"``. ``load()`` MUST raise a
    ``RuntimeError`` whose message contains ``"int8 verification failed"``
    so a silent fallback (Phase 2 Pitfall 12 analogue) can never pass
    unnoticed.
    """
    # Override the mock's compute_type to simulate the silent fallback.
    mock_stt_adapter.compute_type = "float32"
    adapter = _adapter(mock_stt_adapter, compute_type="int8_float16")
    with pytest.raises(RuntimeError, match="int8 verification failed"):
        adapter.load()


def test_int8_equivalence_accepted(mock_stt_adapter, fake_audio_array):
    """D-08 positive: the documented CUDA int8 -> int8_float16 substitution is accepted.

    ``requested="int8"`` + ``actual="int8_float16"`` MUST NOT raise (no false
    positive). Also verifies ``requested="int8_float16"`` +
    ``actual="int8_float16"`` is accepted.
    """
    # requested=int8, actual=int8_float16 (the documented CUDA substitution).
    mock_stt_adapter.compute_type = "int8_float16"
    adapter = _adapter(mock_stt_adapter, compute_type="int8")
    adapter.load()  # must not raise

    # requested=int8_float16, actual=int8_float16 (exact match).
    adapter2 = _adapter(mock_stt_adapter, compute_type="int8_float16")
    adapter2.load()  # must not raise