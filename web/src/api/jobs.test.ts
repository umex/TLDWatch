// jobs.test.ts — VALIDATION.md row 05-03-03 (JOB-03 re-open loads
// transcript) + the D-02 real-percent useUpload assertion.
//
// Two groups:
//   1. useTranscript (D-14): returns the parsed Transcript on 200, and
//      the TRANSCRIBING sentinel on 404 (the detail view's "Transcribing..."
//      state). fetch is the setup.ts vi.fn mock.
//   2. useUpload (D-02 locked-real-percent): using the XHR mock from
//      setup.ts, firing xhr.upload.onprogress with
//      {lengthComputable:true, loaded:500, total:1000} sets progress to
//      50, then loaded:1000/total:1000 sets progress to 100 -- proving
//      real 0->100 percent on the XHR-primary path (NOT a static
//      "Uploading..." label). Also asserts the request hits
//      /jobs/upload with X-Filename + Idempotency-Key + octet-stream
//      headers and that fetch is NOT used for the upload (XHR-primary).
//
// This file uses React.createElement instead of JSX so it can keep the
// `.ts` extension (the plan's acceptance path is `src/api/jobs.test.ts`).
import { beforeEach, describe, expect, it, vi } from "vitest"
import { createElement, type ReactNode } from "react"
import { render, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { TRANSCRIBING, useTranscript, type Transcript } from "./jobs"
import { useUpload } from "../hooks/useUpload"

interface MockXHRInstance {
  __getUrl: () => string
  __getHeaders: () => Record<string, string>
  __progress: (loaded: number, total: number, lengthComputable?: boolean) => void
}

const MockXHR = (
  globalThis as unknown as {
    __MOCKS__: { XMLHttpRequest: { instances: MockXHRInstance[] } }
  }
).__MOCKS__.XMLHttpRequest

const sampleTranscript: Transcript = {
  schema_version: 1,
  job_id: "job-1",
  segments: [{ start_s: 12, end_s: 15, text: "hello" }],
}

function withQueryClient(node: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    createElement(QueryClientProvider, { client: qc }, node),
  )
}

function TranscriptProbe({ id }: { id: string }) {
  const { data } = useTranscript(id)
  const isTranscribing = data === TRANSCRIBING
  return createElement(
    "div",
    {
      "data-testid": "transcript-probe",
      "data-state": isTranscribing ? "transcribing" : data ? "ready" : "loading",
    },
  )
}

function UploadProbe({ file }: { file: File }) {
  const { progress, status } = useUpload(file)
  return createElement(
    "div",
    {
      "data-testid": "upload-probe",
      "data-progress": String(progress),
      "data-status": status,
    },
  )
}

function mockResponse(body: string, status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Not Found",
    text: () => Promise.resolve(body),
  } as Response
}

describe("useTranscript (D-14)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("returns the parsed Transcript on 200", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse(JSON.stringify(sampleTranscript), 200),
    )
    const { getByTestId } = withQueryClient(
      createElement(TranscriptProbe, { id: "job-1" }),
    )
    await waitFor(() =>
      expect(getByTestId("transcript-probe").getAttribute("data-state")).toBe(
        "ready",
      ),
    )
  })

  it("returns the TRANSCRIBING sentinel on 404", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse('{"detail":"transcript not found"}', 404),
    )
    const { getByTestId } = withQueryClient(
      createElement(TranscriptProbe, { id: "job-2" }),
    )
    await waitFor(() =>
      expect(getByTestId("transcript-probe").getAttribute("data-state")).toBe(
        "transcribing",
      ),
    )
  })
})

describe("useUpload (D-02 real 0->100 percent via XHR primary)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("reports progress 0 -> 50 -> 100 from xhr.upload.onprogress", async () => {
    const file = new File(["body-bytes"], "video.mp4", {
      lastModified: 1700000000000,
    })
    const { getByTestId } = withQueryClient(
      createElement(UploadProbe, { file }),
    )

    // Wait for the async idempotencyKey().then() to call xhr.send (which
    // pushes the instance onto the mock tracker).
    await waitFor(() => MockXHR.instances.length > 0)
    const xhr = MockXHR.instances[0]

    // XHR-primary transport: POST /jobs/upload with octet-stream +
    // X-Filename + derived Idempotency-Key headers, and fetch is NOT
    // called for the upload.
    expect(xhr.__getUrl()).toBe("http://localhost:8000/jobs/upload")
    const headers = xhr.__getHeaders()
    expect(headers["X-Filename"]).toBe("video.mp4")
    expect(headers["Content-Type"]).toBe("application/octet-stream")
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f]{32}$/)
    expect(fetch).not.toHaveBeenCalled()

    // Real acked-byte percent (D-02): NOT a static "Uploading..." label.
    // React 19 schedules the setState from the XHR event callback as an
    // async re-render, so waitFor lets the DOM flush before asserting.
    xhr.__progress(500, 1000)
    await waitFor(() =>
      expect(getByTestId("upload-probe").getAttribute("data-progress")).toBe(
        "50",
      ),
    )
    xhr.__progress(1000, 1000)
    await waitFor(() =>
      expect(getByTestId("upload-probe").getAttribute("data-progress")).toBe(
        "100",
      ),
    )
  })
})