# Phase 2: GPU Backend Detection + Model Manager - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 16 new + 4 extended
**Analogs found:** 14 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/models/settings.py` (extend) | model | CRUD (lax/strict Pydantic) | self (Phase 1) | exact |
| `app/models/diagnostics.py` (new) | model | CRUD (Pydantic only) | `app/models/manifest.py` | exact |
| `app/models/backend.py` (new) | service | event-driven (boot-time detect) | `app/jobs/reconcile.py` | role-match |
| `app/models/vram.py` (new) | service | request-response (probe on demand) | `app/storage/atomic.py` | partial |
| `app/models/presets.py` (new) | utility | CRUD (typed data) | `app/models/summary.py` | exact |
| `app/models/manager.py` (new) | service | CRUD + stateful (load/unload) | `app/jobs/manifest.py` | role-match |
| `app/models/hf_token.py` (new) | service | request-response (HEAD call) | `app/jobs/cleanup.py` | role-match |
| `app/storage/models_dir.py` (new) | utility | path resolution | `app/storage/fs.py` | exact |
| `app/api/routes_diagnostics.py` (new) | route | request-response | `app/api/routes_health.py` | exact |
| `app/api/routes_models.py` (new) | route | request-response + SSE | `app/api/routes_jobs.py` | role-match |
| `app/main.py` (extend) | config | lifespan boot | self | exact |
| `tests/conftest.py` (extend) | test fixture | test setup | self | exact |
| `tests/test_gpu_detect.py` (new) | test | unit | `tests/test_settings.py` | exact |
| `tests/test_presets.py` (new) | test | unit | `tests/test_summary_models.py` | exact |
| `tests/test_manager_download.py` (new) | test | unit + tmp dir | `tests/test_atomic_windows_retry.py` | role-match |
| `tests/test_vram_budget.py` (new) | test | unit + httpx | `tests/test_settings.py` | exact |
| `tests/test_concurrent_models.py` (new) | test | unit + httpx | `tests/test_settings.py` | exact |
| `tests/test_settings_phase2.py` (new) | test | unit + httpx | `tests/test_data_dir_validation.py` | exact |
| `tests/test_hf_token.py` (new) | test | unit + httpx | `tests/test_settings.py` | exact |
| `tests/test_diagnostics_api.py` (new) | test | unit + httpx | `tests/test_settings.py` | exact |
| `pyproject.toml` (extend) | config | dependency pinning | self | exact |

## Pattern Assignments

### `app/models/settings.py` (extend — model, CRUD)

**Analog:** self (Phase 1 already ships `Settings` + `UpdateSettingsRequest`).

**Existing shape to extend** (full file, `app/models/settings.py:1-68`):

```python
from pydantic import BaseModel, ConfigDict, model_validator

class Settings(BaseModel):
    """Persisted application settings."""
    model_config = ConfigDict(extra="forbid")
    data_dir: str

