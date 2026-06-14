"""Round-trip and validation tests for the transcript Pydantic models.

Lax-for-output (D-15): the models must deserialise a JSON
representation of any existing ``transcript.json`` without
complaining about missing optional fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.transcript import Transcript, TranscriptSegment


def test_roundtrip_transcript_segment() -> None:
    seg = TranscriptSegment(start_s=0.0, end_s=1.5, text="hello world")
    dumped = seg.model_dump_json()
    restored = TranscriptSegment.model_validate_json(dumped)
    assert restored.start_s == 0.0
    assert restored.end_s == 1.5
    assert restored.text == "hello world"
    assert restored.speaker is None
    assert restored.confidence is None


def test_transcript_segment_with_speaker_and_confidence() -> None:
    seg = TranscriptSegment(
        start_s=1.0,
        end_s=2.5,
        text="hi there",
        speaker="S1",
        confidence=0.95,
    )
    assert seg.speaker == "S1"
    assert seg.confidence == 0.95


def test_transcript_default_segments_is_empty() -> None:
    t = Transcript(job_id="abc")
    assert t.segments == []
    assert t.language is None
    assert t.schema_version == 1


def test_transcript_roundtrip() -> None:
    t = Transcript(
        job_id="abc",
        language="en",
        segments=[
            TranscriptSegment(start_s=0.0, end_s=1.0, text="a"),
            TranscriptSegment(start_s=1.0, end_s=2.0, text="b", speaker="S1"),
        ],
    )
    restored = Transcript.model_validate_json(t.model_dump_json())
    assert restored.job_id == "abc"
    assert restored.language == "en"
    assert len(restored.segments) == 2
    assert restored.segments[1].speaker == "S1"


def test_transcript_segment_rejects_bad_types() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(start_s="not-a-float", end_s=1.0, text="x")
    with pytest.raises(ValidationError):
        TranscriptSegment(start_s=0.0, end_s=1.0)  # missing required text
