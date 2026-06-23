---
phase: 5
slug: local-file-ingest-history-ui-3-pane-layout
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-23
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `## Validation Architecture` in `05-RESEARCH.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (back-end)** | pytest 8 + pytest-asyncio (existing, `asyncio_mode="auto"`) |
| **Config file (back-end)** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"]) |
| **Quick run command (back-end)** | `pytest tests/test_<module>.py -x` |
| **Full suite command (back-end)** | `pytest` |
| **Framework (front-end)** | Vitest 8 (ships with Vite) — NEW, to be configured in `web/` |
| **Config file (front-end)** | `web/vitest.config.ts` (Wave 0 — does not exist yet) |
| **Quick run command (front-end)** | `cd web && npx vitest run <file>` |
| **Full suite command (front-end)** | `cd web && npx vitest run` |
| **Estimated runtime** | ~30 seconds (back-end full suite) + ~10 seconds (FE suite) |

---

## Sampling Rate

- **After every task commit (back-end):** Run `pytest tests/test_upload_stream.py tests/test_transcript_endpoint.py -x`
- **After every task commit (front-end):** Run `cd web && npx vitest run`
- **After every plan wave (merge):** Run `pytest` (full back-end — must stay green; 42 existing test files) + `cd web && npx vitest run`
- **Before `/gsd-verify-work`:** Full back-end + front-end suites must be green; the memory-bound guarantee test (tracemalloc peak assertion) MUST pass.
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | INGEST-01 | T-05-01 | Streams request body to disk; never buffers whole file in memory | unit + integration | `pytest tests/test_upload_stream.py -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | INGEST-01 (memory) | T-05-01 | Heap does not grow proportionally to file size during upload | integration | `pytest tests/test_upload_memory.py -x` (assert `tracemalloc` peak < threshold during large fixture) | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | INGEST-01 (atomic) | T-05-02 | Crashed upload leaves no partial `source.<ext>`; only `.tmp_*` cleaned | unit | `pytest tests/test_upload_atomic.py -x` (abort mid-stream, assert no `source.<ext>`) | ❌ W0 | ⬜ pending |
| 05-01-04 | 01 | 1 | INGEST-01 (race) | T-05-03 | Worker does not pick up job mid-upload (`status='uploading'` invisible to `pull_next`) | unit + integration | `pytest tests/test_upload_race.py -x` (slow upload, assert worker idle; after enqueue worker claims) | ❌ W0 | ⬜ pending |
| 05-01-05 | 01 | 1 | D-14 | — | `GET /jobs/{id}/transcript` returns `Transcript`, 404 when none | unit + integration | `pytest tests/test_transcript_endpoint.py -x` | ❌ W0 | ⬜ pending |
| 05-01-06 | 01 | 1 | D-11 (idempotency) | — | Re-drop mid-upload collapses to existing job | integration | `pytest tests/test_upload_idempotency.py -x` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 2 | JOB-03 | — | Completed jobs appear in history list newest-first | integration | `pytest tests/test_history_list.py -x` (create+complete, `GET /jobs?status=done`) | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 1 | UI-01 | — | 3-pane refined to history page + 2-pane detail (transcript + summary) | FE unit | `cd web && npx vitest run src/pages/DetailPage.test.tsx` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 1 | UI-02 | — | No embedded video player anywhere | FE lint | `grep -r "<video" web/src/` returns no matches | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 2 | UI-03 | — | Active transcript line highlighted on scroll | FE unit (jsdom) | `cd web && npx vitest run src/hooks/useScrollSpy.test.ts` (mock IntersectionObserver, assert `activeId` updates) | ❌ W0 | ⬜ pending |
| 05-03-03 | 03 | 2 | JOB-03 (re-open) | — | Clicking a completed job loads its transcript; re-export reuses Phase 4 export | integration (FE) + e2e | `cd web && npx vitest run src/api/jobs.test.ts` (`GET /jobs/{id}/transcript` returns Transcript; 404 when none) | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · W0 = Wave 0 stub needed*

---

## Wave 0 Requirements

- [ ] `tests/test_upload_stream.py` — stubs for INGEST-01 (streaming write, atomic rename, race prevention)
- [ ] `tests/test_upload_memory.py` — stubs for INGEST-01 memory-bound guarantee (`tracemalloc` peak < N MB during a >100MB fixture upload)
- [ ] `tests/test_upload_atomic.py` — stubs for INGEST-01 atomic cleanup
- [ ] `tests/test_upload_race.py` — stubs for INGEST-01 race prevention
- [ ] `tests/test_transcript_endpoint.py` — stubs for D-14 (`GET /jobs/{id}/transcript`, 404 when none)
- [ ] `tests/test_upload_idempotency.py` — stubs for D-11 idempotent re-drop
- [ ] `tests/test_history_list.py` — stubs for JOB-03 (history list)
- [ ] `web/vitest.config.ts` — Vitest config for the new FE codebase (jsdom environment for scroll-spy + component tests)
- [ ] `web/src/test/setup.ts` — Vitest setup (mock IntersectionObserver, mock WebSocket, fetch polyfill via msw or `vi.fn`)
- [ ] `web/src/hooks/useScrollSpy.test.ts` — stubs for UI-03
- [ ] `web/src/api/jobs.test.ts` — stubs for JOB-03 (history list fetch + transcript fetch)
- [ ] `web/src/pages/DetailPage.test.tsx` — stubs for UI-01 (2-pane detail grid)
- [ ] FE framework install: `cd web && npm install -D vitest @testing-library/react jsdom` — if not present after `npm create vite`

*Existing back-end test infrastructure (pytest, conftest.py, httpx `ASGITransport`) covers the integration test path — new routes are tested via the same `httpx.AsyncClient` + FastAPI app pattern used by the 42 existing test files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 3-pane/2-pane layout visually matches UI-SPEC §4 across breakpoints | UI-01 | Visual layout fidelity needs human eyes at multiple viewport widths | Drag a window across mobile/tablet/desktop widths; confirm history + transcript + summary panes match UI-SPEC §4 grid |
| Drag-and-drop feel (no page reload, drop-zone highlight) | INGEST-01 | Browser DnD gesture + visual affordance not asserted by jsdom | Drag a file over the drop zone; confirm highlight + that drop triggers upload without reload |
| Active-line highlight tracks scroll position smoothly | UI-03 | Real scroll + IntersectionObserver timing varies in jsdom | Scroll the transcript pane; confirm the visible line stays highlighted and updates without flicker |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending