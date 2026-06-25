// DetailPage test (UI-01 2-pane detail + UI-02 no embedded video).
//
// Covers VALIDATION.md rows 05-02-01 (DetailPage.test.tsx) + 05-02-02
// (grep for an embedded media player element returns 0). The test mocks
// `useTranscript` to return a sample Transcript (segments:
// [{start_s:12, end_s:15, text:"hello"}]), renders DetailPage inside a
// MemoryRouter + QueryClientProvider, and asserts both panes are present,
// the [mm:ss] timestamp renders, and NO embedded media player element
// exists anywhere in the container.
import { describe, expect, it, vi } from "vitest"
import { render, within } from "@testing-library/react"
import { MemoryRouter, Routes, Route } from "react-router"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import DetailPage from "./DetailPage"
import type { Transcript } from "../api/jobs"

const sampleTranscript: Transcript = {
  schema_version: 1,
  job_id: "test-id",
  segments: [{ start_s: 12, end_s: 15, text: "hello" }],
}

vi.mock("../api/jobs", async () => {
  const actual =
    await vi.importActual<typeof import("../api/jobs")>("../api/jobs")
  return {
    ...actual,
    useTranscript: () => ({ data: sampleTranscript, isLoading: false }),
  }
})

function renderDetail() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/jobs/test-id"]}>
        <Routes>
          <Route path="/jobs/:id" element={<DetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("DetailPage (UI-01 + UI-02)", () => {
  it("renders both transcript and summary panes in the 2-pane layout", () => {
    const { getByTestId } = renderDetail()
    expect(getByTestId("transcript-pane")).toBeTruthy()
    expect(getByTestId("summary-pane")).toBeTruthy()
  })

  it("renders no embedded media player element anywhere (UI-02)", () => {
    const { container } = renderDetail()
    expect(container.querySelector("video")).toBeNull()
  })

  it("renders a transcript row with the [mm:ss] timestamp + body text", () => {
    const { getByTestId, getByText } = renderDetail()
    const pane = getByTestId("transcript-pane")
    expect(within(pane).getByText("[00:12]")).toBeTruthy()
    expect(getByText("hello")).toBeTruthy()
  })

  it("renders the exact summary placeholder copy (D-08)", () => {
    const { getByTestId } = renderDetail()
    const summary = getByTestId("summary-pane")
    expect(
      within(summary).getByText(
        "Summaries will appear here once summarization is enabled.",
      ),
    ).toBeTruthy()
  })

  it("renders the disabled Export (Coming Soon) stub (D-10)", () => {
    const { getByTestId } = renderDetail()
    const stub = getByTestId("export-stub") as HTMLButtonElement
    expect(stub.disabled).toBe(true)
    expect(stub.textContent).toContain("Export (Coming Soon)")
  })
})