class UpdateSettingsRequest(BaseModel):
    """Strict input model for PATCH /settings."""
    model_config = ConfigDict(strict=True, extra="forbid")
    data_dir: str
    @model_validator(mode="after)
    def _validate_data_dir(self) -> "UpdateSettingsRequest": ...
```

**Phase 2 extension pattern:** add new fields to `Settings` with defaults; add matching optional fields to `UpdateSettingsRequest` (`extra="forbid"` already excludes `backend` / `backend_probe` from the request model — keep that contract by NOT declaring them on `UpdateSettingsRequest`). Enum + nested-model declarations use the same `ConfigDict(extra="forbid")` discipline as `JobManifest` and `StageTimestamps`.

**Validation pattern** (`app/models/settings.py:44-65`): `model_validator(mode="after")` is the Phase 1 convention for cross-field / path-shape rules. For Phase 2 the new validators (e.g. `vram_budget_fraction: float = 0.85` in range 0.1..0.95; `hf_token` base64 encode/decode via `field_serializer` + `field_validator`) follow the same shape — see `app/models/job.py:128-139` for the `field_serializer` precedent used on `created_at`.

---

### `app/models/diagnostics.py` (new — model, CRUD)

**Analog:** `app/models/manifest.py` (the closest existing single-class Pydantic model with `extra` discipline).

**Imports + class shape** (`app/models/manifest.py:1-37`):

```python
from __future__ import annotations
from pydantic import BaseModel, Field
from app.models.common import StageTimestamps

class JobManifest(BaseModel):
    """File-on-disk job manifest, written atomically by every stage mutator."""
    schema_version: int = 1
    job_id: str
    source_type: str | None = None
    ...
    summary_kinds: list[str] = Field(default_factory=list)
    diarization_enabled: bool = False
    status: str = "queued"
    current_stage: str | None = None
    stage_timestamps: StageTimestamps
    error: str | None = None
```

**Phase 2 pattern:** `BackendProbe(BaseModel)` follows the same `Field(default_factory=...)` + `str | None = None` convention. It is a strict response model (the route layer returns it), so add `model_config = ConfigDict(extra="forbid")` to match `Settings`.

---

### `app/models/backend.py` (new — service, event-driven boot-time detect)

**Analog:** `app/jobs/reconcile.py` (a module-level async function called once at boot, with `logger` reporting per the same convention).

**Boot-time logging pattern** (`app/jobs/reconcile.py` — pattern; the file imports `from app.jobs import reconcile as reconcile_module` and uses `logger.info(...)` / `logger.exception(...)` exactly as `app/main.py:113-125` does):

```python
# app/main.py lifespan:
try:
    reconcile_summary = await reconcile_module.reconcile_all(settings, session_factory)
    logger.info(
        "reconcile summary: scanned=%d updated=%d missing_manifests=%d",
        reconcile_summary.get("scanned", 0),
        reconcile_summary.get("updated", 0),
        len(reconcile_summary.get("missing_manifests", [])),
    )
except Exception:
    logger.exception("startup reconciliation failed; refusing to start")
    raise
```

**Module-level logger convention** (`app/jobs/service.py:37`):

```python
_log = logging.getLogger(__name__)
```

**Subprocess + WMI pattern:** there is no existing `subprocess` / `wmic` analog in Phase 1; the closest `os.environ` / `Path` work is in `app/storage/fs.py:50-57` and `app/storage/db.py:36-39`. Use `subprocess.run(..., timeout=3, capture_output=True, text=True)` — no Phase 1 helper to inherit, but mirror the `os.environ.get(...)` discipline from `app/storage/fs.py` (no `os` import in the function body; just use `os.environ.get("ROCM_PATH") or os.environ.get("HIP_PATH")`).

**No analog for the `pydantic_settings`-style env override** — Phase 1 settings are file-only. `app/models/settings.py:1-19` shows the file-only `Settings(BaseModel)` shape.

---

### `app/models/vram.py` (new — service, request-response probe)

**Analog:** `app/storage/atomic.py` (a small, pure-function module that does one I/O thing and returns a typed result).

**Module convention** (`app/storage/atomic.py:1-25`):

```python
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
import aiofiles
from app.storage.retry import retry_windows
```

**Cross-module typed-result shape:** Phase 1 returns Pydantic models from atomic write helpers (e.g. `write_manifest` returns the `Path`, `read_manifest` returns `JobManifest`). The new `probe_vram(backend, manager_state) -> VRAMState` follows the same `TypedDict` / `BaseModel` result convention — declare `VRAMState` in `app/models/diagnostics.py` alongside `BackendProbe`.

---

### `app/models/presets.py` (new — utility, typed data)

**Analog:** `app/models/summary.py` (the closest "enums + nested BaseModel" pattern).

**Enum + Literal + frozenset pattern** (`app/models/summary.py:25-44`):

```python
from typing import Literal, get_args
from pydantic import BaseModel, Field

SummaryKind = Literal["meeting", "investment", "concept", "quick_recap"]
_ALLOWED_SUMMARY_KINDS: frozenset[str] = frozenset(get_args(SummaryKind))

def validate_summary_kind(kind: str) -> str:
    """Return kind iff it is one of the four SummaryKind literals."""
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"invalid summary kind: {kind!r}")
    if kind not in _ALLOWED_SUMMARY_KINDS:
        raise ValueError(...)
    return kind
```

**Phase 2 pattern:** `GpuBackend(str, Enum)` + `QualityPreset(str, Enum)` + `ModelCategory(str, Enum)` use the same `Enum` + `_ALLOWED_*` frozenset shape. The `PRESETS: dict[QualityPreset, ModelSet]` table mirrors the literal-typed mapping in `app/models/job.py:25-27` (`StageNameLiteral`).

---

### `app/models/manager.py` (new — service, stateful CRUD with load/unload)

**Analog:** `app/jobs/manifest.py` (a service that does a write-manifest-first / state-update-last protocol with explicit `model_copy(update=...)` discipline).

**State-update + atomic-write pattern** (`app/jobs/manifest.py:117-126`, `194-249`):

```python
async def write_manifest(settings: Settings, manifest: JobManifest) -> Path:
    path = manifest_path(settings, manifest.job_id)
    await atomic_write_json(path, manifest.model_dump(mode="json"))
    return path
