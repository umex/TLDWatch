// The right pane of the 2-pane detail view (D-08, UI-SPEC §6).
//
// The summary pane stays visible from day one at a stable 40% width
// (the `.detail-layout` grid enforces it; `.summary-pane` is the fixed
// 40% column). It shows the exact placeholder copy "Summaries will
// appear here once summarization is enabled." until Phase 8 fills it
// with structured summaries. Hiding the pane until summaries exist was
// rejected (D-08) — keep the 2-pane shape stable.
export default function SummaryPane() {
  return (
    <aside className="summary-pane" data-testid="summary-pane">
      <p>Summaries will appear here once summarization is enabled.</p>
    </aside>
  )
}