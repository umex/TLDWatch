// ActiveJobCard tests -- plan 05-05 Task 2.
//
// Closes UAT test-4 gap B (FE side): between upload completion and the
// first chunk progress callback the card rendered "Transcribing... 0%"
// with a 0% bar -- the user thought nothing was going on while the STT
// model JIT-loaded. The fix adds an indeterminate "Preparing..." state
// that shows during the model-load window AND the first-chunk wait (i.e.
// whenever status is "preparing" OR status is "transcribing" but no
// progress event has arrived yet). Once the first progress event arrives
// the card switches to the determinate "Transcribing... X%" bar and never
// reverts to Preparing.
//
// ActiveJobCard calls ``useJobEvents(jobId)`` which opens a real WebSocket
// via the setup.ts MockWebSocket. Events are driven through
// ``MockWebSocket.instances[0].__message(...)``. The card is wrapped in a
// QueryClientProvider because the terminal transition calls
// ``invalidateJobs(queryClient)``.
import { describe, expect, it } from "vitest"
import { render, cleanup, waitFor, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import ActiveJobCard from "./ActiveJobCard"

// Access the MockWebSocket class registered by setup.ts.
const MockWS = (
  globalThis as unknown as {
    __MOCKS__: {
      WebSocket: { instances: Array<{ __message: (data: unknown) => void }> }
    }
  }
).__MOCKS__.WebSocket

function renderCard(jobId = "job-1") {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <ActiveJobCard jobId={jobId} />
    </QueryClientProvider>,
  )
}

async function waitForSocket() {
  await waitFor(() => expect(MockWS.instances.length).toBe(1))
  return MockWS.instances[0]
}

function fire(data: unknown) {
  act(() => {
    MockWS.instances[0].__message(data)
  })
}

describe("ActiveJobCard preparing state (plans 05-05 + 05-06)", () => {
  it("shows Preparing... on stage_changed(preparing)", async () => {
    const { getByText, queryByText, getByTestId, container } = renderCard()
    await waitForSocket()
    // Snapshot first so the card has a baseline status.
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "queued",
    })
    // BE-emitted preparing event.
    fire({ type: "stage_changed", stage: "preparing" })

    expect(getByText("Preparing...")).toBeTruthy()
    expect(queryByText(/Transcribing/)).toBeNull()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "true",
    )
    // No determinate 0% fill bar while preparing -- the indeterminate fill
    // has the `indeterminate` modifier class and no inline width style.
    const indeterminate = container.querySelector(".fill.indeterminate")
    expect(indeterminate).toBeTruthy()
    const determinate = container.querySelector('.fill[style*="width"]')
    expect(determinate).toBeNull()
  })

  it("stays Preparing... on transcribing before first progress", async () => {
    const { getByText, getByTestId } = renderCard()
    await waitForSocket()
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "queued",
    })
    fire({ type: "stage_changed", stage: "preparing" })
    // Model loaded; BE emits transcribing. No progress event yet.
    fire({ type: "stage_changed", stage: "transcribing" })

    expect(getByText("Preparing...")).toBeTruthy()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "true",
    )
  })

  it("switches to Transcribing...X% on first progress", async () => {
    const { getByText, getByTestId } = renderCard()
    await waitForSocket()
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "queued",
    })
    fire({ type: "stage_changed", stage: "preparing" })
    fire({ type: "stage_changed", stage: "transcribing" })
    // First chunk progress arrives -> determinate bar.
    fire({
      type: "progress",
      chunks_done: 1,
      chunks_total: 4,
      percent: 25,
      eta_s: 120,
      chunk_start_s: 0,
    })

    expect(getByText(/Transcribing\.\.\. 25%/)).toBeTruthy()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "false",
    )
  })

  it("does not revert to Preparing on a late stage_changed(transcribing) after progress", async () => {
    const { getByText, getByTestId } = renderCard()
    await waitForSocket()
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "queued",
    })
    fire({ type: "stage_changed", stage: "preparing" })
    fire({ type: "stage_changed", stage: "transcribing" })
    fire({
      type: "progress",
      chunks_done: 1,
      chunks_total: 4,
      percent: 25,
      eta_s: 120,
      chunk_start_s: 0,
    })
    // A late stage_changed(transcribing) must NOT revert the UI to Preparing
    // (progressArrived sticks once set).
    fire({ type: "stage_changed", stage: "transcribing" })

    expect(getByText(/Transcribing/)).toBeTruthy()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "false",
    )
  })

  it("terminal done event fades the card (smoke)", async () => {
    const { container, getByText } = renderCard()
    await waitForSocket()
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "queued",
    })
    fire({ type: "stage_changed", stage: "preparing" })
    fire({ type: "stage_changed", stage: "transcribing" })
    fire({
      type: "progress",
      chunks_done: 4,
      chunks_total: 4,
      percent: 100,
      eta_s: 0,
      chunk_start_s: 0,
    })
    fire({ type: "done" })

    expect(getByText("Done")).toBeTruthy()
    // The terminal class is applied on the active-card wrapper.
    await waitFor(() => {
      expect(container.querySelector(".active-card.terminal")).toBeTruthy()
    })
  })

  it("shows Preparing... + indeterminate bar when snapshot status is starting and no stage_changed fires (05-06 race branch a)", async () => {
    const { getByText, queryByText, getByTestId, container } = renderCard()
    await waitForSocket()
    // Late-connecting card: snapshot status "starting" (DB status during the
    // model-load window -- preparing is WS-only and NOT persisted), and the
    // stage_changed(preparing) event was already broadcast before subscribe.
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "starting",
    })

    expect(getByText("Preparing...")).toBeTruthy()
    expect(queryByText(/In Queue/)).toBeNull()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "true",
    )
    const indeterminate = container.querySelector(".fill.indeterminate")
    expect(indeterminate).toBeTruthy()
    const determinate = container.querySelector('.fill[style*="width"]')
    expect(determinate).toBeNull()
  })

  it("shows Transcribing...X% determinate bar when snapshot is starting and a progress event arrives with no stage_changed(transcribing) (05-06 race branch b)", async () => {
    const { getByText, queryByText, getByTestId, container } = renderCard()
    await waitForSocket()
    // Late-connecting card: snapshot status "starting", then a progress event
    // arrives (the card missed BOTH stage_changed(preparing) AND
    // stage_changed(transcribing) -- simulates idle worker + StrictMode
    // remount delaying the real socket).
    fire({
      type: "snapshot",
      job_id: "job-1",
      stage: null,
      percent: 0,
      eta: null,
      status: "starting",
    })
    fire({
      type: "progress",
      chunks_done: 2,
      chunks_total: 5,
      percent: 45,
      eta_s: 60,
      chunk_start_s: 0,
    })

    expect(getByText(/Transcribing\.\.\. 45%/)).toBeTruthy()
    expect(getByTestId("active-job-card").getAttribute("data-preparing")).toBe(
      "false",
    )
    expect(queryByText(/In Queue/)).toBeNull()
    expect(queryByText("Preparing...")).toBeNull()
    const determinate = container.querySelector('.fill[style*="width"]')
    expect(determinate).toBeTruthy()
  })

  it.afterAll(() => {
    cleanup()
  })
})