// Drop zone + full-window drag overlay (D-01, UI-SPEC §1).
//
// Two ingest entry points (D-01):
//   1. A full-window drag overlay -- global window `dragenter`/`dragover`
//      listeners prevent the browser default and reveal a semi-transparent
//      overlay with a #2563EB dashed border + "Drop files to start
//      transcribing" copy. Dismisses on `dragleave`/`drop`.
//   2. A dedicated drop area at the top of the history page (the element
//      carrying the `.drop-zone` class) -- dropping files onto it starts
//      the same upload flow.
//
// Multi-file drops queue FIFO (UI-SPEC §1: single-concurrency client
// queue) -- one file uploads at a time via `useUpload`, keeping the
// client memory profile stable. Each completed upload emits the created
// jobId upward via `onJobCreated` so HistoryPage renders an
// ActiveJobCard; the real 0->100 percent from `useUpload` is shown in
// the drop-area upload indicator while a file is streaming up (D-02).
import { useCallback, useEffect, useRef, useState } from "react"

import { useUpload } from "../hooks/useUpload"

interface DropZoneProps {
  onJobCreated: (jobId: string) => void
}

export default function DropZone({ onJobCreated }: DropZoneProps) {
  const [overlayVisible, setOverlayVisible] = useState(false)
  const [queue, setQueue] = useState<File[]>([])
  const [activeFile, setActiveFile] = useState<File | null>(null)
  const [progress, setProgress] = useState(0)
  const onJobCreatedRef = useRef(onJobCreated)
  onJobCreatedRef.current = onJobCreated

  // Full-window drag overlay (UI-SPEC §1).
  useEffect(() => {
    const hasFiles = (e: DragEvent): boolean =>
      !!e.dataTransfer &&
      Array.from(e.dataTransfer.types ?? []).includes("Files")
    const onDragEnter = (e: DragEvent) => {
      if (hasFiles(e)) {
        e.preventDefault()
        setOverlayVisible(true)
      }
    }
    const onDragOver = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault()
    }
    const onDragLeave = (e: DragEvent) => {
      // relatedTarget === null -> the pointer left the window entirely.
      if (e.relatedTarget === null) setOverlayVisible(false)
    }
    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      setOverlayVisible(false)
    }
    window.addEventListener("dragenter", onDragEnter)
    window.addEventListener("dragover", onDragOver)
    window.addEventListener("dragleave", onDragLeave)
    window.addEventListener("drop", onDrop)
    return () => {
      window.removeEventListener("dragenter", onDragEnter)
      window.removeEventListener("dragover", onDragOver)
      window.removeEventListener("dragleave", onDragLeave)
      window.removeEventListener("drop", onDrop)
    }
  }, [])

  const handleFiles = useCallback((files: FileList) => {
    const arr = Array.from(files)
    if (arr.length === 0) return
    setQueue((prev) => [...prev, ...arr])
  }, [])

  // FIFO queue: pop the next file when the active slot is free
  // (UI-SPEC §1 single-concurrency client queue).
  useEffect(() => {
    if (activeFile !== null || queue.length === 0) return
    const next = queue[0]
    setQueue((q) => q.slice(1))
    setActiveFile(next)
    setProgress(0)
  }, [activeFile, queue])

  const handleDone = useCallback((jobId: string) => {
    onJobCreatedRef.current(jobId)
    setActiveFile(null)
  }, [])

  return (
    <>
      {overlayVisible && (
        <div
          data-testid="drop-overlay"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            // The overlay covers the whole viewport during a drag, so it is
            // the actual drop target -- wire it to the same upload flow as
            // the dedicated .drop-zone (D-01 "two entry points"). The
            // window-level onDrop (preventDefault + hide) still fires via
            // bubbling, but only THIS handler touches the files, so there
            // is no double-handling.
            e.preventDefault()
            handleFiles(e.dataTransfer.files)
          }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "rgba(250,250,250,0.9)",
            border: "4px dashed var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <p
            style={{
              fontSize: "var(--fs-display)",
              fontWeight: 700,
              color: "var(--accent)",
            }}
          >
            Drop files to start transcribing
          </p>
        </div>
      )}
      <div
        className="drop-zone"
        data-testid="drop-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          handleFiles(e.dataTransfer.files)
        }}
        style={{
          minHeight: "120px",
          border: "2px dashed var(--border)",
          borderRadius: "var(--space-sm)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          padding: "var(--space-lg)",
          background: "var(--surface)",
        }}
      >
        {activeFile ? (
          <div data-testid="upload-indicator" style={{ width: "100%" }}>
            <span>
              Uploading {activeFile.name}: {progress}%
            </span>
            <div
              className="progress-bar"
              style={{ marginTop: "var(--space-sm)" }}
            >
              <div className="fill" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)" }}>
            Drag and drop video files here or click the upload area to start
            transcribing.
          </p>
        )}
      </div>
      {activeFile !== null && (
        <UploadController
          key={`${activeFile.name}-${activeFile.size}`}
          file={activeFile}
          onProgress={setProgress}
          onDone={handleDone}
        />
      )}
    </>
  )
}

/** Internal: drives `useUpload` for a single file and reports progress +
 *  completion upward. Rendered with a `key` so each file gets a fresh
 *  hook lifecycle (the previous XHR is aborted on unmount). */
function UploadController({
  file,
  onProgress,
  onDone,
}: {
  file: File
  onProgress: (p: number) => void
  onDone: (jobId: string) => void
}) {
  const upload = useUpload(file)
  const doneRef = useRef(false)

  useEffect(() => {
    onProgress(upload.progress)
  }, [upload.progress, onProgress])

  useEffect(() => {
    if (upload.status === "done" && upload.jobId && !doneRef.current) {
      doneRef.current = true
      onDone(upload.jobId)
    }
  }, [upload.status, upload.jobId, onDone])

  return null
}