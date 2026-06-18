---
phase: 02-gpu-backend-detection-model-manager
fixed_at: 2026-06-19T00:00:00Z
review_path: .planning/phases/02-gpu-backend-detection-model-manager/02-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-06-19
**Source review:** .planning/phases/02-gpu-backend-detection-model-manager/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (2 Critical, 7 Warning)
- Fixed: 9
- Skipped: 0

## Fixed Issues

### CR-01: Boot lifespan builds engine + ModelManager with stale `data_dir` after `apply_pending()`

**Files modified:** `app/main.py`
**Commit:** eead867
**Applied fix:** Moved `apply_pending()` ahead of engine/session-factory/manager
construction in `lifespan`. When a pending restart-required `data_dir` change is
applied on boot, the local `settings` variable is now refreshed from
`settings_service.current()` BEFORE `make_engine`, `make_sessionmaker`,
`configure`, and `configure_manager(ModelManager(settings))` run, so the DB
engine and the model cache point at the NEW `data_dir` that
`settings_service.current()` reports. The `mkdir` of the data directory also
moved after `apply_pending()` so the applied path is the one created.

### CR-02: `PATCH /settings` leaks the base64-encoded `hf_token` in the response body

**Files modified:** `app/api/routes_settings.py`
**Commit:** 705a1fc
**Applied fix:** `patch_settings` now builds `body = result.model_dump()`,
nulls `body["hf_token"]`, and returns the dict — mirroring `get_settings`'s
D-05 nulling. `response_model=Settings` re-validates the dict and serializes
`None` as `null`, so the wire body carries `"hf_token": null` instead of the
base64-encoded cleartext token.

### WR-01: `POST /models/{id}/download` does not dedupe in-flight downloads

**Files modified:** `app/api/routes_models.py`
**Commit:** 8a5d00f
**Applied fix:** `download_model` checks `_in_flight[id]` for an existing entry
in the `queued` or `running` state and raises HTTP 409
(`download_in_flight`) with the existing state + status_url instead of
overwriting the progress entry and spawning a racing second background task.

### WR-02: SSE `download-progress` emits only on state change; byte-level progress never reported

**Files modified:** `app/api/routes_models.py`
**Commit:** 1f47de1
**Applied fix:** `_run_download` now runs a concurrent polling task that sums
the target file size plus any matching `*.incomplete` files (including HF
Hub's `.cache/huggingface/download` staging dir) every 0.5s, writing the
total to `progress.bytes_done`. The SSE `event_generator` now emits a
`progress` frame on `bytes_done` change (throttled to >= 0.5s between
frames) in addition to state changes. `_run_download` accepts `settings` and
uses `spec_file_path` to locate the target. **Status: fixed — requires human
verification** (logic/behavioral change; the partial-file polling paths
depend on HF Hub's staging layout which varies by library version).

### WR-03: `probe_vram` CPU path always returns `loaded=[]`

**Files modified:** `app/models/vram.py`
**Commit:** 1e4f8f0
**Applied fix:** The CPU success branch of `probe_vram` now builds
`loaded=_loaded_list(manager_state)` so `GET /diagnostics/vram` reflects
resident models on CPU backends, matching the CUDA/ROCm branch. The CPU
error path stays `loaded=[]` to match the CUDA error path.

### WR-04: `ModelManager.load` reserves 0 VRAM for STT/diarize, bypassing the SC-4 budget gate

**Files modified:** `app/models/registry.py`
**Commit:** 36d18cc
**Applied fix:** Populated `expected_size_bytes` with rough approximations for
the previously-`None` STT/diarize specs: `_BALANCED_STT` ~3.0 GB,
`_BALANCED_DIARIZE` ~90 MB, `_SMALL_STT` ~1.0 GB. These feed the SC-4 VRAM
budget gate (the comment in `registry.py` notes the value is an approximation
for budget math only, NOT an integrity check). The shared `_BALANCED_STT` /
`_BALANCED_DIARIZE` specs cover the `large.stt` / `small.diarize` /
`large.diarize` aliases. **Status: fixed — requires human verification** (the
approximate sizes are estimates and should be refined against the real
downloaded file sizes).

### WR-05: A non-restart `PATCH /settings` silently drops a pending restart-required `data_dir` change

**Files modified:** `app/settings/service.py`
**Commit:** aa7dea5
**Applied fix:** The non-restart branch of `apply_update` now preserves an
existing pending slot: when `_State.pending is not None`, the disk dict is
augmented with `disk[_PENDING_KEY] = _State.pending.model_dump()` and
`_State.pending` is left intact (no longer cleared). The user's queued
`data_dir` move survives an unrelated hot-swap PATCH and is still installed
by the next boot's `apply_pending`. Docstring updated to reflect the new
behavior. **Status: fixed — requires human verification** (logic/state
change in the settings persistence path).

### WR-06: `ensure_downloaded` with a SHA set does not return early on a valid cached file

**Files modified:** `app/models/manager.py`
**Commit:** dac7cd4
**Applied fix:** The corrupt-SHA fast-path in `ensure_downloaded` now returns
`target` early when `_sha256_of_file(target) == spec.expected_sha256`, so a
valid cached file is not re-fetched and the call succeeds offline. Only on
SHA mismatch does it delete + re-download once (the existing bounded retry).

### WR-07: `_resolve` 404 `available` field wraps the error message instead of listing valid ids

**Files modified:** `app/api/routes_models.py`
**Commit:** 5b86430
**Applied fix:** Imported `REGISTRY` from `app.models.registry` and built the
404 `available` field directly as `sorted(REGISTRY.keys())`, producing a
clean list of valid registry ids instead of a one-element list containing the
full `KeyError` message string.

## Skipped Issues

None — all in-scope findings were fixed.

---

_Fixed: 2026-06-19_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_