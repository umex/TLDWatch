// Detail page at /jobs/:id (D-04, D-06, D-07, D-08, UI-SPEC §5/§6).
//
// Renders a header with a "Back to History" link (React Router `<Link>`)
// and the disabled ExportStub, then the 2-pane `.detail-layout` grid:
// transcript (left, 60%) | summary (right, 40%). The transcript is
// fetched via `useTranscript(id)` (05-02a); when the job has no
// transcript yet (404 -> TRANSCRIBING sentinel, D-14) the TranscriptPane
// shows the "Transcribing..." state. No embedded media player element
// anywhere (UI-02). Clicking a history row navigates here (UI-SPEC §5).
import { Link, useParams } from "react-router"

import { useTranscript } from "../api/jobs"
import TranscriptPane from "../components/TranscriptPane"
import SummaryPane from "../components/SummaryPane"
import ExportStub from "../components/ExportStub"

export default function DetailPage() {
  const { id } = useParams()
  const { data } = useTranscript(id ?? null)

  return (
    <div data-testid="detail-page">
      <header
        style={{
          display: "flex",
          gap: "var(--space-md)",
          alignItems: "center",
          padding: "var(--space-md)",
        }}
      >
        <Link to="/" className="btn">
          ← Back to History
        </Link>
        <ExportStub />
      </header>
      <div className="detail-layout">
        <TranscriptPane transcript={data} />
        <SummaryPane />
      </div>
    </div>
  )
}