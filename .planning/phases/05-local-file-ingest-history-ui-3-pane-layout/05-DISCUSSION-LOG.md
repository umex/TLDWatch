# Phase 5: Local File Ingest + History UI + 3-Pane Layout - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 5-Local File Ingest + History UI + 3-Pane Layout
**Areas discussed:** Upload & new-job flow, 3-pane layout & rendering, History list & live status, Re-export scope (SC-5 vs Phase 9)

---

## Upload & new-job flow

| Option | Description | Selected |
|--------|-------------|----------|
| (free-text) | Full-window drag overlay + a smaller dedicated drop area; per-file upload progress; several files allowed, they queue | ✓ |

**User's choice:** "it can be a full window, but it can also be a smaller dedicated area. Show progress for every file uploaded and there can be several in the queue."
**Notes:** Both entry points ship. The dedicated drop area was later placed at the top of the history page (see Drop area question). Multi-file drops queue because the back-end is worker=1 serial FIFO (Phase 4 D-10).

---

## History list & live status

| Option | Description | Selected |
|--------|-------------|----------|
| (free-text) | History on a separate page; rows show filename, date, duration | ✓ |

**User's choice:** "History should be on separate page, and should show filename, date, duration."
**Notes:** This created a tension with UI-01 ("3-pane: history (left) | transcript | summary"). Resolved in the follow-up layout question → user chose option #1 (history page + 2-pane detail view), refining UI-01 (D-04). "Completed only" + active-jobs-near-drop-zone resolved in the Active jobs question.

---

## Layout reconciliation (history page vs UI-01 3-pane)

| Option | Description | Selected |
|--------|-------------|----------|
| #1 History page + 2-pane detail view | Dedicated history page lists jobs; clicking opens a transcript\|summary working view (no left history pane). Matches "history on a separate page" most literally; diverges from UI-01's literal 3-pane. | ✓ |
| #2 History page + 3-pane detail view | History page plus a 3-pane detail (history\|transcript\|summary) so the user can jump between jobs. Redundant but fully honors UI-01. | |
| #3 3-pane only, history is the left pane | No separate page; history is the left pane (literal UI-01). Drops the "separate page" idea. | |

**User's choice:** #1 — "lets go with 1. I dont care about the details of the job, but later i might want to open up previous transcripts if they are still at that location. But we can ignore that for now as that should be easy to implement later on if needed."
**Notes:** UI-01 refined to history-page + 2-pane detail (D-04). The minimal click→load-transcript still ships (SC-3/SC-5, D-06); no rich job-detail panel (deferred).

---

## Transcript rendering

| Option | Description | Selected |
|--------|-------------|----------|
| One row per segment + timestamp | One row per segment, timestamp on the left (e.g. `[00:12] text`). Discrete lines for the UI-03 scroll-highlight. | ✓ |
| Merged paragraphs, timestamps on hover | Paragraphs by speaker/time gaps; timestamps on hover. Cleaner but fuzzy scroll-highlight. | |
| You decide | Claude picks the simpler option satisfying UI-03. | |

**User's choice:** One row per segment + timestamp.

---

## Active jobs (history page contents)

| Option | Description | Selected |
|--------|-------------|----------|
| Show active jobs with live progress | Queued + in-progress jobs in the history list with live WS progress. | |
| History = completed only | History is a completed-jobs archive; active progress shows near the drop area instead. | ✓ |
| You decide | Claude picks per "as simple as possible." | |

**User's choice:** History = completed only. Active jobs show progress near the drop area (D-03).

---

## Summary pane (before Phase 8)

| Option | Description | Selected |
|--------|-------------|----------|
| Placeholder empty state, pane visible | Right pane shows "Summaries will appear here…"; Phase 8 fills it. Keeps 2-pane shape stable. | ✓ |
| Hide right pane until summaries exist | Single-pane transcript for now; layout grows a pane later. | |
| You decide | Claude picks. | |

**User's choice:** Placeholder empty state, pane visible (D-08).

---

## Drop area placement

| Option | Description | Selected |
|--------|-------------|----------|
| Top of the history page | Drop area at the top of the landing page; dropped files become jobs in the list below. | ✓ |
| Persistent top bar | A bar across the app with a drop target, always available. | |
| You decide | Claude picks. | |

**User's choice:** Top of the history page (D-01). Full-window drag overlay works anywhere on top of this.

---

## Re-export scope (SC-5 vs Phase 9)

| Option | Description | Selected |
|--------|-------------|----------|
| (free-text) | Export can wait till Phase 9 | ✓ |

**User's choice:** "Export can wait till phase 9."
**Notes:** No export UI in Phase 5 (D-10). SC-5 splits — "re-open + see existing transcript" ships in Phase 5; "re-export" ships in Phase 9 with EXPORT-01/02/03.

---

## Claude's Discretion

- **D-11** Streaming upload endpoint mechanism (chunked body vs. streamed multipart) — must stream to `data/jobs/<id>/source.<ext>` without holding the file in memory (SC-1); atomic landing; reuses Idempotency-Key.
- **D-12** Front-end stack versions/pins (Vite + React + TS + openapi-typescript codegen + TanStack Query + React Router + native WebSocket).
- **D-13** Visual theme details (clean minimal light theme; no dark-mode requirement in v1).
- **D-14** Transcript read endpoint route/shape (`GET /jobs/{id}/transcript`, 404 when none).
- **D-09** Exact scroll-spy mechanism for active-line highlight (e.g. IntersectionObserver).
- Whether to show a disabled Export placeholder (default: none).

All recorded with rationale + recommended defaults in CONTEXT.md; cross-AI review (codex + gemini) pressure-tests them per the standing preference.

## Deferred Ideas

- Re-export / Markdown export — Phase 9 (EXPORT-01/02/03).
- YouTube URL submit / yt-dlp / playlist / timestamp link-out — Phase 6.
- Speaker labels / chip bar / per-line reassign / find-replace speaker — Phase 7.
- Summary content in the right pane — Phase 8.
- Inline transcript editing / find-replace text — Phase 9.
- Settings panel / quality preset / model overrides / first-run card — Phase 10.
- Dark mode / responsive / mobile — Out of Scope (desktop browser only).
- Rich job-detail metadata view — deferred (user: "easy to implement later if needed").
- History search/filter/pagination beyond `?limit`/`?offset` — not requested; future.
- Content-hash idempotency — future option (MVP uses Idempotency-Key header).
- "Keep YouTube audio after transcription" toggle — Phase 10 settings option.
- Global WebSocket stream (`/ws/events`) — future; MVP is per-job.

---

*Phase: 5-Local File Ingest + History UI + 3-Pane Layout*
*Discussion logged: 2026-06-23 via /gsd-discuss-phase (interactive, default mode)*