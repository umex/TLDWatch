# Phase 2: GPU Backend Detection + Model Manager - Context

**Gathered:** 2026-06-18
**Status:** Ready for (re)planning
**Source:** /gsd-discuss-phase 2 (interactive, default mode)

<domain>
## Phase Boundary

First-run silent CUDA/ROCm/CPU detection with a real GPU-burn test, plus a model manager that owns every local model's lifecycle on disk (download + verify + resume) and in VRAM (lazy load + idle unload + single-model discipline). Phase 2 has **no UI** — the React front-end arrives in Phase 5. Everything here is back-end code, the `Settings` model extension, and diagnostics/model API endpoints.

In scope (ROADMAP success criteria SC-1..SC-5, requirements HW-02/03/04/07/09):
- Two-stage GPU detect (probe → burn test) writing `backend` + `backend_probe` to `settings.json` only after a real kernel run
- `ModelManager`: download (resumable), size + SHA256 verify, lazy load, explicit unload, VRAM probe, per-model VRAM log
- Default model set (BALANCED) fits 8 GB laptop one-at-a-time; per-model VRAM budget logged on load
- 85% VRAM budget gate; `concurrent_models: bool` opt-in (default False, hidden by default)
- Diagnostics + model API endpoints (`/diagnostics/gpu-burn`, `/diagnostics/vram`, `/diagnostics/test-hf-token`, `/models`, `/models/{id}/download|status|load|unload`)
- 02-03 ROCm-on-Windows spike deliverable (`02-03-SPIKE.md`)

Out of scope for Phase 2: any front-end/UI (Phase 5), the orchestrator/queue/WebSocket (Phase 4), real `pyannote.audio` import (Phase 7 — Phase 2 ships a HF-token-test SHIM), real STT/LLM adapters (Phase 3/8), settings panel UI / quality-preset picker / per-category override picker (Phase 10).

</domain>

<decisions>
## Implementation Decisions

### Model download timing
- **D-01:** Models download **on-demand per category**, not as a silent first-run bulk pull. A model is fetched the first time a job needs that category (STT first, then diarize/LLM as requested). First boot is fast and silent; disk fills only as features are used. Aligns HW-09 ("load on demand"); resolves the PROJECT.md/HW-04 "downloads on first run" vs HW-09 "load on demand" tension in favor of on-demand. The first job of each category pays a one-time download wait.
- **D-02:** Download is triggered **just-in-time at stage start** — each job stage triggers its own model's download+load right before it runs. No background prefetch at job-submit in Phase 2 (that orchestration belongs to Phase 4). Simplest fit for lazy-load; the first job of a category waits at that stage. *Prefetch-at-submit is noted as a Phase 4 follow-up.*

