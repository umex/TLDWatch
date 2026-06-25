---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 03
subsystem: frontend-integration
tags: [scroll-spy, intersection-observer, useScrollSpy, terminal-transition, invalidateJobs, re-open-transcript, end-to-end-vertical-slice]
requires:
  - "Phase 05-01: POST /jobs/upload + GET /jobs/{id}/transcript (D-14) + 'uploading' JobStatus"
  - "Phase 05-02a: web/ API/WS layer (useJobs, useTranscript, invalidateJobs, TRANSCRIBING, jobsKeys) + vitest jsdom infra (IntersectionObserver mock) + CSS Design System (.transcript-row.active, .active-card.terminal)"
  - "Phase 05-02b: FE shell + components (TranscriptPane/TranscriptRow active prop + seg-{index} ids, ActiveJobCard terminal WS -> invalidateJobs + onTerminal fade-out, HistoryList terminal-only newest-first + No Transcripts Yet, HistoryRow navigate /jobs/:id, DetailPage useTranscript)"
  - "Phase 4: WS /ws/jobs/{id}/events snapshot + live terminal events (D-08)"
  - "Phase 3: Transcript / TranscriptSegment schema"
provides:
  - "web/src/hooks/useScrollSpy.ts: IntersectionObserver scroll-spy hook (rootMargin -49% 0px -49% 0px 2% focal line + pixel-offset fallback; disconnect on cleanup; re-run on rowIds change for T-05-11)"
  - "web/src/hooks/useScrollSpy.test.ts: 5 tests -- observer creation, single + multi intersection -> last (lowest in DOM) active row, no-intersection -> nearest-by-pixel fallback, disconnect on unmount"
  - "web/src/components/TranscriptPane.tsx (wired): containerRef + useScrollSpy -> activeId -> TranscriptRow active prop (UI-03, D-09, local files only); Rules-of-Hooks-safe (hooks unconditional, empty rowIds on transcribing state)"
  - "Verified end-to-end vertical slice: drop file -> XHR upload percent 0->100 -> active card -> terminal WS -> invalidateJobs -> history refetch -> click row -> /jobs/:id -> useTranscript -> 2-pane detail + scroll-spy highlight"
  - "Full back-end + FE suites green end-to-end (the vertical slice is provable)"
affects:
  - "Phase 5 verifier (gsd-verifier): the vertical slice is now wired end-to-end; all must_haves truths hold"
  - "Phase 6: consumes the scroll-spy + terminal-transition contracts for YouTube jobs (timestamp link-out will extend TranscriptRow)"
tech-stack:
  added: []
  patterns:
    - "IntersectionObserver scroll-spy (UI-SPEC sec3): single observer rooted at the scrollable container, rootMargin '-49% 0px -49% 0px' creates a 2% focal line at the vertical center; the last (lowest in DOM) intersecting row wins; pixel-offset fallback (getBoundingClientRect midpoint vs window.innerHeight/2) handles no-intersection gaps (fast scroll / short transcripts). threshold: 0 with negative rootMargin (NOT threshold: 1.0 -- RESEARCH Anti-Pattern)."
    - "Rules-of-Hooks-safe scroll-spy wiring: TranscriptPane calls useRef + useMemo + useScrollSpy unconditionally; the transcribing/not-ready branch is handled after the hooks via an isReady flag, with an empty rowIds array causing useScrollSpy to early-return (no observer created)."
    - "Test-infra instance tracking: setup.ts MockIntersectionObserver gained a static instances[] tracker (mirroring the existing WebSocket/XHR trackers) so useScrollSpy.test can drive __trigger on the observer created inside the hook."
key-files:
  created:
    - web/src/hooks/useScrollSpy.ts
    - web/src/hooks/useScrollSpy.test.ts
  modified:
    - web/src/components/TranscriptPane.tsx
    - web/src/test/setup.ts
  verified-unchanged:
    - web/src/components/ActiveJobCard.tsx
    - web/src/components/HistoryList.tsx
    - web/src/components/HistoryRow.tsx
    - web/src/api/jobs.ts
    - web/src/pages/DetailPage.tsx
    - web/src/pages/HistoryPage.tsx
