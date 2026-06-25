---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 02a
subsystem: frontend-foundation
tags: [vite, react, typescript, tanstack-query, react-router, vitest, jsdom, openapi-typescript, design-system, websockets]
requires:
  - "Phase 05-01: back-end 'uploading' JobStatus + POST /jobs/upload + GET /jobs/{id}/transcript (OpenAPI schema the codegen reads)"
  - "Phase 4: WS /ws/jobs/{id}/events snapshot+live event contract (D-08), idempotency-key reservation (D-07)"
  - "Phase 3: Transcript / TranscriptSegment schema (codegen'd into types.ts)"
provides:
  - "web/ Vite + React + TS + TanStack Query + React Router 8 + openapi-typescript scaffold (D-12)"
  - "web/src/api/client.ts: apiFetch + idempotencyKey(filename,size,lastModified) SHA-256->32 hex (D-11, D-07, Open Questions #3)"
  - "web/src/api/ws.ts: useJobEvents(jobId) native WebSocket hook (Phase 4 D-08)"
  - "web/src/api/jobs.ts: useJobs/useJob/useTranscript TanStack Query hooks + invalidateJobs + TRANSCRIBING sentinel (D-12, D-14)"
  - "web/src/api/types.ts: openapi-typescript codegen (incl. 'uploading' status)"
  - "web/scripts/gen-types.sh: codegen wrapper"
  - "Vitest jsdom infra (vitest.config.ts + src/test/setup.ts) mocking IntersectionObserver, WebSocket, fetch, XHR(+upload), crypto.subtle"
  - "CSS Design System tokens + .detail-layout / .transcript-pane / .summary-pane / .transcript-row / .active classes (UI-SPEC Design System + sec4)"
affects:
  - "05-02b: consumes client/ws/jobs API layer, types, styles, and vitest infra to build the app shell + components + useUpload"
  - "05-03: consumes useScrollSpy + invalidateJobs + TranscriptPane active-row contract for scroll-spy + terminal transitions"
tech-stack:
  added:
    - "vite + @vitejs/plugin-react"
    - "react 19 + react-dom + react-router 8"
    - "@tanstack/react-query"
    - "typescript (tsc --noEmit build gate)"
    - "vitest + jsdom + @testing-library/react + @testing-library/dom"
    - "openapi-typescript (codegen)"
    - "lucide-react, @radix-ui/react-dialog, oxlint"
  patterns:
    - "Codegen-first typing: all job/transcript shapes from OpenAPI types.ts, no hand-written model interfaces, no any (RESEARCH Anti-Patterns)"
    - "apiFetch base-URL wrapper + ApiError(status,body) for non-2xx (UI-SPEC sec1)"
    - "Idempotency-Key derived client-side via crypto.subtle SHA-256(filename-size-lastmodified)->32 hex, within back-end [A-Za-z0-9_-]{1,128} cap (T-05-10)"
    - "Native WebSocket (not socket.io) per D-08; jobId|null stays disconnected, reconnects on change, cleans up on unmount"
    - "TRANSCRIBING sentinel for 404 transcript (D-14) instead of throwing; retry skips 404"
    - "invalidateJobs(queryClient) single invalidation entrypoint for terminal transitions (consumed by 05-02b/05-03)"
key-files:
  created:
    - web/package.json
    - web/tsconfig.json
    - web/tsconfig.node.json
    - web/vite.config.ts
    - web/vitest.config.ts
    - web/index.html
    - web/scripts/gen-types.sh
    - web/src/api/types.ts
    - web/src/api/client.ts
    - web/src/api/ws.ts
    - web/src/api/jobs.ts
    - web/src/styles.css
    - web/src/test/setup.ts
    - web/src/test/smoke.test.ts
  modified: []
key-decisions:
  - "Added @testing-library/dom (^10) as an explicit devDependency — it is a peer of @testing-library/react (^16) that npm ERESOLVE skipped; required for setup.ts auto-cleanup import to resolve. Installed with --legacy-peer-deps to match the repo's existing openapi-typescript/typescript peer resolution."
  - "types.ts generated from the live back-end OpenAPI (localhost:8000/openapi.json) so the 'uploading' status added by 05-01 is present (3 references). gen-types.sh documents the backend-must-be-running requirement."
  - "smoke.test.ts is the only FE test in 05-02a (6 tests); the full FE suite (jobs.test.ts, DetailPage.test.tsx, useScrollSpy.test.ts) lands in 05-02b/05-03 per VALIDATION.md Wave 0 staging."
patterns-established:
  - "FE API layer shape: client.ts (transport) / ws.ts (events) / jobs.ts (TanStack hooks) split — 05-02b/05-03 import from here, never hand-roll fetch"
  - "Query key factory jobsKeys.{all,list,detail,transcript} for cache invalidation across hooks"
  - "Test-infra mocks expose __trigger/__progress/__respond helpers for deterministic observer/XHR driving"
requirements-completed: []  # INGEST-01, UI-01, UI-02 are partially satisfied (FE foundation); completed by 05-02b/05-03
metrics:
  duration: "resumed"
  completed: "2026-06-25"
  tasks: 2
  files: 14
---

# Phase 5 Plan 02a: Front-end Scaffold + API/WS Layer + Design System Summary

Greenfield `web/` Vite+React+TS app with TanStack Query + React Router 8, vitest jsdom test infrastructure, the full API/WebSocket layer (code-first against generated OpenAPI types), and the CSS Design System tokens + 2-pane layout classes — the foundational FE plan that 05-02b and 05-03 build on.

