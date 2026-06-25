// A single transcript segment row (UI-SPEC §4, D-07).
//
// CSS Grid row: 64px timestamp | 80px speaker gutter | 1fr body.
// The timestamp is formatted as `[mm:ss]` (zero-padded). The 80px speaker
// gutter is left empty — Phase 7 fills it with a speaker label
// (TranscriptSegment.speaker is `None` until then). The body is rendered
// as a normal React child so the text is auto-escaped (T-05-07
// mitigation: the unescaped-HTML API is never used anywhere in the FE).
//
// The optional `active` prop applies the `.active` class — 05-03's
// scroll-spy (UI-03) flips it on the row nearest the viewport anchor.
// Default is false here; 05-03 wires the IntersectionObserver driver.
import type { TranscriptSegment } from "../api/jobs"

interface TranscriptRowProps {
  segment: TranscriptSegment
  index: number
  active?: boolean
}

/** Format a start_s offset as `[mm:ss]` with zero-padded minutes/seconds. */
export function formatTimestamp(startS: number): string {
  const total = Math.max(0, Math.floor(startS))
  const mm = Math.floor(total / 60)
  const ss = total % 60
  return `[${mm.toString().padStart(2, "0")}:${ss.toString().padStart(2, "0")}]`
}

export default function TranscriptRow({
  segment,
  index,
  active = false,
}: TranscriptRowProps) {
  return (
    <div
      id={`seg-${index}`}
      className={`transcript-row${active ? " active" : ""}`}
      data-testid="transcript-row"
    >
      <span className="timestamp">{formatTimestamp(segment.start_s)}</span>
      {/* Reserved 80px speaker gutter — Phase 7 fills this. */}
      <span className="speaker" />
      <span className="body">{segment.text}</span>
    </div>
  )
}