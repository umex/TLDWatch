// Native WebSocket hook for per-job progress events (Phase 4 D-08).
// Connects to `ws://localhost:8000/ws/jobs/{jobId}/events`, parses the
// snapshot-on-connect + live event stream, and returns the latest event.
// Cleans up on unmount. The event shapes are defined in
// app/api/routes_ws.py (snapshot) + app/jobs/orchestrator.py (live).
//
// The back-end WS endpoint already ships (Phase 4); the FE just connects.

import { useEffect, useState } from "react"

import type { JobStatus } from "./jobs"

/** WebSocket base URL (matches API_BASE in client.ts but ws:// scheme). */
const WS_BASE = "ws://localhost:8000"

/** Discriminated union of the per-job WS events the back-end emits. */
export type JobEvent =
  | { type: "snapshot"; job_id: string; stage: string | null; percent: number; eta: number | null; status: JobStatus }
  | { type: "progress"; chunks_done: number; chunks_total: number; percent: number; eta_s: number | null; chunk_start_s: number }
  | { type: "stage_changed"; stage: string }
  | { type: "done" }
  | { type: "failed"; error: string }
  | { type: "cancelled" }
  | { type: "error"; code: string }

/**
 * Subscribe to the live event stream for a single job.
 *
 * @param jobId the job id to subscribe to, or `null` to stay disconnected
 * (e.g. no active card mounted). On `jobId` change the previous socket
 * is closed and a new one opened. The latest received event is returned
 * (or `null` before the first `snapshot` arrives).
 */
export function useJobEvents(jobId: string | null): JobEvent | null {
  const [event, setEvent] = useState<JobEvent | null>(null)

  useEffect(() => {
    if (!jobId) {
      setEvent(null)
      return
    }
    setEvent(null)
    const url = `${WS_BASE}/ws/jobs/${encodeURIComponent(jobId)}/events`
    const ws = new WebSocket(url)
    ws.onmessage = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data) as JobEvent
        setEvent(parsed)
      } catch {
        // Ignore malformed frames; the back-end always sends valid JSON.
      }
    }
    ws.onerror = () => {
      // Surface a synthetic error event so callers can react to drops.
      setEvent({ type: "error", code: "ws_error" })
    }
    return () => {
      ws.close()
    }
  }, [jobId])

  return event
}