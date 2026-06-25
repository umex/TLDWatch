// The left pane of the 2-pane detail view (D-07, UI-SPEC §4/§6).
//
// Renders one TranscriptRow per TranscriptSegment inside the scrollable
// `.transcript-pane` container. Each row gets the id `seg-{index}` which
// 05-03's scroll-spy observes via IntersectionObserver (UI-03 active-line
// highlight; the `active` class is wired there, not here).
//
// When the transcript is not ready (useTranscript returns the TRANSCRIBING
// sentinel on 404, or undefined while loading) the pane shows the
// "Transcribing..." state per UI-SPEC §6.
import type { Transcript } from "../api/jobs"
import { TRANSCRIBING } from "../api/jobs"

import TranscriptRow from "./TranscriptRow"

interface TranscriptPaneProps {
  transcript: Transcript | typeof TRANSCRIBING | undefined
}

export default function TranscriptPane({ transcript }: TranscriptPaneProps) {
  if (!transcript || transcript === TRANSCRIBING) {
    return (
      <div className="transcript-pane" data-testid="transcript-pane">
        <p data-testid="transcribing-state">Transcribing...</p>
      </div>
    )
  }

  const segments = transcript.segments ?? []
  return (
    <div className="transcript-pane" data-testid="transcript-pane">
      {segments.map((seg, i) => (
        <TranscriptRow key={i} segment={seg} index={i} />
      ))}
    </div>
  )
}