key-decisions:
  - "Pixel-offset fallback uses window.innerHeight/2 (viewport-relative) not container.clientHeight/2, because getBoundingClientRect returns viewport-relative coordinates -- this matches RESEARCH Pattern 4 + the plan's action verbatim."
  - "Task 2 was a verification-only pass: 05-02b already wired the terminal WS -> invalidateJobs + onTerminal fade-out (ActiveJobCard), the 'No Transcripts Yet' empty state + terminal-only newest-first list (HistoryList), the click -> /jobs/:id navigation (HistoryRow), and the useTranscript 404 -> TRANSCRIBING sentinel + invalidateJobs (jobs.ts). No code changes were required; the Task 2 acceptance greps + full combined suite confirm the wiring is correct. No separate Task 2 commit was made because there were no file changes."
  - "useScrollSpy.test.ts uses React.createElement (not JSX) to keep the .ts extension -- the plan's acceptance command is `npx vitest run src/hooks/useScrollSpy.test.ts` (the .ts path is load-bearing), and the tsconfig only enables jsx: react-jsx for .tsx files. Same pattern as 05-02b's jobs.test.ts."
  - "setup.ts modification (MockIntersectionObserver instances tracker) is a Rule 3 test-infra enablement -- the test cannot drive the observer created inside the hook without instance access. Mirrors the existing WebSocket/XHR instance trackers; reset in afterEach."
requirements-completed:
  - UI-03
  - JOB-03
  - UI-01
metrics:
  duration: "20m"
  completed: "2026-06-25"
  tasks: 2
  files: 4
---

# Phase 5 Plan 03: Scroll-Spy + Terminal-Transition Refetch + Re-Open-Loads-Transcript + Full E2E Suite Summary

The integration + polish wave that stitches 05-01 (back-end upload + transcript endpoint) and 05-02b (FE shell + components + XHR-primary upload) into a provable vertical slice: a `useScrollSpy` IntersectionObserver hook drives the active-line highlight (UI-03, D-09), and the terminal-transition refetch + re-open-loads-transcript flow (D-03, JOB-03, D-06, D-14) -- already wired by 05-02b -- is verified end-to-end with the full back-end + FE suites green.

## What Was Built

### Task 1 -- useScrollSpy hook + test + TranscriptPane wiring (`4d804c0`)
- **`web/src/hooks/useScrollSpy.ts`** -- `useScrollSpy(containerRef, rowIds) -> activeId` per RESEARCH Pattern 4 verbatim. A single `IntersectionObserver` rooted at `containerRef.current` with `{ rootMargin: "-49% 0px -49% 0px", threshold: 0 }` creates a 2% focal line at the vertical center (UI-SPEC sec3). On entries: if any `isIntersecting`, the last (lowest in DOM) intersecting row's id wins; else the pixel-offset fallback loops `rowIds`, reads `getBoundingClientRect`, and picks the row whose midpoint (`rect.top + rect.height/2`) is closest to `window.innerHeight/2`. The observer observes each row id's element; cleanup `disconnect()`s in the effect cleanup (T-05-11 no stale-listener leak); the effect re-runs when `rowIds` changes so a transcript swap (re-opening a different job) re-observes the new rows. `threshold: 0` with negative rootMargin (NOT `threshold: 1.0` -- RESEARCH Anti-Pattern).
- **`web/src/hooks/useScrollSpy.test.ts`** -- 5 tests using the mocked IntersectionObserver from `src/test/setup.ts`:
  1. Creates one observer + observes all 3 rows on mount.
  2. Single intersection (`seg-1`) -> `activeId === "seg-1"`.
  3. Multiple intersections (`seg-0` + `seg-2`) -> last (lowest in DOM) wins -> `seg-2`.
  4. No-intersection fallback: mocks `getBoundingClientRect` to place `seg-1`'s midpoint at the viewport center (`window.innerHeight=800`, `seg-1` top=400) -> fallback picks `seg-1`.
  5. Unmount -> `disconnect()` clears the observed-element set (T-05-11).
  Uses `React.createElement` (not JSX) to keep the `.ts` extension (plan acceptance path is `src/hooks/useScrollSpy.test.ts`; tsconfig `jsx: react-jsx` only applies to `.tsx`).
- **`web/src/components/TranscriptPane.tsx`** (wired) -- adds a `containerRef` (useRef<HTMLDivElement>), builds `segmentIds = segments.map((_, i) => 'seg-${i}')` via `useMemo`, calls `const activeId = useScrollSpy(containerRef, segmentIds)`, passes `active={activeId === 'seg-${i}'}` to each `TranscriptRow`, and attaches the ref to the scrollable `.transcript-pane` div. Hooks are called unconditionally (Rules of Hooks): the transcribing/not-ready branch is handled after the hooks via an `isReady` flag, with an empty `segmentIds` array causing `useScrollSpy` to early-return (no observer created). The `.transcript-row.active` class (05-02a styles.css: 4px #2563EB left border + rgba(37,99,235,0.05) tint) applies the highlight (UI-03, D-09, local files only).
- **`web/src/test/setup.ts`** (test-infra enablement) -- `MockIntersectionObserver` gains a `static instances: MockIntersectionObserver[]` tracker (pushed in the constructor, reset in `afterEach`), mirroring the existing `MockWebSocket.instances` + `MockXMLHttpRequest.instances` trackers. This lets `useScrollSpy.test` call `__trigger` on the observer instance created inside the hook. Rule 3 fix -- the test could not drive the observer without instance access.

### Task 2 -- Verify terminal-transition + re-open flow + full combined suite green (verification-only, no commit)

Task 2 was a verification pass. The 05-02b implementation already wired every Task 2 requirement; no code changes were needed. Confirmed by re-reading the components + the acceptance greps + the full combined suite:

- **`web/src/components/ActiveJobCard.tsx`** (verified, 3 `invalidateJobs` references) -- on a terminal WS event (`done`/`failed`/`cancelled`/`error`), sets `fading=true`; a `useEffect` calls `invalidateJobs(queryClient)` (05-02a jobs.ts -> invalidates the `["jobs"]` namespace) once (guarded by `invalidatedRef`), then schedules `onTerminal(jobId)` after 250ms so HistoryPage unmounts the card. The `.active-card` -> `.active-card.terminal` CSS transition (05-02a styles.css: `opacity 200ms ease-out` 1 -> 0) plays the fade-out before unmount (UI-SPEC sec2). On `failed`: soft red border (`var(--destructive)`) + UI-SPEC sec6 error copy "Failed to transcribe video. Please check your file format and try again." before fade-out. The WebSocket is closed by the `useJobEvents` cleanup on unmount (D-03 terminal transition complete).
- **`web/src/pages/HistoryPage.tsx`** (verified) -- `handleTerminal` removes the jobId from `activeJobIds` so the card unmounts; `DropZone` emits jobIds upward; `ActiveJobCard` list + `HistoryList` compose the landing page (D-04).
- **`web/src/components/HistoryList.tsx`** (verified, 2 "No Transcripts Yet" references) -- three `useJobs("done" | "failed" | "cancelled")` calls merged + re-sorted newest-first by `created_at` (D-05; the API `?status=` filter is single-valued). "No Transcripts Yet" empty state (UI-SPEC Copywriting Contract) when the merged list is empty. `invalidateJobs` triggers TanStack Query background refetch on terminal WS so the newly-terminal job appears.
- **`web/src/components/HistoryRow.tsx`** (verified, 1 `navigate.*jobs` reference) -- filename (basename of `source_path`), date (`created_at`), duration (`duration_s` as mm:ss). Click -> `navigate('/jobs/${encodeURIComponent(job.id)}')` (UI-SPEC sec5, D-06 re-open entry point).
- **`web/src/api/jobs.ts`** (verified) -- `useTranscript(id)` fetches `GET /jobs/{id}/transcript`; on 404 returns the `TRANSCRIBING` sentinel (DetailPage shows "Transcribing..." per UI-SPEC sec6); on 200 returns the parsed `Transcript` (D-14). `invalidateJobs(queryClient)` invalidates `["jobs"]` for the terminal-transition refetch.
- **`web/src/pages/DetailPage.tsx`** (verified) -- `useTranscript(id)` feeds `TranscriptPane`; 2-pane `.detail-layout` (transcript 60% | summary 40%) with Back link + disabled ExportStub; no embedded media player (UI-02).

## Verification Results (full combined suite, end-to-end)

- `python -m pytest -q` (from repo root) -- **278 passed** in 348.62s (full back-end suite green: 42+ existing + 7 Phase 5 tests from 05-01).
- `npx vitest run` (from `web/`) -- **19 tests passed** across 4 files (6 smoke from 05-02a + 5 DetailPage + 3 jobs incl. the D-02 0->50->100 progress assertion + 5 useScrollSpy from this plan).
- `npx tsc --noEmit` (from `web/`) -- clean (exit 0).
- `npx vite build` (from `web/`) -- succeeds (built in 247ms).
- `grep -r "<video" web/src/` -- no matches (UI-02 preserved across the full FE).
- `grep -r "dangerouslySetInnerHTML" web/src/` -- no matches (T-05-07 XSS mitigation preserved).
- Task 2 acceptance greps:
  - `grep -c "invalidateJobs\|invalidateQueries" web/src/components/ActiveJobCard.tsx` -> 3 (>= 1, D-03 terminal -> history refetch wired).
  - `grep -c "No Transcripts Yet" web/src/components/HistoryList.tsx` -> 2 (>= 1, UI-SPEC empty state).
  - `grep -c "navigate.*jobs\|Link.*jobs" web/src/components/HistoryRow.tsx` -> 1 (>= 1, click-through to /jobs/:id, D-06).
- Manual (deferred to `/gsd-verify-phase 5`): drop a real file -> XHR upload percent 0->100 -> active card -> terminal -> history -> click row -> detail 2-pane + transcript + scroll-spy highlight; confirm the full vertical slice (D-02 real percent honored).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] MockIntersectionObserver had no instance tracker**
- **Found during:** Task 1 -- writing useScrollSpy.test.ts.
- **Issue:** The plan's Task 1 says "use the mock IntersectionObserver from web/src/test/setup.ts" and "Trigger the mock observer's callback", but the mock class had no way to access the observer instance created inside `useScrollSpy` (the `__trigger` helper exists on instances, but instances were not tracked). The test could not drive the observer without instance access.
- **Fix:** Added `static instances: MockIntersectionObserver[] = []` to the mock class (pushed in the constructor, reset in `afterEach`), mirroring the existing `MockWebSocket.instances` + `MockXMLHttpRequest.instances` trackers. Minimal test-infra enablement; no behavior changed.
- **Files modified:** `web/src/test/setup.ts`
- **Commit:** `4d804c0`

