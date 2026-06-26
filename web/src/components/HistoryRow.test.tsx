// HistoryRow tests -- plan 05-04 Task 2.
//
// Closes UAT test-4 gap A: the row must show the original dropped
// filename (job.original_filename) when present, fall back to
// basename(job.source_path) when it is null, and render "unknown" when
// neither field is set. HistoryRow uses useNavigate so each test wraps
// it in a MemoryRouter + QueryClientProvider.
import { describe, expect, it } from "vitest"
import { render, cleanup } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import HistoryRow from "./HistoryRow"
import type { JobResponse } from "../api/jobs"

function renderRow(job: Partial<JobResponse> & { id: string }) {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HistoryRow job={job as JobResponse} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("HistoryRow filename derivation (plan 05-04)", () => {
  it("renders original_filename when present", () => {
    const { getByText, queryByText } = renderRow({
      id: "j1",
      status: "done",
      created_at: "2026-06-25T00:00:00+00:00",
      source_path: "/data/jobs/j1/source.mp4",
      original_filename: "vacation-final-cut.mp4",
      duration_s: 120,
    })
    expect(getByText("vacation-final-cut.mp4")).toBeTruthy()
    expect(queryByText("source.mp4")).toBeNull()
  })

  it("falls back to basename(source_path) when original_filename is null", () => {
    const { getByText } = renderRow({
      id: "j2",
      status: "done",
      created_at: "2026-06-25T00:00:00+00:00",
      source_path: "/data/jobs/j2/source.mp4",
      original_filename: null,
      duration_s: 60,
    })
    expect(getByText("source.mp4")).toBeTruthy()
  })

  it("shows unknown when both original_filename and source_path are absent", () => {
    const { getByText } = renderRow({
      id: "j3",
      status: "done",
      created_at: "2026-06-25T00:00:00+00:00",
      source_path: null,
      original_filename: null,
      duration_s: null,
    })
    expect(getByText("unknown")).toBeTruthy()
  })

  it.afterAll(() => {
    cleanup()
  })
})