### Idle unload policy
- **D-03:** Unload is **explicit-only** — no time-based timer. A loaded model stays resident in VRAM until one of: (a) another model needs the VRAM and `concurrent_models=False`, (b) the API/Settings explicitly unloads it (`POST /models/{id}/unload` or `unload_all`), or (c) app shutdown. "Idle" means "not being used by a running job," not "N minutes since last use." Back-to-back same-category jobs are instant; a backgrounded app holds VRAM until something asks for it or the process exits.
- **D-04:** When `concurrent_models=False` (default) and a second model load is requested while one is resident, the manager **refuses with 409 `ConcurrentModelRefused`** (body names the resident model). The caller (Phase 4 orchestrator) must explicitly unload the resident model, then load the next. This matches D-03 explicit-only + SC-5. *Auto-swap (unload-and-load in one call) is deliberately NOT the Phase 2 behavior; noted as a Phase 4 orchestrator consideration.* *(Claude's Discretion — user deferred the granular choice; aligns with explicit-only + SC-5.)*

### HF token storage
- **D-05:** The HuggingFace token is stored **base64-encoded inside `settings.json`** (v1). A Pydantic `field_validator` decodes on read and the serializer encodes on write, so the on-disk file never holds cleartext (avoids accidental leak on `cat settings.json`). The token is **never returned by `GET /settings`** (always `null` in the response, regardless of `?reveal=`); it exists in the on-disk file and in `UpdateSettingsRequest`, never in a response. `UpdateSettingsRequest` accepts `hf_token` as a hot-swap field (no restart). base64 is "no accidental cleartext," not real security. *v2 may move the token to a separate `secrets.json` (chmod 0600) if export-to-share ever lands; deferred.*

### GPU fallback visibility
- **D-06:** GPU-detection fallback to CPU is **silent log-only** in Phase 2. When no GPU path works (esp. desktop if the ROCm path fails), the backend writes `backend: cpu` + a structured WARN log line and starts anyway — it **never refuses to start**. No user-facing surface in Phase 2 (no first-run card, no notice flag); the Phase 10 diagnostics page can render the `backend_probe` later. The laptop stays silent (locked by PROJECT.md constraint); the desktop is also silent for consistency. *A one-time non-blocking first-run notice flag in settings (for Phase 5/10 UI to render once) is noted as a Phase 10 follow-up, not Phase 2.*

### ROCm 02-03 spike ownership / timing
- **D-07:** Ship the detect code now targeting the **documented paths** (TheRock nightly `gfx103X-dgpu` index for torch ROCm; `lemonade-sdk/llamacpp-rocm` `lemon-clip` binary + `lemonade-sdk/whisper.cpp-rocm` for the desktop STT/LLM). The 02-03 spike (`02-03-SPIKE.md`) is a **living doc the user runs on the desktop later as a separate manual task**; Phase 2 code is "done" without the spike verdict. The fallback chain (CPU STT/LLM, `n_gpu_layers=0`, loud log) already handles failure safely, so shipping unverified is acceptable. STATE.md flags the TheRock nightly URL as the single load-bearing desktop unknown — exactly what the spike verifies when the user is at the box. *(Claude's Discretion — user deferred; keeps Phase 2 unblocked from hardware availability.)*

### Settings field declaration strategy
- **D-08:** **Declare-now.** Phase 2 extends `Settings` with the fields it uses (`backend`, `backend_probe`, `hf_token`) AND the fields Phase 10 will surface (`quality_preset`, `per_category_overrides`, `concurrent_models`, `vram_budget_fraction`), all with defaults populated, so a fresh boot writes a single stable on-disk format and the back-end can read every field today. This deliberately tensions Phase-1 **D-17** (YAGNI — "every other field added by the phase that needs it"); the override rationale: a future Phase-10 on-disk format re-version is more disruptive than carrying four defaulted fields now, and `concurrent_models`/`vram_budget_fraction` are *enforced* by the Phase 2 model manager (SC-4/SC-5) even before Phase 10 surfaces them. `backend` and `backend_probe` are NOT user-editable (excluded from `UpdateSettingsRequest`); only the detect/burn path and `POST /diagnostics/gpu-burn` set them. *(Claude's Discretion — user deferred; RESEARCH recommendation.)*

### Default model set
- **D-09:** Confirm **BALANCED** as the default preset: STT = `Systran/faster-whisper-large-v3`, diarize = `pyannote/speaker-diarization-3.1` (gated), LLM = `Qwen/Qwen2.5-7B-Instruct-GGUF` `qwen2.5-7b-instruct-q4_k_m.gguf` (~4.5 GB). Fits 8 GB laptop one-at-a-time: largest single model ~5 GB < 6.8 GB (85% of 8 GB). `SMALL` (Qwen2.5-3B ~2 GB) and `LARGE` (Qwen2.5-14B ~10 GB, desktop opt-in per HW-08) presets are declared alongside. LLM is NOT downgraded to 3B — the 7B fits the laptop budget with headroom per RESEARCH math. *(Claude's Discretion — user deferred; matches HW-07 + RESEARCH.)*

### Carried forward from Phase 1 (locked — not re-asked)
- **D-04 (Phase 1):** atomic writes (`<name>.tmp` → fsync → `os.replace`) for every settings change — `backend`/`backend_probe`/`hf_token` writes and `POST /diagnostics/gpu-burn` updates inherit this.
- **D-14 (Phase 1):** `settings.json` is the serialization of the Pydantic `Settings` model; the model is source of truth.
- **D-15 (Phase 1):** strict input / lax output at the API boundary; `UpdateSettingsRequest` is `ConfigDict(strict=True, extra="forbid")`.
- **D-17 (Phase 1):** YAGNI — noted tension with D-08 above; the override is deliberate and recorded.
- **H1 (01-04):** `data_dir` change is restart-only via `pending` slot + `apply_pending()` in the lifespan; `X-Restart-Required: true` fires ONLY for `data_dir`. All new Phase 2 fields are hot-swap (no restart).

### Claude's Discretion
- D-04 (second-load refuse-vs-autoswap), D-07 (spike timing), D-08 (declare-now), D-09 (BALANCED confirm) were deferred by the user and assigned to Claude with a recorded rationale each.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher/planner/executor) MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — hardware constraints (8 GB laptop VRAM budget, dual-machine target: RTX 2000 Ada CUDA + RX 6800 XT ROCm), silent-first-run promise (laptop non-intrusive), no-telemetry, single-user no-auth, back-end is the only thing that touches models + filesystem
- `.planning/REQUIREMENTS.md` — Phase 2 owns `HW-02` (models run on GPU), `HW-03` (auto-detect CUDA/ROCm/CPU), `HW-04` (app downloads its own models), `HW-07` (default set fits 8 GB), `HW-09` (per-job VRAM discipline)
- `.planning/STATE.md` — "Blockers/Concerns": ROCm-on-Windows for gfx1030 in mid-2026 is the highest-risk Phase 2 unknown; first-run GPU-burn test is the ground truth
- `.planning/ROADMAP.md` — Phase 2 goal, mode (mvp), success criteria SC-1..SC-5, plans 02-01/02-02/02-03

### Prior phase context
- `.planning/phases/01-back-end-skeleton-storage-data-layout/01-CONTEXT.md` — D-04 atomic writes, D-14 settings-as-serialization, D-15 strict-in/lax-out, D-17 YAGNI, D-17 settings field scope, H1 restart-only data_dir. Phase 2 inherits all of these.

### Research (already on disk — the existing 3 plans were built from this)
- `.planning/phases/02-gpu-backend-detection-model-manager/02-RESEARCH.md` — two-stage detect protocol, `ModelManager` Protocol, `Settings` Pydantic extension (exact field list + restart-vs-hotswap table), VRAM probe (torch + llama.cpp two-pool problem), default model set + presets, HF token gating + test-token endpoint, 02-03 spike deliverable shape, validation architecture (per-SC testable observables), API endpoints, pitfall traceability, open questions for planner
- `.planning/research/PITFALLS.md` — Pitfall 1 (GPU-backend-detection phase ownership; silent CPU fallback), Pitfall 2 (VRAM two-pool), Pitfall 3 (HF token optional, no app-block), Pitfall 4 (paths/spaces in HF downloads, resume, SHA verify), Pitfall 10 (FE/BE schema drift), Pitfall 12 ("settings says ROCM but jobs run on CPU"), Pitfall 13 (model swap as data not code)
- `.planning/research/SUMMARY.md` — Recommended Stack (Python 3.11 + FastAPI + Uvicorn), Architecture Approach (two-process, back-end as system of record), 8 GB laptop budget math

### Patterns (already on disk)
- `.planning/phases/02-gpu-backend-detection-model-manager/02-PATTERNS.md` — analog files + code excerpts for the new `app/models/*` modules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable assets (from Phase 1)
- `app/models/settings.py` — `Settings(BaseModel)` with `model_config = ConfigDict(extra="forbid")` and `data_dir: str`; `UpdateSettingsRequest` with `ConfigDict(strict=True, extra="forbid")` + a `model_validator` for `data_dir`. Phase 2 extends both per D-08.
- `app/settings/service.py` — `apply_pending()` (restart-only `data_dir` path) + the in-memory `_State.settings` swap. Phase 2 reuses the same `pending`-slot path for `data_dir` and adds hot-swap for every new field.
- `app/storage/atomic.py` — the atomic-write helper (`<name>.tmp` → fsync → `os.replace`). Every Phase 2 settings write + spike/runtime artifact inherits it (D-04 Phase 1).
- `app/main.py` `lifespan` — single boot-time path; calls `apply_pending()` + reconcile. Phase 2 adds: GPU detect + burn test → write `backend`/`backend_probe` → build the `ModelManager` singleton (`get_manager()` / `configure_manager()`), all after `apply_pending`.
- `app/api/routes_settings.py` — `GET /settings` (lax output) + `PATCH /settings` (strict input, `X-Restart-Required` on `data_dir`). Phase 2 extends both with the new fields; never returns `hf_token` (D-05).
- `tests/conftest.py` — `tmp_data_dir` + `app_under_test` + `httpx.AsyncClient` fixture pattern. Every Phase 2 test reuses it; all seams are mocked (no real GPU / no real HF download).

### Established patterns
- **Pydantic as schema source of truth** (D-14/D-15) — new `Settings` fields + strict `UpdateSettingsRequest`; `openapi-typescript` codegen sees the same model.
- **Atomic writes** (D-04) — every on-disk mutation goes through the helper.
- **Restart-only via `pending` slot** (H1) — only `data_dir`; everything else hot-swaps in-memory.

### Integration points
- New modules Phase 2 CREATES: `app/models/backend.py` (GpuBackend enum + detect + burn_test), `app/models/vram.py` (probe_vram), `app/models/presets.py` (PRESETS + active_model_set), `app/models/registry.py` (REGISTRY), `app/models/manager.py` (ModelManager + LoadedModel/DownloadProgress Protocols + `get_manager`/`configure_manager`), `app/models/hf_token.py` (test-token SHIM, no `pyannote.audio` import). `huggingface_hub` is imported ONLY in `app/models/manager.py` and `app/models/hf_token.py` (boundary check: `grep -rE 'from huggingface_hub' app/` matches only those).
- New routers: `app/api/routes_diagnostics.py` (`/diagnostics/gpu-burn`, `/diagnostics/vram`, `/diagnostics/test-hf-token`), `app/api/routes_models.py` (`/models`, `/models/{id}/download|status|download-progress|load|unload`).
- Downstream: Phase 3 (STT) calls `get_manager().load(ModelCategory.STT)`; Phase 4 orchestrator owns the load/unload sequence per D-03/D-04; Phase 7 imports real `pyannote.audio` (Phase 2 ships only the SHIM); Phase 10 surfaces `quality_preset`/`per_category_overrides`/`concurrent_models` in the settings panel.

</code_context>

<specifics>
## Specific Ideas

- **Laptop silence is non-negotiable** (PROJECT.md): first-run detect on the RTX 2000 Ada must be silent — no wizards, no error dialogs, no CUDA-version complaints. The burn test is the only "is this real GPU" proof and it runs silently.
- **Two-pool VRAM discipline**: torch (`torch.cuda.memory_allocated`) and llama.cpp (`manager._live_vram_bytes` sum) hold separate VRAM pools; `probe_vram` must sum both before declaring "free" (RESEARCH Pitfall 2). This is the load-bearing detail for SC-4.
- **`backend`/`backend_probe` are not user-editable** — excluded from `UpdateSettingsRequest` entirely (not just `extra="forbid"`); only detect/burn + `POST /diagnostics/gpu-burn` set them. Prevents a client faking `backend: "cuda"`.
- **Download-progress**: SSE stream (`/models/{id}/download-progress`, Phase 5 consumes) + synchronous poll (`/models/{id}/status`, v1 CI test-friendly) share the same in-memory `DownloadProgress` state.
- **Bounded integrity retry**: SHA mismatch → delete + re-download once, no infinite loop (RESEARCH Pitfall 4).
- **pyannote SHIM**: Phase 2's `test-hf-token` does a metadata HEAD call via `huggingface_hub` directly; no `pyannote.audio` import until Phase 7. Keeps `requirements.txt` to `huggingface_hub` (+ `psutil`, + torch for detect) in Phase 2.

</specifics>

<deferred>
## Deferred Ideas

- **Auto-swap model loading** (unload resident + load new in one call) — Phase 4 orchestrator consideration; Phase 2 ships refuse-then-caller-unloads (D-04).
- **`secrets.json` (chmod 0600) for the HF token** — v2, only if export-to-share lands; Phase 2 uses base64-in-settings (D-05).
- **Prefetch models at job-submit** (overlap download with ingest) — Phase 4 follow-up; Phase 2 is just-in-time at stage start (D-02).
- **One-time first-run "Running on CPU" notice flag** (for Phase 5/10 UI to render once) — Phase 10; Phase 2 is silent log-only (D-06).
- **Quality-preset picker + per-category override picker UI** — Phase 10 (declared in the model now per D-08; not surfaced until Phase 10).
- **`data/runtime/rocm_probe.json` runtime artifact from the spike** — YAGNI; `settings.backend_probe` already records the probe result; the markdown `02-03-SPIKE.md` is enough (RESEARCH open question 2).
- **`expected_size_bytes` / `expected_sha256` for the Qwen2.5-7B GGUF** — leave `None` in `presets.py`, re-verify actual file size from HF at registry-build time in plan 02-02 (RESEARCH open question 4).
- **Exact `n_gpu_layers` for the desktop llama.cpp HIP path** — re-verify at 02-03 spike time on the user's box (RESEARCH open question 3).

</deferred>

---

*Phase: 2-GPU Backend Detection + Model Manager*
*Context gathered: 2026-06-18 via /gsd-discuss-phase (interactive, default mode)*