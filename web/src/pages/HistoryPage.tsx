// History landing page at / (D-04, UI-SPEC §5).
//
// Task 1 of 05-02b ships a minimal shell: placeholders for the drop area
// and the active-job card list (Task 2 composes DropZone + ActiveJobCard
// list + HistoryList into this page), plus the empty-state copy
// "No Transcripts Yet" when there are no completed jobs (UI-SPEC
// Copywriting Contract).
//
// Task 2 replaces the placeholders with the real DropZone + active cards
// + HistoryList. The route wiring (`/` -> HistoryPage) lives in App.tsx.
import { useJobs } from "../api/jobs"

export default function HistoryPage() {
  // Terminal jobs only (D-05). Task 2's HistoryList consumes the same
  // query; this early read just powers the empty-state copy.
  const { data } = useJobs("done")
  const hasJobs = !!data && data.length > 0

  return (
    <div data-testid="history-page" style={{ padding: "var(--space-xl)" }}>
      {/* DropZone wired in Task 2 (D-01: dedicated drop area at top). */}
      <div
        data-testid="drop-area"
        className="drop-zone"
        style={{ minHeight: "120px", marginBottom: "var(--space-lg)" }}
      />
      {/* ActiveJobCard list wired in Task 2 (D-03: live cards near drop). */}
      <div
        data-testid="active-cards"
        style={{ marginBottom: "var(--space-lg)" }}
      />
      {/* HistoryList wired in Task 2. Empty state shown until then. */}
      {!hasJobs && (
        <section data-testid="history-empty" className="history-empty">
          <h1 style={{ fontSize: "var(--fs-heading)", fontWeight: 700 }}>
            No Transcripts Yet
          </h1>
          <p style={{ color: "var(--text-muted)" }}>
            Drag and drop video files here or click the upload area to start
            transcribing.
          </p>
        </section>
      )}
    </div>
  )
}