```

**model_copy + strict-update discipline** (`app/jobs/manifest.py:196-216`):

```python
current = await read_manifest(settings, job_id)
new_manifest = current.model_copy(deep=True)
# PROTECTED: current_stage comes from the function arg, never the patch.
new_manifest.current_stage = stage
new_ts = new_manifest.stage_timestamps.model_copy(update={stage: utcnow_iso()})
new_manifest = new_manifest.model_copy(update={"stage_timestamps": new_ts})
if manifest_patch is not None:
    updates = manifest_patch.model_dump(exclude_unset=True)
    new_manifest = new_manifest.model_copy(update=updates)
```

**In-memory module state pattern** (`app/settings/service.py:44-60`):

```python
class _State:
    """Module-level holder for the in-memory Settings and its path."""
    settings: Settings | None = None
    path: Path | None = None
    pending: Settings | None = None
```

`ModelManager` uses the same `_State` class-with-class-attributes pattern for the singleton (`_manager: ModelManager | None`, `get_manager()`, `configure_manager(m)`).

**Download state JSON pattern:** `ModelManager` writes per-download state files via `await atomic_write_json(download_state_path, state.model_dump())` — same helper as `app/jobs/manifest.py:124-125` uses.

---

### `app/models/hf_token.py` (new — service, request-response HEAD call)

**Analog:** `app/jobs/cleanup.py` (the closest "single async function with a 4-state result + error-type mapping" shape).

**Custom error type + handler pattern:** no existing module raises typed errors and the route layer maps them to HTTP codes via `HTTPException`. Use the `from pydantic import ValidationError` + `except ValidationError as exc: raise HTTPException(422, detail=exc.errors())` pattern from `app/api/routes_jobs.py:153-155` for the typed-error-to-HTTP bridge. Define a `ModelGatedError`, `VramBudgetExceeded`, `ConcurrentModelRefused` exception class in `app/models/manager.py` and map to 403 / 507 / 409 in the route.

---

### `app/storage/models_dir.py` (new — utility, path resolution)

**Analog:** `app/storage/fs.py` (the canonical path-helper module).

**Function shape** (`app/storage/fs.py:60-74`):

```python
def data_dir(settings: Settings) -> Path:
    """Return the configured data directory as a :class:`Path`."""
    return Path(settings.data_dir)

def job_dir(settings: Settings, job_id: str) -> Path:
    """Return the per-job directory: ``<data_dir>/jobs/<job_id>``."""
    return data_dir(settings) / "jobs" / job_id

