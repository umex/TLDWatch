// A single completed-job row in the history list (UI-SPEC §5, D-05).
//
// Renders the filename (derived from `source_path` as the basename),
// the creation date, and the duration. Clicking the row navigates to
// `/jobs/:id` via React Router so the detail view loads the job's
// transcript (D-06).
import { useNavigate } from "react-router"

import type { JobResponse } from "../api/jobs"

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/")
  const parts = normalized.split("/")
  return parts[parts.length - 1] || path
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return iso
  }
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "--:--"
  const total = Math.max(0, Math.floor(seconds))
  const mm = Math.floor(total / 60)
  const ss = total % 60
  return `${mm.toString().padStart(2, "0")}:${ss.toString().padStart(2, "0")}`
}

export default function HistoryRow({ job }: { job: JobResponse }) {
  const navigate = useNavigate()
  // Plan 05-04: prefer the original dropped filename (persisted from
  // X-Filename at upload time); fall back to basename(source_path) for
  // jobs created without an upload, then "unknown" when neither is set.
  const filename =
    job.original_filename ??
    (job.source_path ? basename(job.source_path) : "unknown")
  return (
    <div
      className="history-row"
      data-testid="history-row"
      onClick={() => navigate(`/jobs/${encodeURIComponent(job.id)}`)}
    >
      <span>{filename}</span>
      <span>{formatDate(job.created_at)}</span>
      <span>{formatDuration(job.duration_s)}</span>
    </div>
  )
}