## What Was Built

### Task 1 — Vite scaffold + Vitest jsdom infra + CSS Design System (`be45a5e`)
- **Vite + React 19 + TS scaffold** — `web/package.json`, `vite.config.ts`, `tsconfig.json`/`tsconfig.node.json`, `index.html`. Deps: react, react-dom, react-router 8, @tanstack/react-query, lucide-react, @radix-ui/react-dialog. DevDeps: vite, @vitejs/plugin-react, typescript, vitest, jsdom, @testing-library/react, openapi-typescript, oxlint.
- **Vitest jsdom infra** — `vitest.config.ts` (jsdom env, setup file) + `src/test/setup.ts` (290 lines) mocking IntersectionObserver, WebSocket, fetch, XMLHttpRequest (+ `xhr.upload` with `onprogress`), and crypto.subtle, with `__trigger`/`__progress`/`__respond` helpers for deterministic test driving.
- **CSS Design System** — `src/styles.css` (213 lines): design tokens + `.detail-layout` (2-pane grid), `.transcript-pane`, `.summary-pane`, `.transcript-row` + `.active` (scroll-spy highlight target), `.drop-zone`. Matches UI-SPEC Design System + sec4 so 05-02b/05-03 components render against stable classes.

### Task 2 — API/WS layer + codegen types + vitest smoke (`0bee3cc`)
- **`src/api/client.ts`** — `apiFetch<T>(path, init)` base-URL wrapper with JSON headers + `ApiError(status, body)` on non-2xx; **`idempotencyKey(filename, size, lastModified)`** deriving the `Idempotency-Key` header via `crypto.subtle.digest("SHA-256", "${filename}-${size}-${lastModified}")` truncated to 32 hex chars — deterministic, well inside the back-end `[A-Za-z0-9_-]{1,128}` cap (D-11, D-07, RESEARCH Open Questions #3 RESOLVED, T-05-10).
- **`src/api/ws.ts`** — `useJobEvents(jobId)` native WebSocket hook (D-08): connects to `ws://localhost:8000/ws/jobs/{id}/events`, parses the snapshot-on-connect + live `progress`/`stage_changed`/`done`/`failed`/`cancelled`/`error` events, returns the latest event (or `null`), reconnects on `jobId` change, cleans up on unmount.
- **`src/api/jobs.ts`** — TanStack Query hooks `useJobs(status)`, `useJob(id)`, `useTranscript(id)` (returns `Transcript | TRANSCRIBING` sentinel on 404, D-14), all typed against codegen'd `components["schemas"]`. `invalidateJobs(queryClient)` single invalidation entrypoint for terminal transitions (consumed by 05-02b ActiveJobCard + 05-03). `jobsKeys` query-key factory.
- **`src/api/types.ts`** — openapi-typescript codegen from the back-end OpenAPI schema (57 KB); includes the `uploading` JobStatus value added by 05-01 (3 references). `web/scripts/gen-types.sh` wraps regeneration (requires back-end on localhost:8000).
- **`src/test/smoke.test.ts`** — 6 tests proving the jsdom infra (IntersectionObserver, XHR+upload, WebSocket mocks) and `idempotencyKey` determinism/length.

## Performance

- **Tasks:** 2/2 complete
- **Files created:** 14
- **Self-check:** `tsc --noEmit` clean, `vite build` ok, `vitest run` 6/6 green.

## Task Commits

1. **Task 1: Vite scaffold + Vitest jsdom infra + CSS Design System** — `be45a5e` (feat)
2. **Task 2: API/WS layer (client/ws/jobs) + codegen types + vitest smoke** — `0bee3cc` (feat)

## Deviations / Close-out Note

Plan 05-02a was interrupted mid-Task-2 by a provider session usage limit (HTTP 429) while the executor was between writing the API-layer files and committing them. Task 1 had already committed (`be45a5e`); Task-2 files were on disk but uncommitted and `smoke.test.ts` had a single corrupted line (`#` instead of `//` on line 2, truncated mid-write). Per the execute-phase safe-resume gate, the plan was **closed out manually**:

- Fixed the `smoke.test.ts` line-2 corruption.
- Diagnosed and fixed a missing test peer dependency: `@testing-library/dom` (^10) — a peer of `@testing-library/react` (^16) that npm ERESOLVE had skipped. Added to `web/package.json` devDeps and installed with `--legacy-peer-deps` (matching the repo's existing openapi-typescript/typescript peer resolution).
- Removed a stray `.openapi-snapshot.json` scratch artifact at repo root (not referenced by any plan, not in `files_modified`).
- Verified the full Task-2 surface (tsc + vitest + vite build), then committed Task 2 atomically.

No behavior changed beyond the close-out fixes; all plan `must_haves` truths hold.

## Self-Check: PASSED

- [x] `web/` Vite dev tooling boots (`tsc --noEmit` clean, `vite build` succeeds)
- [x] Vitest jsdom infra + setup mocks exist (IO/WS/fetch/XHR+upload/crypto.subtle) — smoke test proves them
- [x] API layer type-correct against codegen'd OpenAPI types; `idempotencyKey` SHA-256->32 hex helper present
- [x] `types.ts` includes the `uploading` status (codegen reflects 05-01's schema change)
- [x] CSS Design System tokens + `.detail-layout` + `.transcript-row` + `.active` classes defined
- [x] All 14 `files_modified` present; 2 task commits + this summary