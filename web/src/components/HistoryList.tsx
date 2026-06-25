// Completed-jobs history list (D-05, UI-SPEC §5/§6).
//
// Renders terminal jobs (done + failed + cancelled) newest-first, one
// HistoryRow per job. The API `GET /jobs?status=` filter is
// single-valued, so the three terminal statuses are fetched with three
// `useJobs(status)` calls and merged client-side, re-sorted newest-first
// by `created_at` (the API already sorts newest-first within a status).
// When the merged list is empty the UI-SPEC Copywriting Contract
// empty-state copy "No Transcripts Yet" is shown.
import { useJobs } from "../api/jobs"
import type { JobResponse } from "../api/jobs"

import HistoryRow from "./HistoryRow"

export default function HistoryList() {
  const done = useJobs("done")
  const failed = useJobs("failed")
  const cancelled = useJobs("cancelled")
  const all: JobResponse[] = [
    ...(done.data ?? []),
    ...(failed.data ?? []),
    ...(cancelled.data ?? []),
  ].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))

  if (all.length === 0) {
    return (
      <section data-testid="history-empty" className="history-empty">
        <h1 style={{ fontSize: "var(--fs-heading)", fontWeight: 700 }}>
          No Transcripts Yet
        </h1>
        <p style={{ color: "var(--text-muted)" }}>
          Drag and drop video files here or click the upload area to start
          transcribing.
        </p>
      </section>
    )
  }

  return (
    <section data-testid="history-list" className="history-list">
      {all.map((job) => (
        <HistoryRow key={job.id} job={job} />
      ))}
    </section>
  )
}