// Active-job card (D-03, UI-SPEC §2, Phase 4 D-08/D-09).
//
// Subscribes to `/ws/jobs/{id}/events` via the 05-02a `useJobEvents`
// hook and renders the lifecycle states from the snapshot + live
// events:
//   - queued  -> gray "In Queue" badge
//   - ingesting -> progress bar "Ingesting File... X%"
//   - transcribing -> "Transcribing... X% (ETA: MM:SS)" (ETA hidden
//     until >=2 chunks per Phase 4 D-09)
//   - done/failed/cancelled -> fade-out (.active-card transition from
//     05-02a styles.css) + invalidateJobs so the history list refetches
//     and the job appears in the completed list (D-03 terminal
//     transition). On failure the soft red border + UI-SPEC §6 error
//     copy is shown before the fade-out.
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { invalidateJobs } from "../api/jobs"
import { useJobEvents } from "../api/ws"

interface ActiveJobCardProps {
  jobId: string
  /** Called after the fade-out so the parent unmounts the card. */
  onTerminal?: (jobId: string) => void
}

function formatEta(etaSeconds: number): string {
  const total = Math.max(0, Math.floor(etaSeconds))
  const mm = Math.floor(total / 60)
  const ss = total % 60
  return `${mm.toString().padStart(2, "0")}:${ss.toString().padStart(2, "0")}`
}

export default function ActiveJobCard({
  jobId,
  onTerminal,
}: ActiveJobCardProps) {
  const event = useJobEvents(jobId)
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<string>("queued")
  const [percent, setPercent] = useState(0)
  const [eta, setEta] = useState<number | null>(null)
  const [chunks, setChunks] = useState(0)
  const [fading, setFading] = useState(false)
  const invalidatedRef = useRef(false)
  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal
  // 05-05 gap B: progressArrived sticks once the first progress event
  // arrives so the determinate bar stays even if a late stage_changed
  // (transcribing) frame comes in after progress. Reset on jobId change
  // (mirrors the ws.ts hook's own reset on jobId change).
  const progressArrived = useRef(false)
  useEffect(() => {
    progressArrived.current = false
  }, [jobId])

  useEffect(() => {
    if (!event) return
    switch (event.type) {
      case "snapshot":
        setStatus(event.status)
        setPercent(event.percent ?? 0)
        setEta(event.eta ?? null)
        break
      case "stage_changed":
        setStatus(event.stage)
        break
      case "progress":
        progressArrived.current = true
        setPercent(event.percent)
        setEta(event.eta_s)
        setChunks(event.chunks_done)
        break
      case "done":
        setStatus("done")
        setPercent(100)
        setFading(true)
        break
      case "failed":
        setStatus("failed")
        setFading(true)
        break
      case "cancelled":
        setStatus("cancelled")
        setFading(true)
        break
      case "error":
        setStatus("failed")
        setFading(true)
        break
      default:
        break
    }
  }, [event])

  // Terminal transition (UI-SPEC §2): invalidate the history cache so the
  // completed list refetches, then fade the card out and notify the
  // parent to unmount it.
  useEffect(() => {
    if (!fading || invalidatedRef.current) return
    invalidatedRef.current = true
    invalidateJobs(queryClient)
    const t = setTimeout(() => onTerminalRef.current?.(jobId), 250)
    return () => clearTimeout(t)
  }, [fading, jobId, queryClient])

  const isQueued =
    status === "queued" ||
    status === "uploading" ||
    status === "starting"
  const isIngesting = status === "ingesting"
  const isTranscribing = status === "transcribing"
  const isFailed = status === "failed"
  const isDone = status === "done"
  const isCancelled = status === "cancelled"
  // 05-05 gap B: covers BOTH the BE-emitted preparing stage (model load
  // window) AND the transcribing-before-first-progress window (first-chunk
  // wait after the model loads). Once progressArrived is set the card
  // switches to the determinate Transcribing... X% bar and never reverts.
  const isPreparing =
    status === "preparing" ||
    (isTranscribing && !progressArrived.current)
  const showBar = isIngesting || isTranscribing || isPreparing
  const showIndeterminateBar = isPreparing && !isIngesting
  const etaLabel =
    eta !== null && chunks >= 2 ? ` (ETA: ${formatEta(eta)})` : ""

  return (
    <div
      className={`active-card${fading ? " terminal" : ""}`}
      data-testid="active-job-card"
      data-status={status}
      data-preparing={isPreparing ? "true" : "false"}
      style={{
        border: isFailed
          ? "1px solid var(--destructive)"
          : "1px solid var(--border)",
        borderRadius: "var(--space-sm)",
        padding: "var(--space-md)",
        marginBottom: "var(--space-sm)",
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--space-md)",
        }}
      >
        <span className="badge badge-queued">{jobId.slice(0, 8)}</span>
        {isQueued && <span>In Queue</span>}
        {isIngesting && <span>Ingesting File... {percent}%</span>}
        {isPreparing && <span>Preparing...</span>}
        {isTranscribing && progressArrived.current && (
          <span>
            Transcribing... {percent}%{etaLabel}
          </span>
        )}
        {isFailed && (
          <span style={{ color: "var(--destructive)" }}>
            Failed to transcribe video. Please check your file format and try
            again.
          </span>
        )}
        {isDone && <span>Done</span>}
        {isCancelled && <span>Cancelled</span>}
      </div>
      {showBar && (
        <div
          className="progress-bar"
          style={{ marginTop: "var(--space-sm)" }}
        >
          {showIndeterminateBar ? (
            <div className="fill indeterminate" />
          ) : (
            <div className="fill" style={{ width: `${percent}%` }} />
          )}
        </div>
      )}
    </div>
  )
}