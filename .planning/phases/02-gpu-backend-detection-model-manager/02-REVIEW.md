---
phase: 02-gpu-backend-detection-model-manager
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 35
files_reviewed_list:
  - app/api/routes_diagnostics.py
  - app/api/routes_models.py
  - app/api/routes_settings.py
  - app/main.py
  - app/models/__init__.py
  - app/models/backend.py
  - app/models/diagnostics.py
  - app/models/hf_token.py
  - app/models/manager.py
  - app/models/presets.py
  - app/models/registry.py
  - app/models/settings.py
  - app/models/vram.py
  - app/settings/service.py
  - app/storage/models_dir.py
  - tests/conftest.py
  - tests/test_cleanup.py
  - tests/test_concurrent_models.py
  - tests/test_create_job.py
  - tests/test_diagnostics_api.py
  - tests/test_gpu_detect.py
  - tests/test_hf_token.py
  - tests/test_manager_download.py
  - tests/test_manifest_helpers.py
  - tests/test_manifest_patch.py
  - tests/test_migration_idempotency.py
  - tests/test_presets.py
  - tests/test_reconcile.py
  - tests/test_resume.py
  - tests/test_settings_phase2.py
  - tests/test_spike_documented.py
  - tests/test_stage_files.py
  - tests/test_vram_budget.py
  - tests/test_wal.py
  - tests/test_windows_retry_integration.py
findings:
  critical: 2
  warning: 7
  info: 3
  total: 12
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-19
**Depth:** standard
**Files Reviewed:** 35
**Status:** issues_found

## Summary

Phase 2 adds the GPU backend detection, the model manager lifecycle, the
diagnostics + models + settings APIs, and the registry/presets data. The
typed-error boundary, the lazy-import discipline, and the strict-vs-lax
Pydantic config are well-structured. However, two BLOCKER-class defects
are present: (1) the boot lifespan builds the SQLAlchemy engine and the
`ModelManager` with a stale `data_dir` after `apply_pending()` swaps the
in-memory current, leaving the DB and the model cache looking at a
different path than `settings.service.current()` reports; (2) `PATCH
/settings` returns the full serialized `Settings` including the
base64-encoded `hf_token` in the response body, leaking the token that
`GET /settings` carefully nulls. Several WARNINGs cover broken download
progress reporting, a duplicate-download race, the CPU VRAM probe
ignoring loaded models, the budget gate being effectively bypassed for
STT/diarize (whose `expected_size_bytes` is `None`), and a silent data
loss path where a non-restart PATCH drops a pending `data_dir` change.

## Critical Issues

### CR-01: Boot lifespan builds engine + ModelManager with stale `data_dir` after `apply_pending()`

**File:** `app/main.py:157-189`
**Issue:** The lifespan builds the engine and session factory with the
local `settings` variable BEFORE calling `settings_service.apply_pending()`.
When a pending restart-required `data_dir` change exists on disk (written
by a prior `PATCH /settings` that set `X-Restart-Required: true`),
`apply_pending()` swaps `_State.settings` to the NEW `data_dir` and
rewrites the disk file without the `pending` key. But the engine
(`make_engine(settings)` at line 157), the session factory, and
`configure_manager(ModelManager(settings))` at line 189 all still hold
the OLD `settings` local variable. The result after a boot that applies
a pending `data_dir`:

- `settings_service.current().data_dir` reports the NEW path.
- The SQLAlchemy engine points at the OLD `data_dir` DB.
- `ModelManager._settings` (used by `ensure_downloaded`,
  `list_installed`, `verify` via `spec_file_path(self._settings, ...)`)
  points at the OLD `data_dir`, so model files are read/written under
  the OLD path while `current()` reports the NEW one.

The whole point of `apply_pending()` (H1: apply the restart-required
change on the next restart) is defeated: the user moved `data_dir`, the
settings file says the move succeeded, but the DB and the model cache
are still at the old location. The existing tests never exercise this
path because `tests/conftest.py` writes a settings file with no
`pending` key, so `apply_pending()` returns `False` and the bug is
dormant.