async def ensure_job_dir(settings: Settings, job_id: str) -> Path:
    """Create and return the per-job directory."""
    path = job_dir(settings, job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
```

**Phase 2 pattern:** `resolve_data_models_dir(settings) -> Path` returns `data_dir(settings) / "models"`. `ensure_models_dir(settings) -> Path` mirrors `ensure_job_dir` with `mkdir(parents=True, exist_ok=True)`. Category subdirs (`stt/`, `diarize/`, `llm/`) are constructed in `ModelManager.ensure_downloaded` via `data_models_dir / category` — no extra helper needed; the allowlist pattern (`ALLOWED_SOURCE_EXTS` frozenset, `app/storage/fs.py:33-35`) is the precedent for validating the category name.

---

### `app/api/routes_diagnostics.py` (new — route, request-response)

**Analog:** `app/api/routes_health.py` (minimal router shape; no DB / settings deps for `gpu-burn` re-detect).

**Minimal router** (`app/api/routes_health.py:1-13`):

```python
"""``GET /health`` route - liveness probe."""
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Router registration** (`app/main.py:211-213`):

```python
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(settings_router)
```

**Pattern for POST + JSON response** (`app/api/routes_jobs.py:121-156`):

```python
@router.post(
    "/{job_id}/stage",
    response_model=JobManifest,
    responses={
        404: {"description": "job or manifest not found"},
        422: {"description": "ManifestPatch validation failed"},
    },
)
async def post_stage(
    job_id: str,
    payload: StageUpdateRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobManifest:
    try:
        canonical_id = validate_job_id(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job id") from exc
    try:
        manifest = await update_stage(...)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="manifest not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return manifest
```

`POST /diagnostics/gpu-burn` follows this exact shape (no body, no path param, calls `backend.detect()` + `backend.burn_test()`, calls `settings_service.apply_update` for the new `backend` + `backend_probe`; returns `{"probe": BackendProbe, "active_backend": GpuBackend, "settings_written": true}`). `GET /diagnostics/vram` mirrors `GET /health` + `Depends(get_settings)` to read the current backend.

---

### `app/api/routes_models.py` (new — route, request-response + SSE)

**Analog:** `app/api/routes_jobs.py` (the most complete existing router: `APIRouter(prefix=...)`, `Depends(get_session)`, `Depends(get_settings)`, `HTTPException` 404/400/422 mapping, `validate_*` helper at the boundary).

**Router prefix + tags** (`app/api/routes_jobs.py:41`):

```python
router = APIRouter(prefix="/jobs", tags=["jobs"])
```

**Dep injection pattern** (`app/api/routes_jobs.py:49-59`):

```python
async def post_job(
    payload: CreateJobRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    return await create_job(session, settings, ...)
```

**SSE pattern:** Phase 1 has no existing SSE endpoint. The `text/event-stream` response uses `from fastapi.responses import StreamingResponse` and an `async def event_generator()` that yields `"event: progress\ndata: {...}\n\n"` — the precedent for streaming-shape async functions is `app/storage/atomic.py:31-58` (async context manager) and `app/jobs/manifest.py:117-126` (async with `atomic_write_json`). For Phase 2 the simplest correct shape: `return StreamingResponse(event_generator(), media_type="text/event-stream")`.

**Idempotent unload pattern:** no existing 204 No Content precedent; use `from fastapi import status` + `response_model=None` + `status_code=status.HTTP_204_NO_CONTENT` (the `status_code` import is already in use at `app/api/routes_jobs.py:22`).

---

### `app/main.py` (extend — config, lifespan)

**Analog:** self (the existing first-boot bootstrap + lifespan ordering).

**First-boot default-DataDir pattern** (`app/main.py:53-90`):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_path = bootstrap_settings_path()
    bootstrap_dir = bootstrap_path.parent

    if not bootstrap_path.exists():
        # First boot. The default data_dir is the ABSOLUTE path of
        # the bootstrap directory so the data dir is decoupled from
        # the process working directory.
        default_data_dir = str(bootstrap_dir.resolve())
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        await atomic_write_json(
            bootstrap_path, Settings(data_dir=default_data_dir).model_dump()
        )
        logger.info("Wrote initial settings file at %s", bootstrap_path)

    settings, pending = settings_service.load_settings_from_disk(bootstrap_path)
    ...
    engine = make_engine(settings)
    await apply_migrations(engine)
    session_factory = make_sessionmaker(engine)
    configure(session_factory, settings)

    if settings_service.apply_pending():
        new_settings = settings_service.current()
        logger.info(...)
```

**Phase 2 extension:** AFTER `load_settings_from_disk` returns the in-memory `Settings` and BEFORE `configure(...)` (or as a sibling step right after), call `app.models.backend.detect()` + `app.models.backend.burn_test()`, then either:
- (first boot, `backend` is None / not yet set) `apply_update` a new `UpdateSettingsRequest` with the new `backend` + `backend_probe` shape, OR
- (subsequent boot) skip the detect unless the user hits `POST /diagnostics/gpu-burn`.

Use the existing `settings_service.apply_update` so the disk write goes through the same atomic-write + pending-slot path. `try/except` with `logger.exception("first-run GPU detect failed; refusing to start")` mirrors the reconcile fail-fast at `app/main.py:122-125`.

**OpenAPI schema registration** (`app/main.py:157-168`):

```python
_EXTRA_OPENAPI_MODELS = [
    TranscriptSegment,
    Transcript,
    Summary,
    JobManifest,
    ManifestPatch,
    StageUpdateRequest,
    StaleCheckResponse,
]
```

Add `BackendProbe`, `BackendProbeResult` (whatever the final response model is named for `POST /diagnostics/gpu-burn`), `DownloadProgress`, `LoadedModelInfo`, `ModelSpec`, `ModelSet`, `QualityPreset`, `GpuBackend`, `ModelCategory` to this list so they appear in `components.schemas` for `openapi-typescript` codegen.

---

### `tests/conftest.py` (extend — test fixture)

**Analog:** self (the `tmp_data_dir` + `app_under_test` + `client` fixture triplet).

**Existing fixture shape** (`tests/conftest.py:31-113`):

```python
@pytest.fixture
def tmp_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    tmp_root = Path(tempfile.mkdtemp(prefix="tan-test-"))
    data_dir = tmp_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        Settings(data_dir=str(data_dir.resolve())).model_dump_json(),
        encoding="utf-8",
    )
    from app.storage import fs as fs_module
    monkeypatch.setattr(fs_module, "bootstrap_settings_path", lambda: settings_path)
    from app import main as main_module
    monkeypatch.setattr(main_module, "bootstrap_settings_path", lambda: settings_path)
    try:
        yield tmp_root
    finally:
        configure(None, None)
        shutil.rmtree(tmp_root, ignore_errors=True)
