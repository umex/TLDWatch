// The left pane of the 2-pane detail view (D-07, UI-SPEC §4/§6).
//
// Renders one TranscriptRow per TranscriptSegment inside the scrollable
// `.transcript-pane` container. Each row gets the id `seg-{index}` which
// the `useScrollSpy` IntersectionObserver (UI-03 active-line highlight)
// observes. The active row's `active` prop is driven by the `activeId`
// returned from `useScrollSpy` so the `.active` class (4px #2563EB left
// border + rgba(37,99,235,0.05) tint, defined in 05-02a styles.css)
// applies to the row nearest the viewport center (D-09, local files
// only).
//
// When the transcript is not ready (useTranscript returns the TRANSCRIBING
// sentinel on 404, or undefined while loading) the pane shows the
// "Transcribing..." state per UI-SPEC §6.
import { useMemo, useRef } from "react"

import type { Transcript } from "../api/jobs"
import { TRANSCRIBING } from "../api/jobs"
import { useScrollSpy } from "../hooks/useScrollSpy"

import TranscriptRow from "./TranscriptRow"

interface TranscriptPaneProps {
  transcript: Transcript | typeof TRANSCRIBING | undefined
}

export default function TranscriptPane({ transcript }: TranscriptPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const isReady = !!transcript && transcript !== TRANSCRIBING
  const segments = isReady ? (transcript as Transcript).segments ?? [] : []
  const segmentIds = useMemo(
    () => segments.map((_, i) => `seg-${i}`),
    [segments],
  )
  // Hooks must be called unconditionally (Rules of Hooks). When the
  // transcript is not ready, `segmentIds` is empty so `useScrollSpy`
  // early-returns and no observer is created.
  const activeId = useScrollSpy(containerRef, segmentIds)

  if (!isReady) {
    return (
      <div className="transcript-pane" data-testid="transcript-pane">
        <p data-testid="transcribing-state">Transcribing...</p>
      </div>
    )
  }

  return (
    <div className="transcript-pane" ref={containerRef} data-testid="transcript-pane">
      {segments.map((seg, i) => (
        <TranscriptRow
          key={i}
          segment={seg}
          index={i}
          active={activeId === `seg-${i}`}
        />
      ))}
    </div>
  )
}