**Fix:** Refresh the local `settings` after `apply_pending()` and build
the engine AFTER it. The correct order is: load -> apply_pending -> build
engine -> configure session factory -> configure manager.

```python
# Apply pending BEFORE building the engine so a restart-required
# data_dir change takes effect on this boot.
old_data_dir = settings.data_dir
if settings_service.apply_pending():
    settings = settings_service.current()
    logger.info(
        "applied pending settings on boot: data_dir changed from %s to %s",
        old_data_dir,
        settings.data_dir,
    )

# Ensure the configured data directory exists (now using the applied value).
Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

engine = make_engine(settings)
await apply_migrations(engine)
session_factory = make_sessionmaker(engine)
configure(session_factory, settings)

set_manager_state(ManagerState(live_vram_bytes={}))
configure_manager(ModelManager(settings))
```

### CR-02: `PATCH /settings` leaks the base64-encoded `hf_token` in the response body

**File:** `app/api/routes_settings.py:45-66`
**Issue:** `patch_settings` returns `result` (the in-memory `Settings`
after the PATCH) with `response_model=Settings`. FastAPI serializes the
model via the `_serialize_hf_token` field_serializer, which base64-encodes
the cleartext token. So when a client sends `PATCH /settings
{"hf_token": "hf_abc123"}`, the response body contains
`"hf_token": "aGZfYWJjMTIz"` (base64 of the cleartext token). Base64 is
trivially decodable, so this is a credential leak. `GET /settings`
explicitly nulls `hf_token` before returning (and documents D-05: "hf_token
is NEVER returned in the response"), but `PATCH /settings` does not apply
the same nulling — the two routes are inconsistent and the PATCH route
violates D-05. The existing tests (`test_get_settings_hf_token_is_null_in_response`,
`test_hf_token_is_base64_on_disk`) only assert on the GET response and
the on-disk file; none assert that the PATCH response body omits the
token, so the leak is unverified.

**Fix:** Null `hf_token` in the PATCH response body before returning,
mirroring `get_settings`:

```python
@router.patch("", response_model=Settings)
async def patch_settings(
    payload: UpdateSettingsRequest,
    response: Response,
) -> Settings:
    result, restart_required = await apply_update(payload)
    if restart_required:
        response.headers["X-Restart-Required"] = "true"
    body = result.model_dump()
    body["hf_token"] = None
    return body  # type: ignore[return-value]
```

## Warnings

### WR-01: `POST /models/{id}/download` does not dedupe in-flight downloads; overwrites progress and spawns a duplicate task

**File:** `app/api/routes_models.py:126-146`
**Issue:** `download_model` unconditionally overwrites `_in_flight[id]`
with a fresh `DownloadProgress(state="queued")` and then
`asyncio.create_task(_run_download(...))`. If a download is already
running for `id`, the in-flight progress entry is reset to `queued`
(corrupting the status reported by `GET /models/{id}/status` and the
SSE stream), and a SECOND background task is spawned that races with
the first. Both tasks then call `manager.ensure_downloaded` for the
same target concurrently and write to the same shared `_in_flight[id]`
progress object (because `_run_download` uses `setdefault`, which
returns the entry that `download_model` just reset).

**Fix:** Check `_in_flight` for a running/queued entry and return the
existing `task_id` (or a 409) instead of starting a second task.
Alternatively, track an active `asyncio.Task` per id and await/reuse it.

### WR-02: SSE `download-progress` emits only on state change; byte-level progress is never reported

**File:** `app/api/routes_models.py:160-190`, `app/api/routes_models.py:99-123`
**Issue:** The SSE generator only emits an `event: progress` frame when
`progress.state` changes (`if current_state != last_state`). Between
state transitions it sends only `": ping"` heartbeats. Meanwhile
`_run_download` never updates `progress.bytes_done` during the download
— it only sets `bytes_done = spec.expected_size_bytes` on completion.
So a consumer of `GET /models/{id}/download-progress` sees `queued`,
then `running`, then a long silence with only heartbeats, then `done`.
There is no byte-level progress, which defeats the purpose of an SSE
progress stream (the React UI cannot render a progress bar).

**Fix:** Have `ensure_downloaded` (or a wrapper) periodically update
`progress.bytes_done` from the on-disk partial file size, and have the
SSE generator emit a frame whenever `bytes_done` changes (throttled).

### WR-03: `probe_vram` CPU path always returns `loaded=[]`, ignoring `manager_state`

**File:** `app/models/vram.py:133-161`
**Issue:** The CPU branch of `probe_vram` constructs the `VRAMState`
with `loaded=[]` in both the success and error paths. The CUDA/ROCm
branch uses `loaded=_loaded_list(manager_state)` so that
`GET /diagnostics/vram` reflects the resident models. On CPU the route
returns `loaded=[]` even when models are loaded, so the diagnostics
surface is inconsistent across backends and a CPU-mode user cannot see
what is resident.

**Fix:** Use `loaded=_loaded_list(manager_state)` in the CPU success
path (and the CPU error path can stay `[]` to match the CUDA error
path).

### WR-04: `ModelManager.load` reserves 0 VRAM for STT/diarize, bypassing the SC-4 budget gate

**File:** `app/models/manager.py:384-393`, `app/models/registry.py:32-69`
**Issue:** `expected_mb = (spec.expected_size_bytes or 0) / 1024**2`.
Every STT and diarize spec in the registry has `expected_size_bytes=None`
(only the LLM specs set an approximate size). So for STT/diarize,
`expected_mb = 0`, the budget check `(vram.used_mb + 0) > budget_mb`
passes trivially, and `vram_bytes = int(0 * 1024**2) = 0` is recorded
in `live_vram_bytes`. The SC-4 85% budget gate is therefore only
enforced for LLM loads; an STT load followed by a diarize load
(concurrent or not) is never budget-gated and contributes 0 bytes to
`used_mb`, so a subsequent LLM load also sees an understated `used_mb`.

**Fix:** Either populate `expected_size_bytes` for the STT/diarize
registry entries (even a rough approximation, as the comment in
`registry.py` says it is "an approximation used for VRAM budget math
only"), or refuse to load a spec whose `expected_size_bytes` is `None`
when the backend is GPU (the budget gate cannot be enforced without a
size estimate).

### WR-05: A non-restart `PATCH /settings` silently drops a pending restart-required `data_dir` change

**File:** `app/settings/service.py:208-214`
**Issue:** When `apply_update` handles a non-restart change (e.g. the
client PATCHes `quality_preset`), it writes `disk = new.model_dump()`
(no `pending` key) and sets `_State.pending = None`. If a prior
restart-required `data_dir` PATCH had queued a pending change on disk,
that pending change is silently overwritten and dropped from
`_State.pending`. The user's intended `data_dir` move is lost without
any signal. The comment says "drop any prior pending slot" so this is
deliberate, but it is data loss from the user's perspective: they
PATCHed `data_dir`, got `X-Restart-Required: true`, then PATCHed an
unrelated hot-swap field, and the `data_dir` change evaporated.

**Fix:** Preserve the existing pending slot across a non-restart PATCH.
Build `disk = new.model_dump()` and re-attach `disk[_PENDING_KEY] =
_State.pending.model_dump()` when `_State.pending is not None`, and do
not clear `_State.pending` in that case.

### WR-06: `ensure_downloaded` with a SHA set does not return early on a valid cached file; fails offline

**File:** `app/models/manager.py:268-285`
**Issue:** The corrupt-SHA fast-path runs only when
`spec.expected_sha256 is not None` and `target.exists()`. It computes
the SHA and DELETES the file on mismatch — but on MATCH it falls
through (no `return target`) and unconditionally calls
`hf_hub_download`. So a file that is already present and valid is
re-fetched on every call. Worse, if HF Hub is unreachable at that
moment (offline operation after a prior successful download),
`hf_hub_download` raises and `ensure_downloaded` propagates the error
instead of returning the valid cached file. The size-only fast-path
above explicitly requires `spec.expected_sha256 is None`, so any spec
with a SHA set cannot use the cached file offline. This is currently
dormant (no registry spec sets `expected_sha256`), but it is a latent
correctness bug for the moment a SHA is added.

**Fix:** In the corrupt-SHA fast-path, return `target` early when the
SHA matches:

```python
if (
    target.exists()
    and spec.expected_sha256 is not None
    and target.stat().st_size > 0
):
    if _sha256_of_file(target) == spec.expected_sha256:
        return target
    _log.warning("corrupt model file at %s (sha mismatch); re-downloading", target)
    try:
        target.unlink()
    except OSError:
        pass
```

### WR-07: `_resolve` 404 `available` field wraps the error message instead of listing valid ids

**File:** `app/api/routes_models.py:63-78`
**Issue:** On an unknown id, the route builds
`"available": sorted(str(k) for k in exc.args)`. `exc` is the
`KeyError` raised by `get_spec`, which is constructed as
`KeyError(f"unknown model id: {id!r}; available: {sorted(REGISTRY.keys())}")`.
So `exc.args` is a 1-tuple whose single element is the entire error
string. The `available` field in the 404 body is therefore
`["unknown model id: 'foo'; available: ['balanced.diarize', ...]"]`
— a one-element list containing the full message — not the intended
list of valid ids. The actionable information the docstring claims
("lists every valid id") is not actually surfaced as a clean list.

**Fix:** Import `REGISTRY` (or expose a `list_ids()` helper) and build
the field directly:

```python
from app.models.registry import REGISTRY
...
raise HTTPException(
    status_code=404,
    detail={
        "error": "unknown_model",
        "id": id,
        "available": sorted(REGISTRY.keys()),
    },
) from exc
```

## Info

### IN-01: `download_status` default uses the registry id as `model_id`, inconsistent with the in-flight dict

**File:** `app/api/routes_models.py:149-157`
**Issue:** When no in-flight entry exists, the route returns
`DownloadProgress(model_id=id, state="queued")` where `id` is the
registry id (e.g. `"balanced.llm"`). The in-flight dict stores
`model_id=spec.repo_id` (e.g. `"Qwen/Qwen2.5-7B-Instruct-GGUF"`). A
caller polling status before the download starts sees a different
`model_id` shape than after.

**Fix:** Resolve the spec first and use `spec.repo_id`, or document
that `model_id` may be either form.

### IN-02: `_decode_hf_token` cleartext fallback can corrupt tokens that happen to be valid base64

**File:** `app/models/settings.py:91-113`
**Issue:** The `mode="before"` validator tries to base64-decode the
incoming string and falls back to treating it as cleartext if decoding
fails. Real HF tokens prefixed with `hf_` contain `_`, which is not
valid standard-base64, so they fall through cleanly. But a token
without the `hf_` prefix that is coincidentally valid base64 AND
decodes to valid UTF-8 would be silently corrupted (the decoded bytes
would be stored instead of the original string). The fallback is
convenient for tests but fragile for production inputs.

**Fix:** Require an explicit marker for the on-disk base64 form (e.g.
a `b64:` prefix) so the cleartext path is unambiguous, or only decode
when the value round-trips (`_b64_encode(_b64_decode(value)) == value`).

### IN-03: `ModelManager.list_installed` lists duplicate specs for shared registry entries

**File:** `app/models/manager.py:467-481`
**Issue:** `list_installed` iterates every `REGISTRY.items()` entry.
`small.diarize`, `large.diarize`, and `balanced.diarize` all map to
the same `_BALANCED_DIARIZE` spec (and `large.stt` maps to
`_BALANCED_STT`). When the diarize file is on disk, the same `ModelSpec`
is appended three times (once per aliasing id). `GET /models`
therefore reports duplicates in `installed`.

**Fix:** Deduplicate by `(repo_id, file)` or by the resolved target
path before appending.

---

_Reviewed: 2026-06-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_