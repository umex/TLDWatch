// History landing page at / (D-04, UI-SPEC §5).
//
// Composes the three regions of the landing page:
//   1. DropZone (top) -- the dedicated drop area + full-window overlay
//      (D-01). Each completed upload emits a jobId upward.
//   2. ActiveJobCard list -- the live cards for the jobIds DropZone
//      created (D-03: active jobs near the drop area, NOT in history).
//      On a terminal WS event the card fades out and removes itself.
//   3. HistoryList -- the completed (terminal) jobs below (D-05).
import { useState } from "react"

import ActiveJobCard from "../components/ActiveJobCard"
import DropZone from "../components/DropZone"
import HistoryList from "../components/HistoryList"

export default function HistoryPage() {
  const [activeJobIds, setActiveJobIds] = useState<string[]>([])

  const handleJobCreated = (jobId: string) => {
    setActiveJobIds((prev) =>
      prev.includes(jobId) ? prev : [...prev, jobId],
    )
  }
  const handleTerminal = (jobId: string) => {
    setActiveJobIds((prev) => prev.filter((id) => id !== jobId))
  }

  return (
    <div data-testid="history-page" style={{ padding: "var(--space-xl)" }}>
      <DropZone onJobCreated={handleJobCreated} />
      <div
        data-testid="active-cards"
        style={{ marginTop: "var(--space-lg)" }}
      >
        {activeJobIds.map((id) => (
          <ActiveJobCard key={id} jobId={id} onTerminal={handleTerminal} />
        ))}
      </div>
      <HistoryList />
    </div>
  )
}