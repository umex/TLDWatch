---
phase: 05-local-file-ingest-history-ui-3-pane-layout
plan: 02a
type: execute
wave: 1
depends_on: []
files_modified:
  - web/package.json
  - web/tsconfig.json
  - web/vite.config.ts
  - web/index.html
  - web/vitest.config.ts
  - web/src/test/setup.ts
  - web/src/styles.css
  - web/scripts/gen-types.sh
  - web/src/api/types.ts
  - web/src/api/client.ts
  - web/src/api/ws.ts
  - web/src/api/jobs.ts
autonomous: true
requirements: [INGEST-01, UI-01, UI-02]
must_haves:
  truths:
    - "The web/ Vite dev server boots (tsc clean) and the FE codebase is scaffolded per D-12 (Vite + React + TS + TanStack Query + React Router 8 + openapi-typescript)"
    - "Vitest jsdom infra + test setup (mock IntersectionObserver/WebSocket/fetch) exist so 05-02b/05-03 FE tests can run (per VALIDATION.md Wave 0)"
    - "The API layer (client.ts, ws.ts, jobs.ts) is type-correct against the codegen'd OpenAPI types and exposes the Idempotency-Key SHA-256 helper (D-11, D-07, UI-SPEC §1, RESEARCH Open Questions #3)"
    - "The CSS Design System tokens + .detail-layout + .transcript-row + .active classes are defined so 05-02b/05-03 components can render the 2-pane detail + scroll-spy highlight (UI-01, UI-03, UI-SPEC Design System + §4)"
  artifacts:
    - path: "web/package.json"
      provides: "Vite + React + TS + TanStack Query + React Router 8 + openapi-typescript + vitest deps"
      contains: "react-router"
    - path: "web/vitest.config.ts"
      provides: "Vitest jsdom config for FE tests"
    - path: "web/src/test/setup.ts"
      provides: "Vitest setup: mock IntersectionObserver, WebSocket, fetch, XHR"
    - path: "web/src/api/client.ts"
      provides: "apiFetch + idempotencyKey(filename, size, lastModified) SHA-256->32 hex helper"
    - path: "web/src/api/ws.ts"
      provides: "useJobEvents(jobId) native WebSocket hook (Phase 4 D-08 contract)"
    - path: "web/src/api/jobs.ts"
      provides: "useJobs(status?), useJob(id), useTranscript(id), jobsKeys, invalidateJobs helper"
    - path: "web/src/api/types.ts"
      provides: "Codegen'd TS types from /openapi.json (JobResponse incl uploading, Transcript, TranscriptSegment)"
    - path: "web/src/styles.css"
      provides: "CSS variables + .detail-layout + .transcript-row + .active"
      contains: "detail-layout"
    - path: "web/scripts/gen-types.sh"
      provides: "openapi-typescript codegen script -> web/src/api/types.ts"
  key_links:
    - from: "web/scripts/gen-types.sh"
      to: "/openapi.json"
      via: "openapi-typescript codegen"
      pattern: "openapi-typescript"
    - from: "web/src/api/client.ts"
      to: "POST /jobs/upload (05-01)"
      via: "idempotencyKey header derivation consumed by useUpload (05-02b)"
      pattern: "Idempotency-Key"
    - from: "web/src/api/ws.ts"
      to: "/ws/jobs/{id}/events"
      via: "native WebSocket"
      pattern: "useJobEvents"
---

<objective>
Greenfield React front-end scaffold + test infrastructure + the full API/WS layer + codegen'd types + the CSS Design System. This is the foundational FE plan that 05-02b (app shell + components) and 05-03 (scroll-spy + integration) build on.

Purpose: Split out from the original 05-02 to protect hand-written-file quality (client.ts, ws.ts, jobs.ts, styles.css get room) and respect the 15-file plan guidance. This plan owns the Vite scaffold, Vitest jsdom infra, the openapi-typescript codegen, the fetch/WS/TanStack Query API layer, and the CSS tokens/grid classes — everything 05-02b's components import. Runs in parallel with 05-01 (back-end) because the FE API layer is built against the documented contract + the already-exposed OpenAPI models; integration is verified in 05-03. Per D-04, D-12, D-13, D-14, UI-SPEC Design System, RESEARCH Standard Stack + Anti-Patterns + Open Questions #3 (idempotency key SHA-256, RESOLVED -> 05-02a Task 2).

