// XHR-PRIMARY upload hook (D-02 locked-real-percent, INGEST-01 FE half).
//
// React Router + TanStack Query are NOT involved here -- this is a plain
// XMLHttpRequest hook that streams the raw File body to POST /jobs/upload
// so `xhr.upload.onprogress` reports the real acked-byte percent 0->100
// for every file on every browser (Firefox/Safari included -- RESEARCH
// Pitfall 4 moot). fetch streaming is NOT used: it provides no
// reliable upload progress (RESEARCH Pitfall 5) and would render an
// indeterminate "Uploading..." label on Chrome/Edge, violating locked
// D-02 which requires a PERCENT for every file. XHR-primary is the
// single clean path.
//
// The body is sent via `xhr.send(file)` -- the browser streams the
// File/Blob directly from disk WITHOUT buffering the whole file in JS
// heap. This is the FE-side expression of INGEST-01's memory guarantee:
// the browser never holds the full multi-gigabyte file in memory, the
// back-end never buffers it (05-01 `request.stream()` + aiofiles), and
// the source lands atomically via os.replace on the back end.
//
// The raw octet-stream body + X-Filename header matches the 05-01
// back-end `request.stream()` contract -- NO multipart form wrapping
// (verified by the plan's source-grep gate). The
// Idempotency-Key is derived via the 05-02a `idempotencyKey` helper
// (SHA-256 of `[filename]-[size]-[lastmodified]` -> 32 hex chars,
// T-05-10) so a re-drop mid-upload collapses to the existing job
// (Phase 4 D-07).
import { useEffect, useState } from "react"

import { API_BASE, idempotencyKey } from "../api/client"

export type UploadStatus = "idle" | "uploading" | "done" | "error"

export interface UploadState {
  status: UploadStatus
  jobId: string | null
  /** Real acked-byte percent 0-100 driven by `xhr.upload.onprogress`. */
  progress: number
  error: string | null
}

const INITIAL: UploadState = {
  status: "idle",
  jobId: null,
  progress: 0,
  error: null,
}

/**
 * Stream `file` to `POST /jobs/upload` via XHR-primary and track the real
 * acked-byte percent. Pass `null` to stay idle. On `file` change a new
 * XHR is opened; the previous one is aborted on cleanup.
 *
 * @returns live `{ status, jobId, progress, error }` state. `progress`
 *   updates 0->100 as `xhr.upload.onprogress` fires with
 *   `lengthComputable` events; `jobId` is set from the parsed `{id}` of
 *   the 201/200 response body on success.
 */
export function useUpload(file: File | null): UploadState {
  const [state, setState] = useState<UploadState>(INITIAL)

  useEffect(() => {
    if (!file) return
    let cancelled = false
    setState({ status: "uploading", jobId: null, progress: 0, error: null })

    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API_BASE}/jobs/upload`)
    xhr.upload.onprogress = (e: ProgressEvent) => {
      if (cancelled) return
      if (e.lengthComputable) {
        // Real acked-byte percent (D-02). Pitfall 5 mitigation: never a
        // static "Uploading..." label -- this fires for every file on
        // every browser because XHR-primary is the transport.
        setState((s) => ({
          ...s,
          progress: Math.round((e.loaded / e.total) * 100),
        }))
      }
    }
    xhr.onload = () => {
      if (cancelled) return
      if (xhr.status === 201 || xhr.status === 200) {
        try {
          const body = JSON.parse(xhr.responseText) as { id: string }
          setState({ status: "done", jobId: body.id, progress: 100, error: null })
        } catch {
          setState((s) => ({ ...s, status: "error", error: "bad response" }))
        }
      } else {
        setState((s) => ({
          ...s,
          status: "error",
          error: xhr.statusText || "upload failed",
        }))
      }
    }
    xhr.onerror = () => {
      if (cancelled) return
      setState((s) => ({ ...s, status: "error", error: "upload failed" }))
    }

    // Derive the Idempotency-Key (async SHA-256) then send. The browser
    // streams the File/Blob body directly from disk via xhr.send(file)
    // WITHOUT buffering the whole file in JS heap -- FE-side INGEST-01
    // memory guarantee; XHR sends the File handle, not an in-memory copy.
    idempotencyKey(file.name, file.size, file.lastModified).then((key) => {
      if (cancelled) return
      xhr.setRequestHeader("Idempotency-Key", key)
      xhr.setRequestHeader("X-Filename", file.name)
      xhr.setRequestHeader("Content-Type", "application/octet-stream")
      xhr.send(file)
    })

    return () => {
      cancelled = true
      xhr.abort()
    }
  }, [file])

  return state
}