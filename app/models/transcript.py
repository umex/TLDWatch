"""Pydantic models for the on-disk ``transcript.json`` file (D-05, D-15).

These are the typed shapes that the STT adapter (Phase 3) writes to
disk and that every downstream consumer (diarization, summarization,
editor) reads. They are **lax for output / internal storage** (D-15):
deserialising existing files should never fail because of a strict
mode mismatch with a future field. New fields added in later phases
must be optional or have a default to preserve backward compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single timed chunk of the transcript.

    ``speaker`` and ``confidence`` are optional because the STT stage
    (Phase 3) may not know the speaker at transcription time (that is
    filled in by the diarization stage, Phase 7) and not every STT
    backend emits a per-segment confidence score.
    """

    start_s: float
    end_s: float
    text: str
    speaker: str | None = None
    confidence: float | None = None


class Transcript(BaseModel):
    """The full transcript for a single job.

    The list of ``segments`` is the canonical payload; the rest of the
    fields are metadata that downstream stages or the UI may want
    without re-parsing the segment list.
    """

    schema_version: int = 1
    job_id: str
    language: str | None = None
    # 05-07: source MEDIA duration in seconds (chunker total_seconds =
    # len(audio)/SAMPLE_RATE). Additive, optional, default None so
    # existing transcript.json files load without failing (the model is
    # lax for output / internal storage per the module docstring). This
    # is the same semantic as the failed-jobs 00:42 the user observed --
    # the field is colocated with source_sha256/source_path (media
    # metadata), NOT wall-clock processing time.
    duration_s: float | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)


__all__ = ["Transcript", "TranscriptSegment"]