Output: A bootable `web/` Vite app shell, Vitest infra + test setup (mock IntersectionObserver/WebSocket/fetch/XHR), codegen'd TS types, the API client + WS hook + TanStack Query jobs hooks (+ invalidateJobs helper), and the CSS Design System styles.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-CONTEXT.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md
@.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-VALIDATION.md
@app/api/routes_ws.py
@app/models/job.py
@app/models/transcript.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Vite scaffold + deps + Vitest infra + test setup + CSS Design System (D-12, D-13)</name>
  <files>web/package.json, web/tsconfig.json, web/vite.config.ts, web/index.html, web/vitest.config.ts, web/src/test/setup.ts, web/src/styles.css</files>
  <read_first>
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md (Standard Stack table — exact versions: vite 8.1.0, react 19.2.7, react-dom 19.2.7, typescript 6.0.3, @vitejs/plugin-react 6.0.3, @tanstack/react-query 5.101.1, react-router 8.0.1, openapi-typescript 7.13.0, lucide-react 1.21.0, @radix-ui/react-dialog 1.1.17; Alternatives Considered — DO NOT use react-router-dom; Anti-Patterns — DO NOT hand-write TS types; Validation Architecture — Wave 0 gaps: vitest.config.ts, setup.ts)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md (Design System — spacing scale xs=4px..3xl=64px, color #FAFAFA/#FFFFFF/#2563EB/#DC2626, typography 14/12/20/28px system font stack; §4 transcript row grid 64px|80px|1fr; §3 active row 4px left #2563EB border + rgba(37,99,235,0.05) tint)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md (FE block — each file mapped to UI-SPEC section + RESEARCH Pattern/Example + framework default; rows: web/vitest.config.ts, web/src/test/setup.ts, web/src/styles.css)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-VALIDATION.md (Wave 0 Requirements list — vitest.config.ts + setup.ts are Wave 0 gaps created here; annotated "created TDD-style in implementation task" where applicable)
    - .planning/PROJECT.md (FE/BE separated; desktop-browser-only; no dark mode; system font stack)
  </read_first>
  <action>
    Scaffold the web/ dir. Run `npm create vite@latest . -- --template react-ts` inside a new `web/` directory at the repo root (this creates package.json, tsconfig.json, vite.config.ts, index.html, src/main.tsx, src/App.tsx — 05-02b owns main.tsx/App.tsx content; here they stay as the Vite template default). Then install the exact pinned versions from RESEARCH Standard Stack:
    `npm install react@19.2.7 react-dom@19.2.7 @tanstack/react-query@5.101.1 react-router@8.0.1 lucide-react@1.21.0 @radix-ui/react-dialog@1.1.17`
    `npm install -D typescript@6.0.3 @vitejs/plugin-react@6.0.3 openapi-typescript@7.13.0 vitest @testing-library/react jsdom`
    (vitest ships with Vite; install the matching version. Do NOT install react-router-dom — react-router 8.x is the current single package per RESEARCH Pitfall 6.)

    Create web/vitest.config.ts: jsdom environment, globals true, setupFiles ["./src/test/setup.ts"], include ["src/**/*.test.ts","src/**/*.test.tsx"]. Reference Vite+Vitest default config.

    Create web/src/test/setup.ts: import "@testing-library/react"; mock global.IntersectionObserver (class with observe/unobserve/disconnect no-ops + a __trigger helper for tests), mock global.WebSocket (minimal class with send/close + onmessage/onopen/onerror), mock global.fetch via vi.fn, AND mock global.XMLHttpRequest + xhr.upload object (the 05-02b useUpload hook + its progress test rely on the XHR mock — provide a minimal class with open, setRequestHeader, send, upload: {onprogress:null}, onload, onerror, readyState, status, response). This satisfies VALIDATION.md Wave 0 and supports the XHR-primary useUpload path (05-02b, D-02 real percent).

    Create web/src/styles.css: CSS variables from UI-SPEC Design System — spacing tokens (xs 4px, sm 8px, md 16px, lg 24px, xl 32px, 2xl 48px, 3xl 64px), colors (--bg #FAFAFA, --surface #FFFFFF, --accent #2563EB, --destructive #DC2626), system font stack, typography sizes (14/12/20/28px). Include the detail-layout grid (60% | 40%, gap 24px, height 100vh, padding 32px) and the transcript-row grid (64px 80px 1fr, line-height 1.5, active row: 4px left #2563EB border + rgba(37,99,235,0.05) tint) per UI-SPEC §4 + RESEARCH Example 5. The active-row class is used by 05-03's scroll-spy; define it here. Also define an .active-card fade-out transition (opacity 1 -> 0 over ~200ms) used by 05-02b/05-03 ActiveJobCard terminal transition (UI-SPEC §2).

    Per D-12, D-13, UI-SPEC Design System, RESEARCH Standard Stack + Anti-Patterns.
  </action>
  <verify>
    <automated>cd web && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `test -f web/package.json && grep -c "react-router" web/package.json` returns >= 1 (react-router 8 installed, NOT react-router-dom).
    - `grep -c "react-router-dom" web/package.json` returns 0 (legacy package NOT installed).
    - `test -f web/vitest.config.ts` exits 0.
    - `test -f web/src/test/setup.ts` exits 0.
    - `grep -c "IntersectionObserver" web/src/test/setup.ts` returns >= 1 (mock present).
    - `grep -c "XMLHttpRequest" web/src/test/setup.ts` returns >= 1 (XHR mock present for 05-02b useUpload primary path).
    - `test -f web/src/styles.css && grep -c "#2563EB" web/src/styles.css` returns >= 1 (accent color from UI-SPEC).
    - `grep -c "detail-layout\|transcript-row" web/src/styles.css` returns >= 2 (grid layouts defined).
    - `cd web && npx tsc --noEmit` exits 0 (types compile).
  </acceptance_criteria>
  <done>web/ scaffold boots (tsc clean); Vitest jsdom configured; test setup mocks IntersectionObserver/WebSocket/fetch/XHR; CSS Design System tokens + .detail-layout + .transcript-row + .active + .active-card classes defined.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: API layer (client.ts idempotencyKey SHA-256, ws.ts useJobEvents, jobs.ts TanStack Query hooks + invalidateJobs) + openapi-typescript codegen (D-11, D-14, Phase 4 D-07/D-08)</name>
  <files>web/scripts/gen-types.sh, web/src/api/types.ts, web/src/api/client.ts, web/src/api/ws.ts, web/src/api/jobs.ts</files>
  <read_first>
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-RESEARCH.md (Pattern 2 — useUpload contract the client supports (XHR-primary, 05-02b); Pattern 3 — useJobs TanStack Query; Example 4 — useJobEvents WS hook; Example 5 — CSS Grid; Open Questions #3 RESOLVED -> idempotencyKey SHA-256->32 hex; Pitfall 6 — react-router not react-router-dom)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-UI-SPEC.md (§1 Idempotency-Key derivation [filename]-[size]-[lastmodified] hashed; §2 active card WS event mapping)
    - .planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-PATTERNS.md (rows: web/src/api/client.ts, web/src/api/types.ts, web/src/api/jobs.ts, web/src/api/ws.ts — UI-SPEC + RESEARCH + back-end contract mapping)
    - app/api/routes_ws.py (lines 180-188 — snapshot shape {type:"snapshot", job_id, stage, percent, eta, status} + live events {type:"progress"|"stage_changed"|"done"|"failed"|"cancelled"})
    - app/models/job.py (JobResponse fields incl the 'uploading' status 05-01 adds; id, status, created_at, source_type, source_path, current_stage, duration_s, language, summary_kinds, updated_at, error)
    - app/models/transcript.py (TranscriptSegment: start_s, end_s, text, speaker=None, confidence; Transcript: schema_version, job_id, language, segments)
  </read_first>
  <behavior>
    - gen-types.sh runs openapi-typescript against http://localhost:8000/openapi.json and emits web/src/api/types.ts (or types.ts is hand-bootstrapped from app/models/{job,transcript}.py if the back-end is not up yet).
    - client.ts exports apiFetch (fetch wrapper, base URL http://localhost:8000) and idempotencyKey(filename, size, lastModified) that SHA-256 hashes [filename]-[size]-[lastmodified] via crypto.subtle and truncates to 32 hex chars (stays under the 128-char [A-Za-z0-9_-] cap, RESEARCH Open Questions #3 RESOLVED).
    - ws.ts exports useJobEvents(jobId: string | null) that opens a native WebSocket to ws://localhost:8000/ws/jobs/{jobId}/events, parses snapshot + live events, returns the latest event, and cleans up on unmount.
    - jobs.ts exports useJobs(status?), useJob(id), useTranscript(id) (404 -> "transcribing" sentinel), jobsKeys factory, and invalidateJobs(queryClient) helper (used by 05-02b ActiveJobCard terminal transition + 05-03).
    - All hooks consume the codegen'd types (no hand-written model types, no `any` for job/transcript shapes).
  </behavior>
  <action>
    Create web/scripts/gen-types.sh: `openapi-typescript http://localhost:8000/openapi.json -o web/src/api/types.ts` (chmod +x). Run it once the back-end (05-01) is up to generate web/src/api/types.ts. Because 05-01 may not have landed the new routes yet, the codegen captures the already-exposed models (JobResponse, Transcript, TranscriptSegment — already registered in app/main.py::_EXTRA_OPENAPI_MODELS). If the back-end is not running, hand-bootstrap web/src/api/types.ts with the three model interfaces matching app/models/{job,transcript}.py (transitional — regen via gen-types.sh once 05-01 lands). Do NOT hand-write types for any model not already in the OpenAPI schema.

    Create web/src/api/client.ts: a fetch wrapper with base URL `http://localhost:8000` (Vite proxy or direct), an `idempotencyKey(filename, size, lastModified)` helper that derives the UI-SPEC §1 key: hash `[filename]-[size]-[lastmodified]` via crypto.subtle SHA-256 truncated to 32 hex chars (RESOLVED per Open Questions #3 -> 05-02a Task 2). Export `apiFetch` + `idempotencyKey`. The XHR-primary useUpload hook (05-02b) consumes idempotencyKey to set the Idempotency-Key header.

    Create web/src/api/ws.ts: `useJobEvents(jobId: string | null)` hook per RESEARCH Example 4 — opens `new WebSocket("ws://localhost:8000/ws/jobs/${jobId}/events")`, parses snapshot + live events (type: "snapshot"|"progress"|"stage_changed"|"done"|"failed"|"cancelled"), returns the latest event. Cleanup on unmount. The event shapes are defined in app/api/routes_ws.py.

    Create web/src/api/jobs.ts: TanStack Query hooks — `useJobs(status?: JobStatus)` (queryKey ["jobs", status], queryFn -> GET /jobs?status=...), `useJob(id)` (GET /jobs/{id}), `useTranscript(id)` (GET /jobs/{id}/transcript, 404 -> "transcribing" sentinel). Export the hooks + a `jobsKeys` factory + `invalidateJobs(queryClient)` (queryClient.invalidateQueries on ["jobs"]) used by 05-02b ActiveJobCard terminal transition + 05-03. These consume the codegen'd types — no hand-written model interfaces, no `any` for job/transcript shapes (D-12; RESEARCH Anti-Patterns).

    Per D-12, D-14, D-11, Phase 4 D-07 (Idempotency-Key), Phase 4 D-08 (WS contract), UI-SPEC §1/§2, RESEARCH Pattern 3 + Example 4 + Open Questions #3 (RESOLVED).
  </action>
  <verify>
    <automated>cd web && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `test -f web/scripts/gen-types.sh` exits 0.
    - `test -f web/src/api/types.ts` exits 0 (codegen output or hand-bootstrap).
    - `grep -v '^#' web/src/api/client.ts | grep -c "idempotencyKey"` returns >= 1 (Idempotency-Key SHA-256 derivation present, RESOLVED Open Questions #3).
    - `grep -c "SHA-256\|crypto.subtle\|sha-256" web/src/api/client.ts` returns >= 1 (hashing used, not raw concatenated key).
    - `test -f web/src/api/ws.ts && grep -c "useJobEvents" web/src/api/ws.ts` returns >= 1.
    - `test -f web/src/api/jobs.ts && grep -c "useTranscript\|useJobs\|invalidateJobs" web/src/api/jobs.ts` returns >= 3 (hooks + invalidation helper all present).
    - `cd web && npx tsc --noEmit` exits 0 (full FE type-check; hooks consume codegen'd types, no `any`).
  </acceptance_criteria>
  <done>Codegen script + types present; client.ts (apiFetch + idempotencyKey SHA-256), ws.ts (useJobEvents), jobs.ts (useJobs/useJob/useTranscript/jobsKeys/invalidateJobs) all type-correct against the OpenAPI types.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser -> POST /jobs/upload (via 05-02b useUpload) | FE sends Idempotency-Key derived in client.ts (localhost-only) |
| Browser -> /ws/jobs/{id}/events | FE opens a WebSocket per active card (localhost-only) |
| Browser -> GET /jobs, GET /jobs/{id}/transcript | FE reads job list + transcript (localhost-only) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-05-08 | Spoofing | CORS / WS origin abuse from a rogue local page | accept | CORSMiddleware restricts allow_origins to localhost:5173 + 127.0.0.1:5173 (app/main.py, no Phase 5 change); TrustedHostMiddleware allow-lists localhost; single-user localhost-only app (PROJECT.md). No FE action — the back-end boundary holds. |
| T-05-10 | Tampering | Idempotency-Key collision / spoofing | mitigate | FE derives the key via crypto.subtle SHA-256([filename]-[size]-[lastmodified]) truncated to 32 hex chars (UI-SPEC §1 + RESEARCH Open Questions #3 RESOLVED -> 05-02a Task 2); back-end validate_idempotency_key enforces [A-Za-z0-9_-]{1,128} (Phase 4). |
| T-05-SC | Tampering | npm installs (vite, react, react-router, tanstack-query, openapi-typescript, lucide-react, radix-dialog, vitest, testing-library, jsdom) | accept | All packages OK/Approved in RESEARCH Package Legitimacy Audit (top-tier, established registries, 2026 publish dates); no [SUS]/[SLOP]; no blocking checkpoint needed. |

## Mitigation Traceability

- T-05-10 -> Task 2 action: "idempotencyKey(filename, size, lastModified) ... SHA-256 ... truncated to 32 hex chars" (RESOLVED Open Questions #3).
</threat_model>

<verification>
- `cd web && npx tsc --noEmit` — full FE type-checks clean.
- `grep -c "react-router-dom" web/package.json` returns 0 (legacy package not installed — Pitfall 6).
- `grep -c "SHA-256\|crypto.subtle\|sha-256" web/src/api/client.ts` returns >= 1 (idempotency key hashed, Open Questions #3 RESOLVED).
- `grep -c "XMLHttpRequest" web/src/test/setup.ts` returns >= 1 (XHR mock present for 05-02b XHR-primary useUpload).
- `grep -c "detail-layout\|transcript-row" web/src/styles.css` returns >= 2 (CSS Grid layouts defined for 05-02b/05-03).
- Manual (deferred to /gsd-verify-phase): `cd web && npm run dev` boots the Vite dev server on :5173.
</verification>

<success_criteria>
- The web/ Vite dev server boots and tsc is clean (D-12, D-13).
- Vitest jsdom infra + test setup (mock IntersectionObserver/WebSocket/fetch/XHR) exist (VALIDATION Wave 0).
- The API layer (client.ts with idempotencyKey SHA-256, ws.ts useJobEvents, jobs.ts hooks + invalidateJobs) is type-correct against codegen'd OpenAPI types (D-11, D-14, Phase 4 D-07/D-08, Open Questions #3 RESOLVED).
- The CSS Design System tokens + .detail-layout + .transcript-row + .active + .active-card classes are defined (UI-01, UI-03, UI-SPEC Design System + §4).
- FE type-checks clean.
</success_criteria>

<output>
Create `.planning/phases/05-local-file-ingest-history-ui-3-pane-layout/05-02a-SUMMARY.md` when done
</output>

## Artifacts this phase produces

Front-end symbols/files added by this plan (the plan-review-convergence source-grounding pass excludes these from drift verification):
- `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/vitest.config.ts`
- `web/src/test/setup.ts` (Vitest setup: mock IntersectionObserver, WebSocket, fetch, XHR)
- `web/src/styles.css` (CSS variables + `.detail-layout` + `.transcript-row` + `.active` + `.active-card`)
- `web/scripts/gen-types.sh` (openapi-typescript codegen script)
- `web/src/api/types.ts` (codegen'd TS types from /openapi.json)
- `web/src/api/client.ts` (`apiFetch`, `idempotencyKey(filename, size, lastModified)` SHA-256->32 hex)
- `web/src/api/ws.ts` (`useJobEvents(jobId: string | null)`)
- `web/src/api/jobs.ts` (`useJobs(status?)`, `useJob(id)`, `useTranscript(id)`, `jobsKeys`, `invalidateJobs`)