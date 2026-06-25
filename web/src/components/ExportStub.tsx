// Layout-stability stub for the future Export button (UI-SPEC §6, D-10).
//
// Phase 5 delivers only the "re-open a completed job and see its existing
// transcript" half of SC-5; the re-export half is deferred to Phase 9
// (EXPORT-01/02/03). To keep the detail-header layout stable across
// phases, a disabled "Export (Coming Soon)" button is rendered here as a
// grey, non-clickable block. D-10 allows this stub for layout stability.
export default function ExportStub() {
  return (
    <button
      type="button"
      className="btn"
      disabled
      data-testid="export-stub"
    >
      Export (Coming Soon)
    </button>
  )
}