```

**Phase 2 extension:** the test fixture writes `Settings(data_dir=str(data_dir.resolve()))` — once the model gains required fields like `backend` (no default in RESEARCH.md's shape; set by first-run detect), the fixture must supply them. Two options:
- Add defaults to `Settings.backend = GpuBackend.CPU` so the fixture doesn't have to specify it (matches `diarization_enabled: bool = False` precedent in `app/models/manifest.py:30`), OR
- Keep `backend` required and update the fixture to write `Settings(data_dir=..., backend=GpuBackend.CPU, ...)`.

**Mock fixtures pattern (NEW for Phase 2):** the conftest gains a section of `@pytest.fixture` functions that return `unittest.mock.MagicMock` configured for `huggingface_hub.hf_hub_download`, `torch.cuda.is_available`, `torch.cuda.mem_get_info`, `faster_whisper.WhisperModel`, `llama_cpp.Llama`, `app.models.vram.probe_vram`. Pattern from `tests/test_create_job.py:71-99` — `from unittest.mock import patch` + `patch.object(jobs_service, "ensure_job_dir", side_effect=OSError(28, "no space"))`. Phase 2 mocks are module-level so all 8 new test files can `from tests.conftest import mock_hf_hub_download` and override per-test.

---

### `tests/test_gpu_detect.py` (new — test, unit)

**Analog:** `tests/test_settings.py` (httpx + monkeypatch + read-back-from-disk assertion).

**Pattern** (`tests/test_settings.py:28-58`):

```python
@pytest.mark.asyncio
async def test_patch_settings_persists(
    client: httpx.AsyncClient,
    tmp_data_dir: Path,
) -> None:
    new_dir = "C:/tmp/x"
    boot_dir = str((tmp_data_dir / "data").resolve())
    resp = await client.patch("/settings", json={"data_dir": new_dir})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_dir"] == boot_dir
    settings_file = tmp_data_dir / "data" / "settings.json"
    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["data_dir"] == boot_dir
    assert payload["pending"]["data_dir"] == new_dir
```

**Phase 2 pattern:** mock `app.models.backend.detect` to return `GpuBackend.CUDA`, mock `app.models.backend.burn_test` to return a fixed `BackendProbe`; trigger a fresh lifespan (or call the same boot path directly); assert `GET /settings` returns the new `backend` and that the on-disk `settings.json` reflects it. Use `monkeypatch.setattr` to swap the module-level functions (mirroring `tests/conftest.py:58,63`).

---

### `tests/test_presets.py` (new — test, unit)

**Analog:** `tests/test_summary_models.py` (pure Pydantic model assertion with no I/O).

**Pattern** (the simplest existing test file is `tests/test_summary_models.py` — small model-construction assertions, no fixtures, no async). Read it directly for the exact shape; the Phase 2 test does the same:

```python
def test_balanced_preset_stt_repo_id():
    from app.models.presets import PRESETS
    from app.models.settings import QualityPreset
    assert PRESETS[QualityPreset.BALANCED].stt.repo_id == "Systran/faster-whisper-large-v3"
```

---

### `tests/test_manager_download.py` (new — test, unit + tmp dir)

**Analog:** `tests/test_atomic_windows_retry.py` (the closest "patch the I/O function, assert the on-disk artifact" test).

**Pattern** (`tests/test_atomic_windows_retry.py` — full file pattern; uses `tmp_path` pytest fixture, patches `os.replace` via `monkeypatch.setattr`, and asserts the on-disk file was written). Phase 2 mirrors this: monkeypatch `huggingface_hub.hf_hub_download` to a fake that writes a known-SHA blob to `target.parent`; call `ModelManager.ensure_downloaded(spec)`; assert the target file exists with the right size and SHA. Resume test sets up a partial file at the target and asserts the second `ensure_downloaded` call does NOT pass `force_download=True`.

**Mocking the I/O boundary** (`tests/test_create_job.py:94-100`):

```python
with patch.object(
    jobs_service, "ensure_job_dir", side_effect=OSError(28, "no space")
):
    with pytest.raises(OSError):
        async with sf() as session:
            await jobs_service.create_job(session, settings)
```

---

### `tests/test_vram_budget.py` (new — test, unit + httpx)

**Analog:** `tests/test_settings.py` (the canonical httpx + `client` fixture + `tmp_data_dir` recipe).

Use the same `client` + `tmp_data_dir` fixture; mock `app.models.vram.probe_vram` via `monkeypatch.setattr(app.models.vram, "probe_vram", lambda *a, **kw: VRAMState(total_mb=8192, used_mb=0, ...))`; assert `POST /models/stt:Systran.../load` returns 200 with the right `vram_mb` when the mock budget is generous, and returns 507 when the mock budget is tight. Mirror the `assert resp.status_code == 422, resp.text` discipline of `tests/test_settings.py:34`.

---

### `tests/test_concurrent_models.py` (new — test, unit + httpx)

**Analog:** `tests/test_settings.py` + `tests/test_settings_restart_required_header.py` (httpx + `monkeypatch.setattr` on the in-memory state).

**State-mutation test pattern** (`tests/test_settings_restart_required_header.py:53-84`):

```python
async def test_data_dir_change_does_not_swap_in_memory(
    client: httpx.AsyncClient, tmp_data_dir: Path
) -> None:
    from app.settings import service as svc
    boot = svc.current().data_dir
    resp = await client.patch("/settings", json={"data_dir": "C:/some/other/path"})
    assert resp.status_code == 200, resp.text
    assert svc.current().data_dir == boot
    assert svc._State.pending is not None
    assert svc._State.pending.data_dir == "C:/some/other/path"
```

**Phase 2 pattern:** first call `await manager.load(ModelCategory.STT)` (mocked to succeed), then `await manager.load(ModelCategory.LLM)` should raise `ConcurrentModelRefused`. With `concurrent_models=True` set via `PATCH /settings {"concurrent_models": true}` (mock `apply_update` to set the value directly on `_State.settings`), the second load succeeds.

**OpenAPI schema assertion pattern** (`tests/test_openapi.py:49-77`):

```python
resp = await client.get("/openapi.json")
data = resp.json()
schemas = data.get("components", {}).get("schemas", {})
for name in ("ManifestPatch", "StageUpdateRequest", ...):
    assert name in schemas, f"{name} missing from components.schemas"
patch_props = set(schemas["ManifestPatch"].get("properties", {}).keys())
for protected in (...):
    assert protected not in patch_props, ...
