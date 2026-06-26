"""Windowed audio chunker with OOM split-both-halves retry (D-02, INGEST-05).

This module is a pure-Python orchestrator over the
:class:`~app.models.stt.protocol.STTAdapter` Protocol (D-06). It imports
NEITHER ``faster_whisper`` NOR ``ctranslate2`` at module top -- audio
decoding is routed through ``adapter.decode_audio(path)`` (a Protocol
method added in this plan, implemented in
:class:`~app.models.stt.adapter.FasterWhisperAdapter` via a lazy
``from faster_whisper.audio import decode_audio``) so the SC-4 grep
boundary still matches ONLY ``app/models/stt/adapter.py``.

Strategy (D-02):

- **<=30 min** (``SINGLE_CALL_THRESHOLD_SECONDS``): a single
  ``adapter.transcribe()`` call with ``condition_on_previous_text=True``
  (Pitfall 8 -- the default is fine for short audio). No offsetting, no
  dedupe -- the result is mapped straight to ``TranscriptSegment``.
- **>30 min**: ~15-min windows (``WINDOW_SECONDS``) with ~30 s overlap
  (``OVERLAP_SECONDS``). Language is detected on the first 30 s and
  passed to every chunk so the whole transcript is one language (D-07,
  INGEST-06). Each chunk is transcribed with
  ``condition_on_previous_text=False`` (Pitfall 8 planner decision --
  each chunk is independent after stitching). The chunk's
  :class:`SttSegment` timestamps are offset by the chunk's absolute
  start. Overlap dedupe drops later-chunk segments whose absolute
  ``start_s`` is before the previous chunk's absolute end (no timestamp
  mutation -- Codex HIGH stitch fix). The final merged list is assembled
  into a single :class:`~app.models.transcript.Transcript`.

**OOM split-both-halves recursive retry** (RESEARCH Pattern 3, REVISED
per Codex HIGH): when a chunk's ``transcribe()`` raises a
``RuntimeError`` matching ``"out of memory"`` (case-insensitive, Pitfall
5), the chunker SPLITS that chunk into two half-sized sub-chunks and
transcribes BOTH recursively (sub-chunking each half until it succeeds
or falls below the 60 s ``FLOOR_SECONDS`` floor). BOTH halves are always
transcribed, so the full chunk duration is covered with NO dropped
remainder -- the prior shrink-only retry dropped the second half of a
failed window (Codex HIGH correctness defect). Non-OOM
``RuntimeError``\\ s are re-raised unchanged (Pitfall 5 -- a
flash-attention / cuBLAS RuntimeError is NOT halved).

The recursion is bounded: each OOM halves ``chunk_s``, and below
``FLOOR_SECONDS`` the final attempt is allowed to raise (no catch, no
further split), so the depth is ``log2(WINDOW / FLOOR) ~= 4`` and the
call tree is finite (T-03-04 mitigation).

NOTE on full-decode memory (Codex MEDIUM): ``adapter.decode_audio(path)``
decodes the entire file once into a mono float32 16 kHz numpy array
(~115 MB per hour of audio). This is manageable for hours-long files on
both target machines. A streaming/chunked decode is a future enhancement
if very long files (> several hours) become problematic; out of scope
for this plan.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from typing import Callable, Optional

from app.jobs.errors import JobCancelled  # Fix 5: horizontal import (NOT upward into orchestrator)
from app.models.stt.protocol import (
    STTAdapter,
    ChunkProgress,
    SttSegment,
    SttTranscription,
)
from app.models.transcript import Transcript, TranscriptSegment

_log = logging.getLogger(__name__)

# Chunker constants (D-02). Imported by tests so the tests and impl agree.
WINDOW_SECONDS = 15 * 60  # 900 s -- coarse window on top of faster-whisper's 30 s
OVERLAP_SECONDS = 30  # overlap between consecutive windows
FLOOR_SECONDS = 60  # below this, an OOM is a real failure (no further split)
SAMPLE_RATE = 16000  # faster-whisper's decode_audio sample rate
SINGLE_CALL_THRESHOLD_SECONDS = 30 * 60  # 1800 s -- <=this is a single call

# Pitfall 5: match the "out of memory" substring case-insensitively. CT2
# raises ``RuntimeError`` for many non-OOM reasons (flash-attention dtype,
# cuBLAS version mismatches); the substring match is the guard that keeps
# non-OOM errors from being halved.
_OOM_RE = re.compile(r"out of memory", re.IGNORECASE)


def transcribe_file(
    adapter: STTAdapter,
    audio_path: str,
    *,
    language: Optional[str] = None,
    job_id: str = "cli",
    progress_cb: "Callable[[ChunkProgress], None] | None" = None,
    cancel_flag: "threading.Event | None" = None,
) -> Transcript:
    """Transcribe ``audio_path`` into a single :class:`Transcript` (D-02, INGEST-05).

    Decodes the audio once via ``adapter.decode_audio`` (D-01 PyAV, routed
    through the Protocol so the chunker imports no ``faster_whisper``).
    Audio <=30 min is transcribed via a single ``adapter.transcribe()``
    call (D-02 fast path). Audio >30 min is split into ~15-min windows
    with ~30 s overlap, each transcribed, then stitched into one
    continuous transcript.

    :param adapter: the STT adapter (Protocol -- never ``faster_whisper``).
    :param audio_path: path to the audio/video file (PyAV handles the
        container; the video track is ignored).
    :param language: ``None`` triggers faster-whisper auto-detect on the
        first 30 s (D-07, INGEST-06); the detected language is passed to
        every chunk and recorded on the returned :class:`Transcript`.
    :param job_id: recorded on the returned :class:`Transcript`.
    :param progress_cb: Phase 4 (D-09): optional callback invoked once
        per chunk boundary with cumulative :class:`ChunkProgress`. The
        callback is SYNC (the chunker runs off-loop in a worker thread);
        the orchestrator marshals events back to the asyncio loop via
        ``loop.call_soon_threadsafe``. ``None`` keeps the standalone
        CLI call unchanged.
    :param cancel_flag: Phase 4 (D-06): optional ``threading.Event``
        checked at the TOP of each chunk iteration. When set, the
        chunker raises :class:`JobCancelled` at the next chunk boundary
        (cooperative cancel -- stops within one chunk). ``None`` keeps
        the standalone CLI call unchanged. The orchestrator passes a
        ``threading.Event`` (NOT ``asyncio.Event``) so the flag is
        settable from the asyncio side without crossing loop boundaries.
    """
    # 1. Decode once (D-01 PyAV). The decode lives on the adapter (SC-4).
    audio = adapter.decode_audio(audio_path)
    total_samples = len(audio)
    total_seconds = total_samples / SAMPLE_RATE

    # 2. Fast path: <=30 min -> single transcribe() call.
    if total_seconds <= SINGLE_CALL_THRESHOLD_SECONDS:
        # D-06 cooperative cancel: check once before the single call. A
        # single-call fast path has no mid-call boundary, so this is the
        # only chance to observe a pre-call cancel.
        if cancel_flag is not None and cancel_flag.is_set():
            raise JobCancelled(job_id)
        result = adapter.transcribe(
            audio,
            language=language,
            vad_filter=True,
            # Pitfall 8: the default True is fine for short audio.
            condition_on_previous_text=True,
        )
        # D-09: emit one progress event covering the whole fast-path call.
        if progress_cb is not None:
            progress_cb(
                ChunkProgress(chunks_done=1, chunks_total=1, chunk_start_s=0.0)
            )
        segments = [
            TranscriptSegment(
                start_s=float(s.start_s),
                end_s=float(s.end_s),
                text=s.text,
                confidence=s.confidence,
            )
            for s in result.segments
        ]
        return Transcript(
            job_id=job_id,
            language=result.language if language is None else language,
            segments=segments,
            duration_s=total_seconds,
        )

    # 3. Chunked path: >30 min -> windowed chunks + overlap-dedupe stitch.
    # D-07: detect language on the first 30 s once, pass to every chunk.
    lang = language
    if lang is None:
        lang, _prob = adapter.detect_language(audio[: SAMPLE_RATE * 30])

    step_seconds = WINDOW_SECONDS - OVERLAP_SECONDS
    step_samples = step_seconds * SAMPLE_RATE
    window_samples = WINDOW_SECONDS * SAMPLE_RATE

    # D-09: compute the total chunk count ONCE so each progress event
    # carries a stable denominator. ``math.ceil`` matches the while-loop
    # condition (start_sample < total_samples advances by step_samples).
    # Guard against zero division -- if total_seconds == 0 the fast path
    # above already applied, so step_seconds > 0 here by construction.
    total_chunks = math.ceil(total_seconds / step_seconds) if step_seconds > 0 else 1

    merged: list[TranscriptSegment] = []
    prev_chunk_end = 0.0  # chunk 0 keeps all its segments (no prior chunk)
    chunk_count = 0
    start_sample = 0
    while start_sample < total_samples:
        # D-06 cooperative cancel (Fix 3): check at the TOP of the chunk
        # loop body BEFORE the transcribe call. The cancel_flag is a
        # threading.Event (NOT asyncio.Event) so the orchestrator's
        # asyncio side can set it without crossing loop boundaries; the
        # chunker (off-loop in a worker thread) observes it here. Raises
        # JobCancelled at the next chunk boundary -> the orchestrator
        # catches it on the awaited run_in_executor future.
        if cancel_flag is not None and cancel_flag.is_set():
            raise JobCancelled(job_id)

        chunk_audio = audio[start_sample : start_sample + window_samples]
        chunk_seconds = len(chunk_audio) / SAMPLE_RATE
        chunk_start = start_sample / SAMPLE_RATE
        chunk_count += 1

        # OOM-safe recursive transcribe (covers the FULL chunk -- Codex HIGH).
        stt = _transcribe_chunk_oom_safe(
            adapter, chunk_audio, language=lang, chunk_s=chunk_seconds
        )

        # Pattern 4 (REVISED per Codex HIGH on stitching): offset each
        # segment's start_s/end_s by the chunk's absolute start, then drop
        # later-chunk segments whose absolute start_s < prev_chunk_end
        # (the previous chunk's absolute end -- these are in the overlap
        # region already covered by the previous chunk). Keep all other
        # segments UNCHANGED (no start_s mutation -- avoids the
        # text/timestamp mismatch Codex flagged).
        for s in stt.segments:
            abs_start = float(s.start_s) + chunk_start
            abs_end = float(s.end_s) + chunk_start
            if abs_start < prev_chunk_end:
                continue  # overlap dedupe -- already covered by prev chunk
            merged.append(
                TranscriptSegment(
                    start_s=abs_start,
                    end_s=abs_end,
                    text=s.text,
                    confidence=s.confidence,
                )
            )

        # prev_chunk_end is the chunk's absolute end (chunk_start + chunk_seconds).
        prev_chunk_end = chunk_start + chunk_seconds
        start_sample += step_samples

        # D-09: emit per-chunk progress AFTER the chunk boundary closes
        # (chunk_count was just incremented). The orchestrator marshals
        # this onto the asyncio loop via call_soon_threadsafe.
        if progress_cb is not None:
            progress_cb(
                ChunkProgress(
                    chunks_done=chunk_count,
                    chunks_total=total_chunks,
                    chunk_start_s=chunk_start,
                )
            )

    _log.info(
        "STT chunker transcribed %.1f s in %d chunk(s) -> %d segment(s), language=%s",
        total_seconds,
        chunk_count,
        len(merged),
        lang,
    )
    return Transcript(job_id=job_id, language=lang, segments=merged, duration_s=total_seconds)


def _transcribe_chunk_oom_safe(
    adapter: STTAdapter,
    audio_slice: object,
    *,
    language: Optional[str],
    chunk_s: float,
) -> SttTranscription:
    """Transcribe ``audio_slice`` with OOM split-both-halves recursive retry.

    On OOM (``RuntimeError`` matching ``"out of memory"``), splits the
    slice at its midpoint and recursively transcribes BOTH halves,
    merging with the right-half offset. On non-OOM ``RuntimeError``,
    re-raises unchanged (Pitfall 5). Below ``FLOOR_SECONDS``, makes one
    final attempt and lets any ``RuntimeError`` raise (no further split).

    This is the Codex HIGH fix: BOTH halves of a failed window are
    transcribed (recursively sub-chunking each half until it succeeds),
    so the full chunk duration is covered with no dropped remainder.
    The prior shrink-only retry dropped the second half. The recursion
    is bounded: each OOM halves ``chunk_s``, and below the floor the
    final attempt raises -- depth ``log2(WINDOW / FLOOR) ~= 4`` (T-03-04).
    """
    # Pitfall 8 planner decision: chunked path -> False per chunk.
    kwargs = {
        "language": language,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }

    # Below the floor: one final attempt, let it raise (no catch).
    if chunk_s < FLOOR_SECONDS:
        return adapter.transcribe(audio_slice, **kwargs)

    try:
        return adapter.transcribe(audio_slice, **kwargs)
    except RuntimeError as exc:
        # Pitfall 5: non-OOM RuntimeError re-raised unchanged, NOT split.
        if not _OOM_RE.search(str(exc)):
            raise
        _log.warning("chunk OOM at %.1f s, splitting into halves and transcribing both", chunk_s)
        # Split at the midpoint and recursively transcribe BOTH halves.
        mid = len(audio_slice) // 2  # type: ignore[arg-type]
        left = _transcribe_chunk_oom_safe(
            adapter, audio_slice[:mid], language=language, chunk_s=chunk_s / 2
        )
        right = _transcribe_chunk_oom_safe(
            adapter, audio_slice[mid:], language=language, chunk_s=chunk_s / 2
        )
        right_offset = mid / SAMPLE_RATE  # the right half starts mid samples in
        right_segments = [
            SttSegment(
                start_s=s.start_s + right_offset,
                end_s=s.end_s + right_offset,
                text=s.text,
                confidence=s.confidence,
            )
            for s in right.segments
        ]
        return SttTranscription(
            segments=left.segments + right_segments,
            language=left.language,
            language_probability=left.language_probability,
            duration=left.duration + right.duration,
        )


__all__ = ["transcribe_file", "WINDOW_SECONDS", "OVERLAP_SECONDS", "FLOOR_SECONDS", "SAMPLE_RATE", "SINGLE_CALL_THRESHOLD_SECONDS"]