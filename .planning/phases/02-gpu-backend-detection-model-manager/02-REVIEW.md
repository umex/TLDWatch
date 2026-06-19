---
phase: 02-gpu-backend-detection-model-manager
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - app/models/manager.py
  - app/api/routes_models.py
  - app/models/vram.py
  - tests/test_download_routes.py
  - tests/test_diagnostics_api.py
  - tests/conftest.py
findings:
  critical: 1
  warning: 6
  info: 5
  total: 12
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-19
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 02 gap-closure changes (plans 02-04 download offloading +
non-Xet resume path, and 02-05 `probe_vram` graceful-degradation fallback) plus
the full current state of each in-scope file. The core fixes are sound:
`asyncio.to_thread` correctly offloads the synchronous `hf_hub_download`,
`_loaded_list(manager_state)` now flows through every CPU/stub error-fallback
so the SC-4 indicator degrades gracefully, and the belt-and-suspenders
`hf_xet=False` / `HF_HUB_DISABLE_XET=1` forcing is verified by AST + env-capture
tests.

One BLOCKER-grade concurrency defect ships in the new env-var forcing
(`HF_HUB_DISABLE_XET` is mutated and restored on a process-global from inside
per-download worker threads with no synchronization), plus several robustness
gaps in the fire-and-forget background task, the SSE generator's terminal
state handling, and real-time-timer flakiness in the new live tests.

## Critical Issues

### CR-01: `HF_HUB_DISABLE_XET` env var is mutated process-global from concurrent worker threads with no lock

**File:** `app/models/manager.py:357-406`
**Issue:** `ensure_downloaded` sets `os.environ["HF_HUB_DISABLE_XET"] = "1"`
before calling `await asyncio.to_thread(hf_hub_download, ...)` and restores it
in a `finally` (`os.environ.pop` if the prior value was `None`, else reassign).
`asyncio.to_thread` runs `hf_hub_download` on the default
`ThreadPoolExecutor`, so two concurrent downloads (e.g. `POST /models/small.stt/download`
and `POST /models/balanced.llm/download` issued back-to-back) execute the body
in two worker threads simultaneously. The save/restore is per-call and
unsynchronized:

- Thread A enters, `_prev_xet_A = None`, sets env to `"1"`, starts download.
- Thread B enters, `_prev_xet_B = "1"` (the value A set), sets env to `"1"`,
  starts download.
- Thread A finishes first, hits `finally`, sees `_prev_xet_A is None`, **pops**
  the env var.
- Thread B is still inside `hf_hub_download`. The env var is now unset. If
  `huggingface_hub` (or any sub-import it triggers lazily mid-download, e.g.
  the Xet backend shim) re-reads `HF_HUB_DISABLE_XET` after this point, the
  Xet backend is silently re-enabled for B's download -- exactly the HW-09
  regression 02-04 was written to prevent. The `_prev_xet` snapshot is taken
  per-call, so restores clobber each other.

`os.environ` is process-global and not thread-safe for read-modify-write
patterns; the dedupe-by-prior-value logic only works for strictly nested calls,
which `asyncio.to_thread` does NOT guarantee.

**Fix:** Hold a module-level reference count under a lock, or force the env
var once at lifespan startup and never restore it. The simplest correct fix is
to set it once at import / lifespan time (the classic non-Xet path is the
desired global behavior for the whole app):

```python
# At module load or in configure_manager():
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
```

…and remove the save/restore block in `ensure_downloaded` (keep the
`hf_xet=False` kwarg, which is per-call and thread-safe). If a save/restore
is strictly required, guard it with a `threading.Lock` and a refcount so the
env var is only restored when the last concurrent download finishes.

## Warnings

### WR-01: Fire-and-forget `asyncio.create_task` with no stored reference -- task can be garbage-collected mid-download

**File:** `app/api/routes_models.py:212`
**Issue:** `asyncio.create_task(_run_download(spec, category, id, settings))`
discards the returned `Task` object. CPython's `asyncio` documentation
explicitly warns: "Save a reference to the result of this function, to avoid a
task disappearing mid-execution." The event loop holds only a weak reference
to the task; if the only strong reference is the transient return value, the
task can be collected before completion, silently aborting a download the
client already received a 202 for. The `_in_flight` entry would then be left
stuck in `"running"` forever (the `finally` in `_run_download` never runs),
defeating the 409 dedupe for that id until process restart.