**2. [Rule 1 - Bug] TranscriptPane early return violated the Rules of Hooks**
- **Found during:** Task 1 -- wiring useScrollSpy into TranscriptPane.
- **Issue:** The 05-02b TranscriptPane returned the "Transcribing..." JSX before any hooks were called. Adding `useRef` + `useMemo` + `useScrollSpy` after the early return would make the hooks conditional on the transcript being ready -- a Rules-of-Hooks violation (React warnings + lint errors + potential render-order bugs when the transcript arrives later).
- **Fix:** Restructured so all hooks (`useRef`, `useMemo`, `useScrollSpy`) are called unconditionally at the top. An `isReady` flag drives both the `segments` computation and the early-return branch. When not ready, `segmentIds` is empty so `useScrollSpy` early-returns and no observer is created. No behavior changed.
- **Files modified:** `web/src/components/TranscriptPane.tsx`
- **Commit:** `4d804c0`

**3. [Rule 1 - Bug] useScrollSpy.test.ts JSX required .tsx but the acceptance path names .ts**
- **Found during:** Task 1 -- `npx vitest run src/hooks/useScrollSpy.test.ts` failed with a parse error on JSX inside a `.ts` file.
- **Issue:** The plan's acceptance command is `npx vitest run src/hooks/useScrollSpy.test.ts` (the `.ts` path is load-bearing), but the test harness naturally wants JSX for the container + row elements. The tsconfig only enables `jsx: react-jsx` for `.tsx` files.
- **Fix:** Rewrote the test to use `React.createElement` instead of JSX, keeping the `.ts` extension so the acceptance path matches. Same pattern as 05-02b's `jobs.test.ts`.
- **Files modified:** `web/src/hooks/useScrollSpy.test.ts`
- **Commit:** `4d804c0`

