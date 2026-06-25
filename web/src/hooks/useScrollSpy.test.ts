// useScrollSpy test (UI-03, D-09; VALIDATION.md row 05-03-02).
//
// Uses the mocked IntersectionObserver from src/test/setup.ts. The mock
// tracks every constructed observer via `MockIntersectionObserver.instances`
// and exposes a `__trigger` helper that fires the intersection callback
// with synthetic entries. A harness component renders the container +
// three segment rows so `useScrollSpy` has real DOM elements to observe,
// and surfaces the current `activeId` via a data attribute.
//
// This file uses React.createElement (not JSX) so it can keep the `.ts`
// extension named by the plan's acceptance command
// `npx vitest run src/hooks/useScrollSpy.test.ts` (the tsconfig only
// enables `jsx: react-jsx` for `.tsx` files -- same pattern as jobs.test.ts).
import { describe, expect, it, afterEach } from "vitest"
import { render, cleanup, waitFor } from "@testing-library/react"
import { createElement, useRef } from "react"
import type { ReactElement } from "react"

import { useScrollSpy } from "./useScrollSpy"

interface MockIO {
  __trigger: (
    entries: Array<{ target: Element; isIntersecting: boolean }>,
  ) => void
  elements: Set<Element>
}

const MOCKS = (globalThis as unknown as {
  __MOCKS__: { IntersectionObserver: { instances: MockIO[] } }
}).__MOCKS__

interface HarnessProps {
  rowIds: string[]
  onActive?: (id: string | null) => void
}

function Harness({ rowIds, onActive }: HarnessProps) {
  const ref = useRef<HTMLDivElement>(null)
  const activeId = useScrollSpy(ref, rowIds)
  const children: ReactElement[] = rowIds.map((id) =>
    createElement("div", { key: id, id: id, "data-testid": id }),
  )
  children.push(
    createElement("span", { "data-testid": "active-id", key: "active" }, activeId ?? "none"),
  )
  if (onActive) {
    children.push(
      createElement("span", {
        "data-testid": "sink",
        key: "sink",
        ref: () => onActive(activeId),
      }),
    )
  }
  return createElement("div", { ref, "data-testid": "container" }, children)
}

afterEach(cleanup)

describe("useScrollSpy (UI-03, D-09)", () => {
  it("creates an IntersectionObserver rooted at the container with the -49% focal rootMargin", () => {
    render(createElement(Harness, { rowIds: ["seg-0", "seg-1", "seg-2"] }))
    expect(MOCKS.IntersectionObserver.instances).toHaveLength(1)
    const io = MOCKS.IntersectionObserver.instances[0]
    expect(io.elements.size).toBe(3)
  })

  it("sets activeId to the last intersecting row when one or more rows intersect the focal line", async () => {
    const { getByTestId } = render(
      createElement(Harness, { rowIds: ["seg-0", "seg-1", "seg-2"] }),
    )
    const seg1 = getByTestId("seg-1")
    const io = MOCKS.IntersectionObserver.instances[0]
    io.__trigger([{ target: seg1, isIntersecting: true }])
    await waitFor(() => {
      expect(getByTestId("active-id").textContent).toBe("seg-1")
    })
  })

  it("picks the last (lowest in DOM) intersecting row when several intersect", async () => {
    const { getByTestId } = render(
      createElement(Harness, { rowIds: ["seg-0", "seg-1", "seg-2"] }),
    )
    const seg0 = getByTestId("seg-0")
    const seg2 = getByTestId("seg-2")
    const io = MOCKS.IntersectionObserver.instances[0]
    io.__trigger([
      { target: seg0, isIntersecting: true },
      { target: seg2, isIntersecting: true },
    ])
    await waitFor(() => {
      expect(getByTestId("active-id").textContent).toBe("seg-2")
    })
  })

  it("falls back to nearest-by-pixel when no row intersects (seg-1 closest to viewport center)", async () => {
    const origGetBoundingClientRect = Element.prototype.getBoundingClientRect
    const centers: Record<string, number> = {
      "seg-0": 0,
      "seg-1": 400,
      "seg-2": 9999,
    }
    Element.prototype.getBoundingClientRect = function (): DOMRect {
      const id = (this as Element).id
      const top = id in centers ? centers[id] : 0
      return {
        top,
        bottom: top + 40,
        left: 0,
        right: 100,
        width: 100,
        height: 40,
        x: 0,
        y: top,
        toJSON: () => ({}),
      } as DOMRect
    }
    Object.defineProperty(window, "innerHeight", {
      value: 800,
      configurable: true,
    })

    try {
      const { getByTestId } = render(
        createElement(Harness, { rowIds: ["seg-0", "seg-1", "seg-2"] }),
      )
      const seg0 = getByTestId("seg-0")
      const io = MOCKS.IntersectionObserver.instances[0]
      io.__trigger([{ target: seg0, isIntersecting: false }])
      await waitFor(() => {
        expect(getByTestId("active-id").textContent).toBe("seg-1")
      })
    } finally {
      Element.prototype.getBoundingClientRect = origGetBoundingClientRect
    }
  })

  it("disconnects the observer on unmount (T-05-11 no stale-listener leak)", () => {
    const { unmount } = render(
      createElement(Harness, { rowIds: ["seg-0", "seg-1"] }),
    )
    const io = MOCKS.IntersectionObserver.instances[0]
    expect(io.elements.size).toBe(2)
    unmount()
    expect(io.elements.size).toBe(0)
  })
})