**Fix:** Keep a strong reference for the lifetime of the task:

```python
task = asyncio.create_task(_run_download(spec, category, id, settings))
_download_tasks[id] = task
task.add_done_callback(lambda t: _download_tasks.pop(id, None))
```

with a module-level `_download_tasks: dict[str, asyncio.Task] = {}`.

### WR-02: `_run_download` does not set `progress.state` on cancellation -- SSE clients hang on a "running" frame

**File:** `app/api/routes_models.py:155-176`
**Issue:** The `try/except/finally` sets `progress.state = "done"|"failed"` on
every exit path **except** `asyncio.CancelledError`. In Python 3.8+
`CancelledError` inherits from `BaseException`, so neither
`except ModelManagerError` nor `except Exception` catches it; the `finally`
only cancels `poll_task` and swallows its `CancelledError`. If the background
download task is cancelled (e.g. lifespan teardown, or a future cancel-on-new-
download feature), `progress.state` stays `"running"` and the SSE generator at
`routes_models.py:259` never emits a terminal frame -- the client streams
heartbeats indefinitely. The 409 dedupe at `routes_models.py:196` also keeps
blocking new downloads for that id.

**Fix:** Add a `BaseException` (or explicit `asyncio.CancelledError`) handler
that flips state to `"failed"`:

```python
except asyncio.CancelledError:
    progress.state = "failed"
    progress.message = "cancelled"
    raise
except ModelGatedError as exc:
    ...
```

### WR-03: `_poll_bytes` closure contains dead `import time` / `_ = time` leftover

**File:** `app/api/routes_models.py:124-152`
**Issue:** The poll coroutine imports `time` at line 125 and assigns
`_ = time  # keep import local to the closure` at line 152, but `time` is
never actually used inside `_poll_bytes` (the sleep is `asyncio.sleep(0.5)`).
The `_ = time` statement is dead code, suggesting the closure was refactored
and leftover state remains. Additionally, the `finally` at line 174 catches
`(asyncio.CancelledError, Exception)`; the broad `Exception` clause can mask
unexpected errors from the poll body (which already has its own `except
OSError`).

**Fix:** Remove the dead `import time` and `_ = time` lines, and narrow the
`finally` cleanup to `asyncio.CancelledError` only:

```python
finally:
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
```

### WR-04: `download_status` and `download_progress_sse` declare an unused `settings` dependency

**File:** `app/api/routes_models.py:218-269`
**Issue:** Both route handlers accept `settings: Settings = Depends(get_settings)`
but never reference it. The dependency still executes on every request (and
any side effect of `get_settings` runs), and the unused parameter misleads
readers into thinking the response is settings-dependent. It also adds a
phantom dependency to FastAPI's dependency cache.

**Fix:** Drop the parameter from both signatures, or if a dependency is
required for auth/TrustedHost consistency, mark it `_settings` and document
why.

### WR-05: Live SSE tests depend on real 5-7s wall-clock timers -- flaky on loaded CI

**File:** `tests/test_download_routes.py:122-165, 176-220`
**Issue:** `test_download_progress_sse_streams_live` and
`test_download_progress_byte_level` schedule `threading.Timer(6.0, ...)` and
collect SSE lines for up to 7s, asserting the 5s `: ping` heartbeat fires
within the window. On a loaded CI runner the heartbeat can slip past 7s (the
`now - heartbeat > 5.0` check uses `time.monotonic()` sampled every 0.1s, but
if the event loop is starved the sample cadence slips), causing intermittent
`assert ping_lines` failures unrelated to the code under test. The
`elapsed += 0.1` accumulator is also a count of `aiter_lines` iterations, not
wall-clock seconds -- on a fast connection it undercounts real elapsed time
and can break the loop early before the heartbeat fires.

**Fix:** Use `time.monotonic()` for the elapsed check (not iteration count),
and raise the window to ~10s or poll until the heartbeat is seen with a hard
upper bound:

```python
deadline = time.monotonic() + 10.0
async for line in r.aiter_lines():
    ...
    if saw_done or time.monotonic() >= deadline:
        break
```

### WR-06: `_in_flight` cleared by tests while the background download task is still alive -- "Task was destroyed but it is pending!" risk

**File:** `tests/test_download_routes.py:108-109, 155-157, 206-208`
**Issue:** Every live test's `finally` calls `_clear_in_flight(model_id)`
immediately after `release_event.set()`. The release unblocks the worker
thread, but the `asyncio.to_thread` coroutine still needs to be scheduled back
onto the event loop, `_run_download` still needs to set `state="done"` and run
its `finally`, and the task is not awaited. When pytest-asyncio tears down the
loop at test end, the task is often still pending -> `Task was destroyed but it
is pending!` warning, and on some interpreters a `RuntimeError` from the
finalizer. This is test-hygiene noise that hides real task-lifecycle bugs
(WR-01).

**Fix:** After `release_event.set()`, `await` the background task before
clearing `_in_flight`. This requires `download_model` to surface the task
(see WR-01's `_download_tasks` dict) so the test can do
`await _download_tasks.pop(model_id)`.

## Info

### IN-01: `DownloadProgress.state` literal includes `"resuming"` but no code path ever sets it

**File:** `app/models/manager.py:156`, `app/api/routes_models.py:196`
**Issue:** The `state` Literal declares `"resuming"` and the 409 dedupe check
at `routes_models.py:196` only matches `("queued", "running")`. If a future
change sets `state="resuming"` (the obvious value for the HW-09 resume-after-
crash path), the dedupe will not catch it and a second POST will overwrite
`_in_flight[id]` and spawn a racing second background task. Today this is
unreachable, so it is a latent gap, not an active bug.

**Fix:** Either remove `"resuming"` from the Literal until it is wired, or add
it to the dedupe set: `existing.state in ("queued", "running", "resuming")`.

### IN-02: `_resolve` return type annotated as `tuple[ModelSpec, "object"]` instead of `ModelCategory`

**File:** `app/api/routes_models.py:64`
**Issue:** The string forward-ref `"object"` defeats the type checker for the
category slot; `get_category` returns `ModelCategory`. Downstream callers
(`load_model`, `_run_download`) lose type information for `category`.

**Fix:** `def _resolve(id: str) -> tuple[ModelSpec, ModelCategory]:` and import
`ModelCategory` (already imported transitively via `app.models.diagnostics`).

### IN-03: `_run_download`'s `category` parameter has no type annotation

**File:** `app/api/routes_models.py:105`
**Issue:** `async def _run_download(spec: ModelSpec, category, id: str, settings: Settings)`
leaves `category` untyped, inconsistent with the rest of the module's
annotations and the `ModelCategory` type used everywhere else.

**Fix:** `category: ModelCategory`.

### IN-04: `_loaded_list` is imported by tests/conftest.py despite the leading-underscore "private" convention

**File:** `app/models/vram.py:81`, `tests/conftest.py:212`
**Issue:** `_loaded_list` is a leading-underscore "private" helper but is
imported by `tests/conftest.py:212` (`from app.models.vram import _loaded_list`)
to build the mock `probe_vram` default. It is not in `__all__`. The underscore
says "private" but the cross-module test import says "shared seam"; either
intent is fine but it should be declared. This is a maintainability signal,
not a bug.

**Fix:** Either rename to `build_loaded_list` and add to `__all__`, or
document the leading-underscore-as-test-seam convention in the docstring.

### IN-05: `list_installed` re-imports `_CATEGORY_SHORTS` inside the loop body

**File:** `app/models/manager.py:536-542`
**Issue:** The `from app.models.registry import _CATEGORY_SHORTS` import is
inside the `for id, spec in REGISTRY.items():` loop, so the import machinery
runs once per registry entry on every `list_installed()` call. The
`noqa: PLC0415` comment acknowledges the import-in-function pattern, but the
placement inside the loop is unnecessary -- it works because Python caches
`sys.modules`, but it is still a code smell.

**Fix:** Hoist the import to the top of `list_installed` (or to module top
given `registry` is already imported at module top on line 55).

---

_Reviewed: 2026-06-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_