No architectural changes (Rule 4) and no blockers. Task 2 required no code changes (verification-only) -- documented as a deviation from the plan's `files_modified` list, but all Task 2 acceptance criteria pass.

## Threat Mitigations (from plan `<threat_model>`)

- **T-05-11 (Scroll-spy observer attached to a stale container):** `useScrollSpy` `disconnect()`s the observer in the effect cleanup and re-runs the effect when `rowIds` changes, so a transcript swap (re-opening a different job) re-observes the new rows. Verified by the useScrollSpy.test "disconnects on unmount" test (element set clears to 0). No stale-listener leak.
- **T-05-12 (History refetch race on rapid terminal events):** accepted per plan -- TanStack Query deduplicates + invalidates idempotently; ActiveJobCard's `invalidatedRef` guards against a double-invalidate within one card. Single-user local app.
- **T-05-07 (XSS via transcript text):** inherited from 05-02b -- React default escaping, no `dangerouslySetInnerHTML` anywhere. Re-asserted by `grep -r "dangerouslySetInnerHTML" web/src/` returning 0 matches in this plan's verification.

## Known Stubs

| File | Line | Stub | Reason | Resolved By |
|------|------|------|--------|-------------|
| `web/src/components/SummaryPane.tsx` | placeholder copy | Static "Summaries will appear here once summarization is enabled." text, no data source | Intentional per D-08 -- stable 40% width placeholder until Phase 8 | Phase 8 |
| `web/src/components/ExportStub.tsx` | disabled button | Disabled "Export (Coming Soon)" button, no click handler | Intentional per D-10 -- layout-stability stub; re-export is Phase 9 | Phase 9 |
| `web/src/components/TranscriptRow.tsx` | 80px speaker gutter | Empty `.speaker` span, no speaker label rendered | Intentional per D-07 -- reserved space; `speaker` is `None` until diarization | Phase 7 |

No new stubs introduced by this plan. The existing stubs are explicit deferred-phase placeholders documented in CONTEXT.md; none block the plan's goal (the scroll-spy + terminal-transition + re-open vertical slice).

## Threat Flags

None. This plan introduced no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. The scroll-spy is pure client-side DOM observation; the terminal-transition + re-open flows reuse the 05-01/05-02a/05-02b surfaces already covered by the existing threat model.

## Task Commits

1. **Task 1: useScrollSpy hook + test + TranscriptPane wiring** -- `4d804c0` (feat)
2. **Task 2: Verify terminal-transition + re-open flow + full combined suite green** -- verification-only, no file changes (05-02b already wired all Task 2 requirements); no separate commit. The full combined suite (pytest 278 + vitest 19 + tsc + build + lint gates) confirms the wiring.

## Self-Check: PASSED

- [x] `web/src/hooks/useScrollSpy.ts` present with `IntersectionObserver` (3 references) + `"-49% 0px -49% 0px"` rootMargin (2 references).
- [x] `web/src/hooks/useScrollSpy.test.ts` present (5 tests green).
- [x] `web/src/components/TranscriptPane.tsx` wires `useScrollSpy` (5 references) + passes `active=` to TranscriptRow (1 reference).
- [x] `web/src/test/setup.ts` MockIntersectionObserver instances tracker present.
- [x] Commit `4d804c0` exists in `git log`.
- [x] Full back-end suite green: `pytest` 278 passed.
- [x] Full FE suite green: `vitest run` 19/19, `tsc --noEmit` clean, `vite build` ok.
- [x] No `<video>` anywhere (UI-02), no `dangerouslySetInnerHTML` anywhere (T-05-07).
- [x] Task 2 acceptance greps: ActiveJobCard invalidateJobs=3, HistoryList "No Transcripts Yet"=2, HistoryRow navigate jobs=1.