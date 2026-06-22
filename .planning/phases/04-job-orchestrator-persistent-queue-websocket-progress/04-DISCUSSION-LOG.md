# Phase 4: Job Orchestrator + Persistent Queue + WebSocket Progress - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-22
**Phase:** 4-Job Orchestrator + Persistent Queue + WebSocket Progress
**Areas discussed:** Ingest stage without upload UI, Idempotent submit key, Restart resume behavior, Cancel granularity (running)

---

## Ingest stage without upload UI

| Option | Description | Selected |
|--------|-------------|----------|
| Local file path → stage as source.<ext> (copy) | POST /jobs with source_path; orchestrator copies file into job dir as source.<ext> + sha256/duration. Self-contained but doubles disk. | |
| Local file path → reference in place | POST /jobs with source_path; manifest records it; transcriber reads directly. No copy. | ✓ |
| Stub ingest | Skip real ingest; queue machinery only with a mock stage. | |

**User's choice:** Reference in place (free-text): "only reference I don't need to do duplicates, space management is important. Even for youtube videos I don't want to keep them after transcription, they should be deleted. Later we will add this as an option."
**Notes:** The two ingest paths (local file vs YouTube) must be kept strictly separate, never mixed. Phase 4 implements `source_type=local` only; `source_type=youtube` is a Phase 6 seam. YouTube audio deletion after transcription captured for Phase 6 (D-05). `source_sha256` optional for local-reference ingest. The `ingested` completion check is refined (Phase 1 D-11) to "manifest.source_path resolves OR source.<ext> exists in job dir" so Phase 5 upload + Phase 6 download still work.

---

## Restart resume behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-resume all queued/in-flight on boot | Orchestrator silently resumes work on restart. | |
| Mark interrupted failed; user re-submits | Active-stage jobs → failed (error=interrupted), source name preserved; no restart button. | ✓ |
| Leave in-flight as queued (auto-runs next boot) | Surface as re-joinable, runs again automatically. | |

**User's choice:** Mark interrupted failed + preserve source name (free-text): "just keep track that something got interrupted and have log with error saved same with file or video name so I can find it later and restart transcription. We don't even need to have a restart button for MVP."
**Notes:** No mid-transcription (mid-chunk) resume — the chunker does not checkpoint; a crashed transcribe leaves no transcript.json (atomic write at end) so the existing `infer_resume_point` walker naturally re-transcribes from scratch. No separate "clear everything" path. The interrupted-sweep boot step runs after `reconcile_all`.

---

## Cancel granularity (running)

| Option | Description | Selected |
|--------|-------------|----------|
| Cooperative — stop after current chunk | Set cancel flag; chunker checks between chunks; stop; discard partial; mark cancelled. | ✓ |
| Hard — abort immediately | Cancel the asyncio task mid-C-call; may leave partial output. | |

**User's choice:** Cooperative (inferred from "as simple as possible" + no mid-transcription resume — there is no need to preserve partial output, so discard-on-cancel is safe and simplest).
**Notes:** Queued jobs cancel instantly via Phase 1 `cancel_job` (DB-first + retried rmtree). Because D-02 means we never resume mid-transcription, discarding the partial transcript on running-cancel is safe. Cancellation is idempotent (no-op on terminal jobs).

---

## Idempotent submit key

| Option | Description | Selected |
|--------|-------------|----------|
| Client Idempotency-Key header + table | Standard HTTP pattern; key→job_id in a new table with TTL; same key returns existing job. | ✓ (Claude's Discretion) |
| source sha256 content hash | Same file → reuse job. Requires hashing multi-GB files. | (deferred — future option) |
| source_path dedupe | Same path → reuse job. Fragile if file changes. | |

**User's choice:** Deferred to Claude's Discretion + cross-AI review (user did not pick; "as simple as possible" → header-based key, no content hashing).
**Notes:** Content-hash dedupe ("same source file reuses existing job") explicitly a future option, not MVP. D-07 in CONTEXT.md.

---

## Claude's Discretion

- **Idempotency-key mechanism (D-07):** client `Idempotency-Key` header + `idempotency_keys` table with bounded TTL. Researcher/planner picks the TTL.
- **WebSocket endpoint shape (D-08):** per-job `GET /ws/jobs/{id}/events`, state snapshot on connect, in-process asyncio event bus (no broker). Global `/ws/events` is a future option.
- **Progress / ETA granularity (D-09):** per-stage binary for ingest, per-chunk percent for transcription, ETA with min-sample threshold. Exact event schema + cadence = researcher/planner.
- **Worker=1 serial dispatch (D-10):** locked by HW-09 + Phase 2 D-04 (409 on second model). May overlap ingest of N+1 with transcribe of N only if low-complexity; default fully serial.
- **Stale-sweep cadence (D-11):** periodic watchdog reusing Phase 1 `is_stale`/`mark_stale` with the D-13 10-min threshold.
- **Cross-AI review (D-12):** standing preference (carried from Phase 3 D-09) — codex + gemini review the Phase 4 plans + implementation.

## Deferred Ideas

- Browser drag-and-drop / streaming upload UI + endpoint → Phase 5.
- YouTube ingest / yt-dlp / playlists / timestamp link-out → Phase 6 (includes D-05 delete-after-transcribe + playlist resume behavior: resume playlist from the interrupted child, restart that child from the beginning).
- "Restart from beginning" UI button → future (MVP = manual re-submit).
- Mid-chunk transcription checkpointing → explicitly rejected for MVP.
- Content-hash idempotency (same-file reuse) → future option.
- Global WebSocket stream → future.
- Prefetch STT model at job-submit → deferred again (Phase 2 D-02 carry).
- "Keep YouTube audio after transcription" toggle → future settings option (Phase 10).
- `source_sha256` for local-reference ingest → optional / best-effort for MVP.
- Overlap ingest of N+1 with transcribe of N → only if low-complexity (D-10 latitude).