---
phase: 05-local-file-ingest-history-ui-3-pane-layout
reviewed: 2026-06-26T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - app/api/routes_jobs.py
  - app/jobs/manifest.py
  - app/jobs/orchestrator.py
  - app/jobs/service.py
  - app/models/job.py
  - app/models/manifest.py
  - migrations/0009_add_original_filename.sql
  - tests/test_migration_idempotency.py
  - tests/test_orchestrator.py
  - tests/test_original_filename.py
  - web/src/api/types.ts
  - web/src/components/ActiveJobCard.test.tsx
  - web/src/components/ActiveJobCard.tsx
  - web/src/components/HistoryRow.test.tsx
  - web/src/components/HistoryRow.tsx
  - web/src/styles.css
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-26T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Gap-closure review for Phase 05 plans 05-04 (original_filename persistence) and 05-05
(preparing-state WS event). The two plans are well-threaded and internally consistent:

- **05-04** correctly adds the `original_filename` column as an additive nullable TEXT
  field, threads it through `JobManifest` → `update_stage` projection → `list_jobs` /
  `get_job` SELECTs → `_row_to_response` → `JobResponse` → `HistoryRow` fallback. The
  upload route writes the DB column directly before enqueue so an immediate GET returns
  it, and `update_stage` re-projects the same value from the manifest (idempotent).
  Migration 0009 is a single `ALTER TABLE ADD COLUMN` and reuses the runner's
  duplicate-column guard; the triple-apply + missing-version-row tests cover the
  idempotency contract. No blocker-level issues on this path.

- **05-05** correctly emits `stage_changed(preparing)` as an additive WS-only event
  before `_load_stt_adapter` on the production path only, leaves the DB stage/status
  untouched (no `update_stage` call), and keeps `preparing` out of `StageNameLiteral`.
  The `progressArrived` ref correctly sticks once the first progress event arrives and
  resets on `jobId` change, giving the "determinite bar never reverts" property. The
  ordering test (`preparing` before `transcribing`) and the test-path-skips-preparing
  test pin both contracts.

The issues found are all on the FE reconnect path: a client that (re)connects
mid-transcription does not see the determinate bar or the ETA, because the snapshot
event is not treated as evidence that progress has arrived. These are UX-correctness
defects in the stated "determinite bar that never reverts" contract, not crashes or
data-loss. No security or data-integrity issues were found.

## Warnings

### WR-01: Reconnect mid-transcription shows "Preparing..." indeterminate instead of the determinate "Transcribing... X%" bar

**File:** `web/src/components/ActiveJobCard.tsx:60-64, 120-122`
**Issue:**
The `progressArrived` ref is only set in the `progress` case (line 69). The `snapshot`
case (lines 61-64) updates `percent` / `eta` / `status` from the snapshot but never
sets `progressArrived.current = true`. The WS snapshot is sourced from `progress.json`
(`app/api/routes_ws.py:179-188`), so a client that connects mid-transcription receives
`{type:"snapshot", status:"transcribing", percent:50, eta:...}` with a non-zero
percent. The preparing logic then evaluates:

```ts
const isPreparing =
  status === "preparing" ||
  (isTranscribing && !progressArrived.current)   // transcribing + !false -> true
```

So `isPreparing` is `true`, `showIndeterminateBar` is `true`, and the card renders
"Preparing..." with an indeterminate bar, ignoring the available `percent=50`. This
contradicts the plan 05-05 contract: "ActiveJobCard shows an indeterminate 'Preparing...'
bar until the first progress event, then a determinate bar that never reverts." For a
reconnecting client the snapshot IS the first progress signal, and the determinate bar
should appear.

The existing test `stays Preparing... on transcribing before first progress`
(`ActiveJobCard.test.tsx:82`) only fires a snapshot with `percent: 0` / `status:
"queued"`, so it does not cover the reconnect-with-nonzero-percent case.

**Fix:**
In the `snapshot` case, mark progress as arrived when the snapshot carries a non-zero
percent (i.e. `progress.json` already has real chunk data):

```ts
case "snapshot":
  setStatus(event.status)
  setPercent(event.percent ?? 0)
  setEta(event.eta ?? null)
  if ((event.percent ?? 0) > 0) {
    progressArrived.current = true
  }
  break
```

This keeps the `percent: 0` snapshot path in the existing test green (progressArrived
stays false → Preparing still shown), while making a reconnect mid-transcription render
the determinate "Transcribing... 50%" bar immediately.

### WR-02: Reconnect during the model-load window shows "Ingesting File... 0%" instead of "Preparing..."

**File:** `app/jobs/orchestrator.py:251-263`, `app/api/routes_ws.py:168-188`
**Issue:**
`stage_changed(preparing)` is intentionally WS-only: the DB `status` stays at
`"ingesting"` (set by the prior `update_stage("ingested")`) for the whole model-load
window, and the event is emitted exactly once before `_load_stt_adapter`. A client that
connects AFTER that event was emitted (e.g. a page refresh during the JIT load) receives
a WS snapshot with `status = job.status = "ingesting"` (the DB value) and never sees the
`preparing` event (it is not replayed on connect). `ActiveJobCard` then renders
"Ingesting File... 0%" — the very stuck-looking state plan 05-05 was written to eliminate
— for the entire model-load window, with no transition to Preparing.

This is a known consequence of the additive WS-only design (documented in the scope:
"preparing is intentionally NOT added to StageNameLiteral"), but it leaves the
reconnecting user with a degraded UX during the exact window the fix targets. Worth
either (a) recording a transient `preparing` flag in `progress.json` so the snapshot can
surface it, or (b) accepting the gap with an explicit comment in `routes_ws.py` next to
the snapshot's `status` field.

**Fix (option a, smallest):** have the orchestrator write `{"stage": "preparing"}` into
`progress.json` (or a sibling `stage_hint.json`) before publishing the event, and have
`routes_ws.py` override the snapshot's `status` to `"preparing"` when that hint is
present and the DB status is still `"ingesting"`. This re-surfaces the preparing state
to reconnecting clients without touching the DB stage/status invariant.

### WR-03: ETA is hidden after reconnect because the WS snapshot carries no `chunks_done`

**File:** `web/src/components/ActiveJobCard.tsx:60-64, 126`, `app/api/routes_ws.py:180-188`
**Issue:**
`etaLabel` is gated on `chunks >= 2` (line 126), and `chunks` is only updated in the
`progress` case (line 72). The WS snapshot (`routes_ws.py:180-188`) carries `percent`
and `eta` but no `chunks_done`, so after a reconnect `chunks` stays `0` and `etaLabel`
is `""` even when the snapshot's `eta` is non-null. A reconnecting client mid-transcription
sees "Transcribing... 50%" with no ETA, then the ETA appears only after the next live
`progress` event arrives. This is a minor UX regression on the reconnect path that
follows from the same root cause as WR-01 (the snapshot is not fully treated as a
progress signal).

**Fix:** Either include `chunks_done` / `chunks_total` in the WS snapshot (read from
`progress.json` alongside `percent` / `eta`) and set `setChunks(event.chunks_done)` in
the `snapshot` case, or relax the ETA gate on the snapshot path to `eta !== null &&
percent > 0`.

## Info

### IN-01: Redundant `!isIngesting` term in `showIndeterminateBar`

**File:** `web/src/components/ActiveJobCard.tsx:124`
**Issue:** `showIndeterminateBar = isPreparing && !isIngesting`. `isPreparing` requires
`status === "preparing" || (isTranscribing && !progressArrived.current)` while
`isIngesting` requires `status === "ingesting"`; the two are mutually exclusive, so
`!isIngesting` is always true when `isPreparing` is true. Harmless but noisy.
**Fix:** `const showIndeterminateBar = isPreparing`.

### IN-02: Unused `_SerialFakeAdapterAdapter` class

**File:** `tests/test_orchestrator.py:758-769`
**Issue:** The `_SerialFakeAdapterAdapter` wrapper class is never instantiated (the
serial-concurrency test returns the bare `_SerialFakeAdapter` from the monkeypatched
loader). It is marked `pragma: no cover - retained for forward compat` but adds dead
code to the test module.
**Fix:** Remove the class, or add a concrete test that uses it.

### IN-03: `original_filename` stored from the raw `X-Filename` header with no length/charset cap

**File:** `app/api/routes_jobs.py:122, 207-225`
**Issue:** `x_filename` is taken straight from the `X-Filename` header and written
unbounded into both the on-disk manifest and the `jobs.original_filename` TEXT column.
It is display-only (never used as a filesystem path; `source_path` is built from the
validated `ext`), and React auto-escapes the rendered value in `HistoryRow`, so there is
no XSS or path-traversal vector. However there is no length cap or charset validation
equivalent to `validate_idempotency_key`, so an oversized or hostile header value flows
unbounded into the DB and the manifest JSON.
**Fix:** Apply a length cap (e.g. 255) and a basic printable-character check on
`x_filename` before persisting, mirroring the idempotency-key validation pattern.

### IN-04: `HistoryRow.basename` returns the trailing slash for trailing-slash paths

**File:** `web/src/components/HistoryRow.tsx:11-15`
**Issue:** For an input like `"foo/"`, `parts = ["foo", ""]`, `parts[parts.length - 1]`
is `""` (falsy), so the function falls back to returning `path` (`"foo/"`), which would
render the trailing slash. Real `source_path` values are always `source.<ext>` files so
this is not reachable today, but the fallback is surprising.
**Fix:** `return parts[parts.length - 1] || parts[parts.length - 2] || path` — or
filter out empty segments before splitting.

---

_Reviewed: 2026-06-26T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_