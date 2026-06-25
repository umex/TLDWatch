// Scroll-spy active-line highlight hook (UI-03, D-09, UI-SPEC §3,
// RESEARCH Pattern 4).
//
// A single IntersectionObserver with `rootMargin: "-49% 0px -49% 0px"`
// (UI-SPEC §3) creates a 2% focal line at the vertical center of the
// scrollable container. The segment row passing through that line is
// highlighted. A pixel-offset fallback handles the gap when no row
// intersects the focal line (fast scroll / short transcripts) by picking
// the row whose midpoint is closest to the viewport center.
//
// The observer is rooted at `containerRef.current` so the focal line is
// relative to the scrollable transcript pane, not the window. The effect
// re-runs when `rowIds` changes (e.g. a transcript swap on re-open) so
// the new rows are re-observed and the old observer is disconnected
// (T-05-11 mitigation: no stale-listener leak). `threshold: 0` is used
// with a negative rootMargin -- `threshold: 1.0` would never fire on
// rows taller than the viewport (RESEARCH Anti-Pattern).

import { useEffect, useState } from "react"
import type { RefObject } from "react"

/**
 * Track which segment row is nearest the viewport center.
 *
 * @param containerRef ref to the scrollable pane (the IntersectionObserver
 *   root). Must be attached to the scrollable container div.
 * @param rowIds ids of the observable rows (e.g. `["seg-0","seg-1",...]`).
 *   The effect re-runs when this array changes so a transcript swap
 *   re-observes the new rows.
 * @returns the active row id (the one nearest the viewport center), or
 *   `null` until the observer first fires.
 */
export function useScrollSpy(
  containerRef: RefObject<HTMLDivElement | null>,
  rowIds: string[],
): string | null {
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || rowIds.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const intersecting = entries.filter((e) => e.isIntersecting)
        if (intersecting.length > 0) {
          // Pick the last (lowest in DOM) intersecting row -- the one
          // closesest to the center focal line on a downward scroll.
          setActiveId(intersecting[intersecting.length - 1].target.id)
        } else {
          // Fallback: closest row by pixel offset to the viewport
          // center. Used on fast scroll / short transcripts where no
          // row intersects the 2% focal line. `getBoundingClientRect`
          // is viewport-relative so the center is `window.innerHeight/2`.
          const center = window.innerHeight / 2
          let best: string | null = null
          let bestDist = Infinity
          for (const id of rowIds) {
            const el = document.getElementById(id)
            if (!el) continue
            const rect = el.getBoundingClientRect()
            const midpoint = rect.top + rect.height / 2
            const dist = Math.abs(midpoint - center)
            if (dist < bestDist) {
              bestDist = dist
              best = id
            }
          }
          if (best) setActiveId(best)
        }
      },
      {
        root: container,
        rootMargin: "-49% 0px -49% 0px",
        threshold: 0,
      },
    )

    rowIds.forEach((id) => {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    })

    return () => observer.disconnect()
    // Re-run when the container or the row-id list changes. `rowIds` is
    // a fresh array per render so a shallow dep is sufficient; the
    // effect re-observes the current rows each time.
  }, [containerRef, rowIds])

  return activeId
}