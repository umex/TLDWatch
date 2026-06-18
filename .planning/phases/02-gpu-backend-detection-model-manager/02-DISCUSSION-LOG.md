# Phase 2: GPU Backend Detection + Model Manager - Discussion Log

**Gathered:** 2026-06-18
**Mode:** /gsd-discuss-phase 2 (interactive, default mode)
**For:** human reference (audits, retrospectives). NOT consumed by downstream agents.

## Areas discussed

Four gray areas selected by the user (multiSelect). Two standby areas resolved as Claude's Discretion after the user deferred.

### 1. Model download timing
- Q1 — When should the default models be downloaded?
  - Options: On-demand per category (Recommended) / Silent bulk on first run / Hybrid (STT on first run, rest on-demand)
  - Selected: **On-demand per category** — first boot fast/silent; a model downloads the first time a job needs that category. Resolves PROJECT.md/HW-04 vs HW-09 tension in favor of on-demand.
- Q2 — When is the download triggered?
  - Options: Just-in-time at stage start (Recommended) / Pre-fetch at job submit / You decide
  - Selected: **Just-in-time at stage start** — each stage triggers its own model's download+load right before it runs. No background prefetch in Phase 2 (Phase 4 owns orchestrator). Prefetch-at-submit noted as Phase 4 follow-up.
- Check: Next area.

### 2. Idle unload policy
- Q1 — When should a loaded model be unloaded from VRAM?
  - Options: Explicit-only (Recommended) / Time-based auto-unload / On-stage-complete
  - Selected: **Explicit-only** — resident until another model needs VRAM, API/Settings unloads, or shutdown. No timer. "Idle" = not used by a running job.
- Q2 — Second model load while one is resident, concurrent_models=False?
  - Options: Refuse 409 caller unloads first (Recommended) / Auto-swap / You decide
  - Tool repeatedly rejected the structured payload (harness validation glitch, not user input); user signaled the follow-up was too granular ("i dont know what any of these are").
  - Resolved as **Claude's Discretion: refuse 409, caller unloads first** — aligns with explicit-only + SC-5; auto-swap noted as Phase 4 orchestrator consideration.
- Check: Next area.

### 3. HF token storage
- Presented as plain-text numbered list (tool fallback).
  - Options: (1) base64 in settings.json / (2) separate secrets.json 0600 / (3) plaintext in settings.json
  - Selected: **(1) base64-encoded inside settings.json** — v1 simple; Pydantic field_validator decodes on read; never returned in GET /settings. secrets.json deferred to v2.

### 4. GPU fallback visibility
- 4a — When detection falls back to CPU, how visible is it?
  - Options: (1) Silent log-only / (2) One-time non-blocking notice / (3) Loud / refuse to start
  - Selected: **(1) Silent log-only** — backend:cpu + structured WARN; no Phase-2 UI surface; laptop silent (locked); never refuses to start. First-run notice flag deferred to Phase 10.
- 4b — 02-03 ROCm spike: who runs it, does Phase 2 block on it?
  - Options: (1) User runs it as part of Phase 2 / (2) Ship detect now, user runs spike later / (3) Skip spike in v1
  - User: "have no idea you decide" → **Claude's Discretion: (2) ship detect now, user runs spike later** — keeps Phase 2 unblocked from hardware availability; fallback chain handles failure safely; TheRock URL is the single load-bearing desktop unknown the spike verifies.

## Standby areas (resolved as Claude's Discretion after user deferred)
- **Settings field declaration strategy** — strict YAGNI (Phase 2 fields only) vs declare-now (also write Phase-10 fields with defaults). Resolved: **declare-now** (D-08), with recorded tension vs Phase-1 D-17; rationale = avoids a Phase-10 on-disk format re-version and the manager enforces `concurrent_models`/`vram_budget_fraction` today.
- **Default model set confirmation** — BALANCED = faster-whisper-large-v3 + pyannote-3.1 + Qwen2.5-7B Q4_K_M. Resolved: **confirm BALANCED** (D-09); fits 8 GB one-at-a-time (~5 GB < 6.8 GB budget @ 85%); LLM not downgraded to 3B.

## Notes
- AskUserQuestion intermittently rejected structured payloads with a "type expected as array but provided as string" validation error mid-session; the workflow's plain-text numbered-list fallback (per answer_validation) was used for Areas 3 and 4. A minimal probe question confirmed the tool itself still functioned.
- User consistently deferred granular/technical follow-ups ("you decide", "have no idea you decide"); four decisions recorded as Claude's Discretion with rationale (D-04 second-load, D-07 spike timing, D-08 declare-now, D-09 BALANCED).
- No checkpoint file was written mid-discussion (single uninterrupted interactive session); CONTEXT.md is the canonical record.

## Deferred ideas captured
Auto-swap loading (Phase 4) · secrets.json token storage (v2) · prefetch at job-submit (Phase 4) · first-run CPU notice flag (Phase 10) · quality-preset/override picker UI (Phase 10) · `rocm_probe.json` runtime artifact (YAGNI) · Qwen2.5-7B exact size/SHA (re-verify in 02-02) · exact desktop `n_gpu_layers` (re-verify at 02-03 spike).

---
*Phase: 2-GPU Backend Detection + Model Manager*
*Discussion log: 2026-06-18*