```

Phase 2 SC-5(c) test mirrors this exactly: assert `concurrent_models: bool` is in `schemas["UpdateSettingsRequest"]["properties"]`.

---

### `tests/test_settings_phase2.py` (new — test, unit + httpx)

**Analog:** `tests/test_data_dir_validation.py` (the canonical "strict Pydantic input + 422 boundary" test).

**Pattern** (`tests/test_data_dir_validation.py:24-48`):

```python
@pytest.mark.asyncio
async def test_data_dir_null_returns_422(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": None})
    assert resp.status_code == 422, resp.text

@pytest.mark.asyncio
async def test_data_dir_relative_returns_422(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": "relative/path"})
    assert resp.status_code == 422, resp.text
```

**Phase 2 pattern:** round-trip the new `Settings` fields via `Settings.model_validate({...})`; PATCH with each new field via `client.patch("/settings", json={field: value})`; PATCH with `backend` and `backend_probe` and assert 422 (the strict `UpdateSettingsRequest` excludes them). Mirror the `assert resp.status_code == 422, resp.text` discipline on every rejection case.

---

### `tests/test_hf_token.py` (new — test, unit + httpx)

**Analog:** `tests/test_settings.py` (httpx + status-code assertions on 200/401/403/422).

Pattern: mock `huggingface_hub.HfApi` (or the HEAD call directly) to return the four states (no token / valid / invalid / gated-terms-not-accepted); assert the response status code + JSON body matches the table in RESEARCH.md §HF Token Gating. Use `monkeypatch.setattr` on the module-level `validate_token` function (or whatever the shim is named).

---

### `tests/test_diagnostics_api.py` (new — test, unit + httpx)

**Analog:** `tests/test_settings.py` (httpx + status-code assertions on 200 / 507 / 409 / 403).

Pattern: mock `probe_vram` + `ModelManager` methods; for each endpoint (`POST /diagnostics/gpu-burn`, `GET /diagnostics/vram`, `GET /models`, `GET /models/{id}/status`), assert the 200 happy path and the 4xx/5xx error paths. Use the `client` fixture as-is.

---

### `pyproject.toml` (extend — config)

**Analog:** self (the existing `dependencies` + `dev` extras structure).

**Pattern** (`pyproject.toml:10-25`):

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.19",
    "aiofiles>=23",
    "python-dateutil>=2.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]
```

**Phase 2 extension:** append `"huggingface_hub>=0.20"` (RESEARCH recommends `>=0.25` to suppress the resume-deprecation warning), `"psutil>=5.9"` to `dependencies`. Do NOT add `faster-whisper`, `llama-cpp-python`, or `pyannote.audio` — those arrive in their own phases (3, 8, 7). Add `"pytest-mock>=3.12"` to `dev` if not already present (RESEARCH says it is, but verify before adding).

---

## Shared Patterns

### Settings service (`app/settings/service.py`)

**Apply to:** all routes that mutate or read `Settings` (`PATCH /settings`, `POST /diagnostics/gpu-burn`, `POST /diagnostics/test-hf-token`).

**Source** (`app/settings/service.py:150-217`):

```python
async def apply_update(patch: UpdateSettingsRequest) -> tuple[Settings, bool]:
    """Apply a PATCH and return (in_memory_settings, restart_required)."""
    existing = current()
    updates = patch.model_dump(exclude_unset=True)
    new = existing.model_copy(update=updates)
    restart_required = (
        "data_dir" in patch.model_fields_set and new.data_dir != existing.data_dir
    )
    target_path = _State.path or _default_settings_path()
    if target_path.exists():
        disk = _read_disk_dict(target_path)
    else:
        disk = {}
    if restart_required:
        disk["data_dir"] = existing.data_dir
        disk[_PENDING_KEY] = new.model_dump()
        await _write_disk_dict(target_path, disk)
        _State.pending = new
        return existing, True
    disk["data_dir"] = new.data_dir
    disk.pop(_PENDING_KEY, None)
    await _write_disk_dict(target_path, disk)
    _State.pending = None
    _State.settings = new
    return new, False
```

**Phase 2 use:** `POST /diagnostics/gpu-burn` calls `apply_update(UpdateSettingsRequest(...))` (with `quality_preset=None`, `hf_token=None`, `concurrent_models=None`, etc. — the only fields it sets are whatever the request model allows; `backend` / `backend_probe` are NOT in `UpdateSettingsRequest` so the detect result is the source of truth and the PATCH only carries user-mutable fields). For a non-restart PATCH the response is `result, False`; for `data_dir`-change PATCHes the response is `existing, True` and the route sets `X-Restart-Required: true`.

### Atomic JSON write (`app/storage/atomic.py:atomic_write_json`)

**Apply to:** every JSON file written to disk — manifest, settings, download state, download progress log.

**Source** (`app/storage/atomic.py:61-64`):

```python
async def atomic_write_json(path: Path, payload: dict) -> None:
    """Write payload as pretty-printed JSON to path atomically."""
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    await atomic_write_bytes(path, encoded)
```

**Phase 2 use:** `ModelManager.ensure_downloaded` writes per-download state via this helper. Do NOT use `Path.write_text` directly — every other module in the codebase goes through `atomic_write_json` and Phase 2 must follow suit.

### In-memory module state (`_State` class with class attributes)

**Apply to:** `ModelManager` singleton, `get_manager()` / `configure_manager(m)` accessors.

**Source** (`app/settings/service.py:44-60`):

```python
class _State:
    """Module-level holder for the in-memory Settings and its path."""
    settings: Settings | None = None
    path: Path | None = None
    pending: Settings | None = None
```

**Phase 2 use:** `app/models/manager.py` declares `_manager: ModelManager | None = None` (no class needed; a module-level var is sufficient since there is no `_State` reset across lifespan runs beyond what `app/main.py:138` does via `configure(None, None)`). The lifespan calls `configure_manager(ModelManager(...))` after the engine is built; routes call `get_manager()` which raises if not configured (mirrors `app/settings/service.py:144-147`).

### HTTPException mapping for typed errors

**Apply to:** all routes that catch custom exception types and return 4xx/5xx with structured bodies.

**Source** (`app/api/routes_jobs.py:148-156`):

```python
try:
    manifest = await update_stage(settings, session, canonical_id, payload.stage, payload.manifest_patch)
except FileNotFoundError as exc:
    raise HTTPException(status_code=404, detail="manifest not found") from exc
except ValidationError as exc:
    raise HTTPException(status_code=422, detail=exc.errors()) from exc
```

**Phase 2 use:** `POST /models/{id}/load` catches `VramBudgetExceeded` -> 507, `ConcurrentModelRefused` -> 409, `ModelGatedError` -> 403, `ModelIntegrityError` -> 500 (or 502). Mirror the `from exc` chain.

### Pydantic v2 strict input + `extra="forbid"`

**Apply to:** every `*Request` model that crosses the API boundary.

**Source** (`app/models/settings.py:40`, `app/models/job.py:37,59,77,86,113`, `app/models/summary.py:25`):

```python
model_config = ConfigDict(strict=True, extra="forbid")
```

**Phase 2 use:** `UpdateSettingsRequest` already has it (extended for Phase 2). New request models in `app/api/routes_models.py` (`DownloadRequest`, `LoadRequest`, `UnloadRequest` if any) MUST use the same config. New `BackendProbe` / `DownloadProgress` / `ModelSpec` / `ModelSet` are response/storage models — use `model_config = ConfigDict(extra="forbid")` (strict=False, the default) to match `Settings` and `JobManifest`.

### Custom error type pattern

**Apply to:** `VramBudgetExceeded`, `ConcurrentModelRefused`, `ModelGatedError`, `ModelIntegrityError` (all in `app/models/manager.py`).

**No Phase 1 precedent** for typed errors; the closest precedent is `FileNotFoundError` caught at the route layer (`app/api/routes_jobs.py:152`). Define a small `class VramBudgetExceeded(Exception): def __init__(self, category, needed_mb, available_mb): ...` family and catch them in the route. Body shape from RESEARCH.md is `{ "error": "gated", "repo": spec.repo_id, "fix": "add HF token in settings" }` — return via `HTTPException(status_code=..., detail=...)` with a `dict` detail (FastAPI serialises it as a JSON object, not a string).

### Test fixture triplet (`tmp_data_dir` + `app_under_test` + `client`)

**Apply to:** all 8 new test files (every test that hits the API).

**Source** (`tests/conftest.py:31-113` — see excerpt above). The 3 fixtures are already in scope for every test in `tests/`; Phase 2 tests just import nothing extra and accept `client: httpx.AsyncClient` + `tmp_data_dir: Path` parameters.

### OpenAPI schema registration

**Apply to:** every new Pydantic model that should appear in `components.schemas` (i.e. every model that crosses the API boundary OR is referenced from a request/response model).

**Source** (`app/main.py:157-197`):

```python
_EXTRA_OPENAPI_MODELS = [
    TranscriptSegment, Transcript, Summary, JobManifest,
    ManifestPatch, StageUpdateRequest, StaleCheckResponse,
]

def _custom_openapi():
    ...
    for model in _EXTRA_OPENAPI_MODELS:
        key = model.__name__
        if key in schemas:
            continue
        schemas[key] = model.model_json_schema(ref_template="#/components/schemas/{model}")
```

**Phase 2 use:** append `BackendProbe`, `DownloadProgress`, `ModelSpec`, `ModelSet`, `QualityPreset` (if declared as `str, Enum` in `app/models/settings.py`, may not need separate schema entry — verify), `GpuBackend`, `ModelCategory`, `LoadedModelInfo` (whatever the load-response type is named).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `app/models/backend.py` (subprocess / wmic calls) | service | event-driven | No subprocess or WMI calls exist in Phase 1; no precedent for `subprocess.run(..., timeout=3)` |
| `app/models/vram.py` (torch.cuda.mem_get_info wrapper) | service | request-response | No `torch` import in Phase 1; no precedent for `torch.cuda` mocking |
| `app/api/routes_models.py` (SSE stream) | route | streaming | No `StreamingResponse` or SSE endpoint in Phase 1; the closest streaming-shape is `app/storage/atomic.py:31-58` (async context manager, not a stream) |
| `app/models/hf_token.py` (HEAD call to HF Hub) | service | request-response | No `huggingface_hub` import in Phase 1; the test-token endpoint is a thin shim with no Phase 1 analog |
| `02-03-SPIKE.md` | docs | n/a | Spike deliverable, no code; no analog needed |

For these, use the RESEARCH.md code-block shapes as the starting point; the planner should consult RESEARCH.md §"Per-backend burn test" for the `torch.cuda` matmul, §"Source of truth per backend" for the VRAM probe table, and §"API Endpoints Added" for the SSE event format.

## Metadata

**Analog search scope:** `app/api/`, `app/models/`, `app/storage/`, `app/jobs/`, `app/settings/`, `app/util/`, `tests/`
**Files scanned:** 33 source + 22 test files
**Pattern extraction date:** 2026-06-15
