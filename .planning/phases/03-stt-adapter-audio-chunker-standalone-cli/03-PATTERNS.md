# Phase 3: STT Adapter + Audio Chunker + Standalone CLI - Pattern Map

**Mapped:** 2026-06-19
**Files analyzed:** 13 (6 new source + 1 modified source + 5 new test + 1 modified test)
**Analogs found:** 11 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/models/stt/__init__.py` | package-init | n/a | `app/models/__init__.py` (+ `app/jobs/__init__.py`) | role-match |
| `app/models/stt/protocol.py` | protocol/model | n/a (declarative) | `app/models/backend.py` (`BackendProvider` Protocol) | exact |
| `app/models/stt/adapter.py` | service | transform (audio→segments) | `app/models/manager.py` (lazy in-body import + boundary) + `app/models/hf_token.py` | exact (lazy-import) + role-match (service) |
| `app/models/stt/chunker.py` | service/transform | streaming (windowed chunks + OOM retry + stitch) | `app/jobs/reconcile.py` (walk + per-item transform + summary) | role-match (orchestrator-style) |
| `app/cli/__init__.py` | package-init | n/a | `app/jobs/__init__.py` | role-match |
| `app/cli/transcribe.py` | controller/CLI | request-response (argv→stdout + file out) | none (no existing CLI) — closest idiom: `app/settings/service.py` `current()` accessor + argparse stdlib | partial (no CLI analog) |
| `pyproject.toml` (modify) | config | n/a | `pyproject.toml` itself (deps block + `[tool.pytest.ini_options]`) | exact (self-edit) |
| `tests/test_stt_adapter.py` | test | unit (mocked seam) | `tests/test_manager_download.py` (mocks lazy import seam) | exact |
| `tests/test_chunker.py` | test | unit (FakeAdapter over Protocol) | `tests/test_concurrent_models.py` (policy unit tests via fixtures) | role-match |
| `tests/test_cli_transcribe.py` | test | unit (argparse + monkeypatched settings) | `tests/test_settings_phase2.py` (settings PATCH via client/monkeypatch) | role-match |
| `tests/test_stt_boundary.py` | test | unit (grep boundary check) | `tests/test_spike_documented.py` (assertion-on-text style) | role-match |
| `tests/_stt_fake.py` | test-helper | n/a (FakeAdapter) | `tests/conftest.py` mock-fixture bodies (`mock_hf_hub_download._default_download`) | role-match |
| `tests/conftest.py` (modify) | test-fixture | n/a | `tests/conftest.py` `mock_hf_hub_download` + `slow_mock_hf_hub_download` fixtures | exact (self-extend) |

## Pattern Assignments

### `app/models/stt/protocol.py` (protocol/model, declarative)

**Analog:** `app/models/backend.py` — `BackendProvider` Protocol (lines 162-179)

The new `STTAdapter` Protocol must mirror the `BackendProvider` shape: a `typing.Protocol` with attribute + method stubs, a module-level docstring explaining the seam, and NO import of the upstream package (`faster_whisper` / `ctranslate2`) at module top. The Protocol module is the contract the chunker + CLI + (Phase 4) orchestrator depend on; the implementation lives in `adapter.py`.

**Protocol shape pattern** (lines 162-179):
```python
class BackendProvider(Protocol):
    """One GPU backend's detection + device-resolution surface.

    ``available()`` is a CHEAP, synchronous, never-raising probe (lazy-import
    its packages; a missing tool is "not present"). ``detect`` iterates
    :data:`BACKENDS` by ``priority`` and returns the first provider whose
    ``available()`` is True. ``burn_test`` runs a real kernel proof.
    ``device_for(engine)`` resolves the device argument for a given inference
    package. ``probe_vram`` is intentionally NOT here (it lives in
    :mod:`app.models.vram` to avoid a circular import — see plan Trade-off B).
    """

    backend: GpuBackend
    priority: int  # lower = tried first by ``detect``

    def available(self) -> bool: ...
    async def burn_test(self) -> BackendProbe: ...
    def device_for(self, engine: InferenceEngine) -> str | int: ...
```

**Apply to `protocol.py`:** declare `class STTAdapter(Protocol)` with `load()`, `transcribe(audio, language=None, vad_filter=True) -> SttTranscription`, `detect_language(audio) -> tuple[str, float]`, `unload()` stubs. Use `from __future__ import annotations` + `from typing import Protocol` (mirrors `backend.py` lines 41-47). Result types `SttTranscription` / `SttSegment` are dataclasses or Pydantic `BaseModel` re-using `app.models.transcript.TranscriptSegment` (see RESEARCH.md Pattern 1 for the exact sketch).

---

### `app/models/stt/adapter.py` (service, transform; the ONLY faster_whisper/ctranslate2 import site)

**Primary analog:** `app/models/manager.py` — lazy in-body `huggingface_hub` import + the documented boundary check.

**Lazy in-body import pattern** (`manager.py` lines 311-315, inside `ensure_downloaded`):
```python
from huggingface_hub import hf_hub_download  # type: ignore[import-not-found]
from huggingface_hub.errors import (  # type: ignore[import-not-found]
    GatedRepoError,
    RepositoryNotFoundError,
)
```

**Documented boundary discipline** (`manager.py` lines 37-39, module docstring):
```
``huggingface_hub`` is imported ONLY inside ``ensure_downloaded`` (the
boundary check ``grep -rE "from huggingface_hub" app/`` matches only
``app/models/manager.py`` and ``app/models/hf_token.py``).
```

**Apply to `adapter.py`:** the module docstring MUST contain the equivalent boundary statement:
```
``faster_whisper`` and ``ctranslate2`` are imported ONLY inside this module
(the boundary check ``grep -rE "from faster_whisper|import faster_whisper|import ctranslate2" app/``
matches only ``app/models/stt/adapter.py`` — SC-4, mirrors the Phase 2
``huggingface_hub`` boundary in ``app/models/manager.py``).
```
Inside `FasterWhisperAdapter.load()`:
```python
from faster_whisper import WhisperModel  # type: ignore[import-not-found]  # lazy in-body
import ctranslate2                                     # type: ignore[import-not-found]
self._model = WhisperModel(self._model_path, device=self._device,
                           compute_type=self._compute_type)
# D-08 int8 verification — see RESEARCH.md Pattern 2 for the _ACCEPTED table.
actual = self._model.model.compute_type
if actual not in _ACCEPTED[self._compute_type]:
    raise RuntimeError(...)
```

**Secondary analog (typed error hierarchy + module-level singleton):** `app/models/manager.py` lines 65-133 (`ModelManagerError` / `VramBudgetExceeded` / `ModelGatedError`) + lines 549-564 (`_manager` singleton + `get_manager()` / `configure_manager()`). If the adapter needs a typed error (e.g. `SttInt8VerificationError`), mirror this hierarchy; if it needs a process-wide adapter singleton, mirror `get_manager()`/`configure_manager()` (the `RuntimeError("... not configured (lifespan not installed)")` guard).

**Tertiary analog (lazy import + module-level seam for tests):** `app/models/hf_token.py` lines 41-51 (`_hf_hub_url` thin alias with lazy `from huggingface_hub import hf_hub_url` inside the body, declared at module scope "so tests can `monkeypatch.setattr`"). If `adapter.py` exposes any seam tests must patch (e.g. a `_load_whisper_model` factory), declare it at module scope with the lazy import inside, mirroring this idiom.

**Service init/dependency-injection pattern** (`manager.py` lines 227-234):
```python
def __init__(
    self,
    settings: Settings,
    settings_factory: Callable[[], Settings] | None = None,
) -> None:
    self._settings = settings
    self._state = ManagerState()
    self._settings_factory = settings_factory or (lambda: current())
```
**Apply:** `FasterWhisperAdapter.__init__(self, model_path: str, device: str, compute_type: str)` — receive already-resolved values (device from `device_for`, model_path from `ModelManager.ensure_downloaded`); the adapter does NOT call `current()` or `device_for` itself (keeps it a pure transform the chunker/CLI can compose).

---

### `app/models/stt/chunker.py` (service/transform, streaming — windowed chunks + OOM retry + stitch)

**Analog:** `app/jobs/reconcile.py` — orchestrator-style "walk items → per-item transform → collect summary" (lines 48-70).

**Orchestrator shape pattern** (`reconcile.py` lines 48-70):
```python
async def reconcile_all(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Walk every per-job folder and UPDATE drifted DB rows.
    ...
    """
    jobs_root = data_dir(settings) / "jobs"
    if not jobs_root.is_dir():
        _log.info("reconcile: jobs root %s missing; nothing to do", jobs_root)
        return {"scanned": 0, "updated": 0, "missing_manifests": []}

    summary: dict[str, Any] = {
```
**Apply to `chunker.py`:** `transcribe_file(path, preset, device, compute_type, language) -> Transcript` follows the same shape — early-return/fast-path for the ≤30 min single-call case (mirrors the "jobs root missing; nothing to do" guard), then the per-chunk loop with OOM halve-and-retry (RESEARCH.md Pattern 3), then stitch (RESEARCH.md Pattern 4), then return the assembled `Transcript`. Module-level `_log = logging.getLogger(__name__)` + structured INFO line on success mirrors `manager.py` lines 474-489 (the `json.dumps({"event": "model_loaded", ...})` SC-2 log).

**Imports pattern** (`reconcile.py` lines 31-43):
```python
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.manifest import _latest_ts, read_manifest, stage_to_status
from app.models.settings import Settings
from app.storage.fs import data_dir
```
**Apply to `chunker.py`:** `from __future__ import annotations` first; `import logging` + `import re` (for the OOM regex); NO `faster_whisper`/`ctranslate2`/`numpy`-as-top-level-GPU import — numpy may be imported at top (it is a transitive dep but pure-Python at import time; if the planner wants zero-risk they can lazy-import it inside `transcribe_file` like `manager.py` does for `huggingface_hub`). Import the `STTAdapter` Protocol from `app.models.stt.protocol` (the contract), `Transcript`/`TranscriptSegment` from `app.models.transcript`, `get_spec`/`get_category` from `app.models.registry`, `ModelCategory` from `app.models.diagnostics`.

**Error handling pattern:** the chunker catches `RuntimeError` per chunk, matches `"out of memory"` (case-insensitive) before treating as OOM, halves the chunk, retries down to a ~60 s floor, and re-raises everything else (RESEARCH.md Pattern 3 + Pitfall 5). This mirrors `manager.py`'s typed-exception filtering (`GatedRepoError` → `ModelGatedError`, `RepositoryNotFoundError` → `ModelManagerError`, lines 362-367) — catch a specific shape, re-raise the rest.

---

### `app/cli/transcribe.py` (controller/CLI, request-response — argv→stdout + atomic file out)

**No existing CLI in the codebase** (`app/cli/` does not exist; confirmed via `ls`). Closest idiom for the settings read is `app/settings/service.py` `current()`.

**Settings accessor pattern** (`app/settings/service.py` lines 139-147):
```python
def current() -> Settings:
    """Return the in-memory current :class:`Settings`.

    Raises :class:`RuntimeError` if the lifespan has not yet installed
    a value (i.e. :func:`configure` was never called).
    """
    if _State.settings is None:
        raise RuntimeError("settings not configured (lifespan not installed)")
    return _State.settings
```
**Apply to the CLI's `--device auto` path:** `settings = current(); device = device_for(settings.backend, InferenceEngine.FASTER_WHISPER)`. The CLI is a standalone entry point (no FastAPI lifespan), so the planner MUST decide how settings get configured for the CLI — either (a) call `load_settings_from_disk()` at CLI startup (mirrors `app/main.py` lifespan), or (b) read the bootstrap settings file directly via `app.storage.fs.bootstrap_settings_path()` + `Settings.model_validate_json(...)`. This is a planner decision (the RESEARCH.md Code Examples sketch calls `current()` without showing the bootstrap — flag this gap).

**Atomic write pattern** (`app/storage/atomic.py` lines 61-64):
```python
async def atomic_write_json(path: Path, payload: dict) -> None:
    """Write ``payload`` as pretty-printed JSON to ``path`` atomically."""
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    await atomic_write_bytes(path, encoded)
```
**Apply to the CLI's `--out` step:** `await atomic_write_json(out_path, transcript.model_dump())`. `atomic_write_json` is `async`, so the CLI wraps it in `asyncio.run(...)` (RESEARCH.md Code Examples line 486 sketches this). `model_dump()` is the Pydantic v2 serializer used throughout (`settings/service.py` line 131, `manager.py` line 475).

**Imports pattern (mirror project conventions):** `from __future__ import annotations` first; `import argparse`, `import asyncio`, `import sys`, `from pathlib import Path`; project-absolute imports (`from app.models.backend import device_for`, `from app.models.diagnostics import InferenceEngine`, `from app.models.stt import FasterWhisperAdapter`, `from app.models.stt.chunker import transcribe_file`, `from app.models.transcript import Transcript`, `from app.settings.service import current`, `from app.storage.atomic import atomic_write_json`). The CLI MUST NOT import `faster_whisper` / `ctranslate2` (SC-4 boundary).

**Argparse shape:** RESEARCH.md Code Examples lines 454-490 provides the exact sketch (`ArgumentParser(prog="transcribe")`, positional `file`, `--preset/--device/--language/--compute-type/--out/--verbose`, `main() -> int` returning 0). The `main` function is the `[project.scripts]` entry point target.

---

### `app/models/stt/__init__.py` + `app/cli/__init__.py` (package-init)

**Analog:** `app/jobs/__init__.py` (package-init convention — minimal, no heavy imports at package top to avoid triggering the boundary).

**Apply:** `app/models/stt/__init__.py` re-exports `STTAdapter`, `SttTranscription`, `SttSegment` (from `.protocol`), `FasterWhisperAdapter` (from `.adapter`), and `transcribe_file` (from `.chunker`) via `__all__`. IMPORTANT: importing `FasterWhisperAdapter` from the package top will trigger `adapter.py`'s module load — but `adapter.py` has NO top-level `faster_whisper` import (lazy in-body), so this is safe in a CPU-only env. Confirm this by mirroring `manager.py`'s discipline (top-level imports are stdlib + project-internal only; the upstream package import is inside the method body).

---

### `pyproject.toml` (modify — config)

**Analog:** `pyproject.toml` itself (self-edit). Existing structure:

**Dependencies block** (lines 10-26):
```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.19",
    "aiofiles>=23",
    "python-dateutil>=2.8",
    # Phase 2: HF token shim + VRAM probe + HTTP client. Promoted from
    # dev to main so production installs get them. NO faster-whisper,
    # llama-cpp-python, pyannote.audio, or torch — those arrive in
    # their own phases (3, 8, 7) per RESEARCH Environment Availability
    # and the CONTEXT domain boundary.
    "huggingface_hub>=0.25",
    "psutil>=5.9",
    "httpx>=0.27",
]
```
**Apply:** add a Phase 3 comment block + the pinned pair, mirroring the Phase 2 comment style:
```toml
    # Phase 3: STT inference (faster-whisper + CTranslate2). Pinned to the
    # verified-compatible pair (RESEARCH.md Standard Stack). Imported ONLY
    # inside app/models/stt/adapter.py (SC-4 boundary).
    "faster-whisper==1.2.1",
    "ctranslate2==4.7.2",
    # CUDA 12.x runtime libs for the laptop (CT2 win_amd64 wheel bundles cuDNN
    # but NOT cublas/cudart — RESEARCH.md Pitfall 1 / Open Q1). Conditional /
    # checkpoint:human-verify before adding.
    # "nvidia-cublas-cu12",
    # "nvidia-cuda-runtime-cu12",
```

**`[project.scripts]` is ABSENT today** — the planner adds it after the `[project]` table (before `[project.optional-dependencies]`), mirroring the sketch in RESEARCH.md Code Examples line 451:
```toml
[project.scripts]
transcribe = "app.cli.transcribe:main"
```

**Existing pytest config** (lines 40-42) stays unchanged — `asyncio_mode = "auto"` + `testpaths = ["tests"]` already covers the new test files.

---

### `tests/test_stt_adapter.py` (test, unit — mocked lazy import seam)

**Analog:** `tests/test_manager_download.py` — builds the unit under test directly, invokes it, asserts on the side effect, uses the `mock_hf_hub_download` fixture (which patches the lazy import seam).

**Test-file structure pattern** (`tests/test_manager_download.py` lines 22-60):
```python
"""Tests for ``ModelManager.ensure_downloaded`` (SC-3, Pitfall 4, D-01).

Four tests:
...
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.models.diagnostics import GpuBackend, ModelCategory, ModelSpec
from app.models.manager import (
    ModelGatedError,
    ModelIntegrityError,
    ModelManager,
)
from app.models.registry import REGISTRY
from app.models.settings import Settings
from app.storage.models_dir import spec_file_path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        backend=GpuBackend.CUDA,
    )


@pytest.mark.asyncio
async def test_ensure_downloaded_size_and_sha(
    tmp_path: Path, mock_hf_hub_download
) -> None:
    """SC-3: download writes the file at the expected path with the right size."""
```
**Apply to `test_stt_adapter.py`:** module docstring listing the test cases (REQ INGEST-06, TRANS-01, D-08); `from __future__ import annotations`; `import pytest`; project imports (`from app.models.stt.adapter import FasterWhisperAdapter`, `from app.models.transcript import TranscriptSegment`); a `mock_stt_adapter` fixture usage (added to `conftest.py` — see below); `@pytest.mark.asyncio` if any path is async (the adapter's `load()`/`transcribe()` are sync per RESEARCH.md, so tests are likely plain `def`). The int8-verification test mocks `self._model.model.compute_type` to return `"float32"` and asserts `pytest.raises(RuntimeError)`.

---

### `tests/test_chunker.py` (test, unit — FakeAdapter over Protocol)

**Analog:** `tests/test_concurrent_models.py` — policy unit tests that exercise a unit via fixtures, no real GPU/network.

**Imports pattern** (`tests/test_concurrent_models.py` lines 19-23):
```python
from __future__ import annotations

import httpx
import pytest

from app.models.diagnostics import GpuBackend, VRAMState
```
**Apply to `test_chunker.py`:** `import pytest`; `from app.models.stt.chunker import transcribe_file` (or the per-chunk helper); `from tests._stt_fake import FakeAdapter` (the shared fake); build the chunker with a `FakeAdapter` that yields deterministic `SttTranscription`s, then assert stitch offsets + overlap-trim midpoint (RESEARCH.md Pattern 4). For the OOM test, the `FakeAdapter`'s `transcribe` raises `RuntimeError("CUDA failed with error out of memory")` on demand; assert the chunker halves and retries down to the floor.

---

### `tests/test_cli_transcribe.py` (test, unit — argparse + monkeypatched settings)

**Analog:** `tests/test_settings_phase2.py` (settings PATCH via monkeypatched client — the closest existing "exercise a settings-reading entry point" test).

**Apply to `test_cli_transcribe.py`:** use `monkeypatch.setattr` on `app.settings.service.current` (or `app.cli.transcribe.current`) to return a `Settings(backend=GpuBackend.CUDA)` vs `GpuBackend.CPU` and assert `device_for` is called with the right `InferenceEngine.FASTER_WHISPER` (SC-5 test). Invoke `main()` via `sys.argv` patching (`monkeypatch.setattr(sys, "argv", ["transcribe", str(file), ...])`) and assert the atomic-written `transcript.json` + stdout summary. Mock `transcribe_file` to avoid running the real pipeline.

---

### `tests/test_stt_boundary.py` (test, unit — grep boundary check)

**Analog:** `tests/test_spike_documented.py` (assertion-on-text style — closest existing "grep the tree and assert" test).

**Apply to `test_stt_boundary.py`:** run `subprocess.run(["git", "grep", "-lE", r"from faster_whisper|import faster_whisper|import ctranslate2", "--", "app/"])` (or Python `pathlib` walk + `re`), collect matching files, and `assert matching == ["app/models/stt/adapter.py"]`. This is the SC-4 automated gate (RESEARCH.md Validation Architecture row SC-4).

---

### `tests/_stt_fake.py` (test-helper — FakeAdapter)

**Analog:** `tests/conftest.py` `mock_hf_hub_download._default_download` body (lines 246-261) — a self-contained fake that satisfies the contract without the real package.

**Apply to `tests/_stt_fake.py`:** declare `class FakeAdapter` implementing `STTAdapter` Protocol with: deterministic `transcribe(audio, language, vad_filter)` returning a `SttTranscription` with controllable segments; `oom_on_call: int | None` attribute that makes `transcribe` raise `RuntimeError("CUDA failed with error out of memory")` on the Nth call; `detect_language(audio)` returning `("en", 0.99)`. This is exactly why the Protocol exists (D-06) — the chunker + CLI tests depend on the Protocol, never the package.

---

### `tests/conftest.py` (modify — add `mock_stt_adapter` + `fake_audio_array` fixtures)

**Analog:** `tests/conftest.py` `mock_hf_hub_download` (lines 229-265) + `slow_mock_hf_hub_download` (lines 268-351).

**Mock-fixture pattern** (`conftest.py` lines 229-265):
```python
@pytest.fixture
def mock_hf_hub_download(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the manager's lazy ``hf_hub_download`` seam with a MagicMock.

    The manager lazy-imports ``huggingface_hub.hf_hub_download`` inside
    ``ensure_downloaded``. This fixture ensures ``huggingface_hub`` is
    imported (it is a real dependency per pyproject) and patches the
    ``hf_hub_download`` attribute on the real module so the manager's
    ``from huggingface_hub import hf_hub_download`` resolves to the
    mock. ...
    """
    import huggingface_hub  # type: ignore[import-not-found]
    from app.models.registry import REGISTRY

    def _default_download(*, repo_id, filename, revision, local_dir, token):
        ...
    mock = MagicMock(side_effect=_default_download)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", mock)
    return mock
```
**Apply to `mock_stt_adapter`:** mirror the structure — `@pytest.fixture`, `monkeypatch` arg, import the real `faster_whisper` module (it is a real dep per the new pyproject), `monkeypatch.setattr(faster_whisper, "WhisperModel", mock_whisper_model_class)`. The mock `WhisperModel` class's `__init__` records `device`/`compute_type`, exposes `self.model = SimpleNamespace(compute_type=...)` (so the D-08 verification reads it), and `transcribe(...)` returns `(iter([Segment(...)]), TranscriptionInfo(...))`. Tests override `compute_type` per-case (the int8-verification test sets it to `"float32"` to trigger the fail-loud path). See RESEARCH.md Validation Architecture "Test-seam guidance" — the two options are (a) patch the attribute on the real `faster_whisper` module after forcing its import, or (b) patch `sys.modules["faster_whisper"]` with a `MagicMock` BEFORE the adapter imports it. Prefer (a) to mirror `mock_hf_hub_download` exactly.

**Apply to `fake_audio_array`:** a small `numpy.ndarray` (e.g. `numpy.zeros(16000 * 30, dtype="float32")` — 30 s of silence at 16 kHz) for chunker tests that slice the array. If the planner wants zero numpy-at-import-time risk in the test env, lazy-import numpy inside the fixture body (mirrors the lazy-import discipline).

**Other reusable fixtures already in conftest.py** (no re-creation needed): `tmp_data_dir`, `mock_probe_vram`, `configured_model_manager`. The adapter tests that exercise `ModelManager.ensure_downloaded` can pull `mock_hf_hub_download` + `configured_model_manager` directly.

---

## Shared Patterns

### Lazy in-body import + package boundary (the Phase 2 discipline, mirrored for Phase 3)
**Source:** `app/models/manager.py` lines 37-39 (docstring boundary statement) + lines 311-315 (lazy `from huggingface_hub import ...` inside the method body); `app/models/hf_token.py` lines 41-51 (module-scope seam with lazy import inside the body, for `monkeypatch.setattr`).
**Apply to:** `app/models/stt/adapter.py` (the ONLY `faster_whisper`/`ctranslate2` import site — SC-4). The `protocol.py`, `chunker.py`, `__init__.py`, and `app/cli/transcribe.py` modules MUST NOT import those packages.
```python
# inside adapter.py's FasterWhisperAdapter.load():
from faster_whisper import WhisperModel  # type: ignore[import-not-found]
import ctranslate2                        # type: ignore[import-not-found]
```

### Device resolution seam (the Phase 2 seam Phase 3 calls)
**Source:** `app/models/backend.py` `device_for` (lines 436-447) + `BackendProvider.device_for` per-engine dispatch (lines 278-281, 309-312, 368-371).
**Apply to:** `app/cli/transcribe.py` (`--device auto` path) and `app/models/stt/adapter.py` (the adapter receives the resolved device, does NOT call `device_for` itself).
```python
# backend.py lines 436-447:
def device_for(backend: GpuBackend, engine: InferenceEngine) -> str | int:
    provider = _provider_for(backend)
    if provider is None:
        return -1 if engine == InferenceEngine.LLAMA_CPP else "cpu"
    return provider.device_for(engine)
```
CLI usage: `device_for(settings.backend, InferenceEngine.FASTER_WHISPER)` → `"cuda"` on CUDA, `"cpu"` on CPU.

### Atomic write (Phase 1 D-04)
**Source:** `app/storage/atomic.py` `atomic_write_json` (lines 61-64) — async, pretty-printed, `os.replace` via `retry_windows`.
**Apply to:** `app/cli/transcribe.py`'s `--out` step (writes `<input>.transcript.json`).
```python
async def atomic_write_json(path: Path, payload: dict) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    await atomic_write_bytes(path, encoded)
```

### Output schema (Phase 1 D-15 lax-output)
**Source:** `app/models/transcript.py` lines 16-44 — `TranscriptSegment(start_s, end_s, text, speaker=None, confidence=None)` + `Transcript(schema_version=1, job_id, language=None, segments=[])`.
**Apply to:** the adapter's `SttTranscription` → `Transcript` mapping. The adapter fills `start_s`/`end_s`/`text`/`confidence` and leaves `speaker=None` (Phase 7 diarization fills it). `confidence = math.exp(seg.avg_logprob)` per RESEARCH.md A5. The `Transcript.job_id` field is REQUIRED — the CLI must supply something (e.g. the input filename stem or a generated id); the planner decides the value (the CLI does NOT create a `data/jobs/<id>/` dir per D-03, so `job_id` is a logical label, not a filesystem path).

### Spec resolution (Phase 2 registry)
**Source:** `app/models/registry.py` `get_spec` (lines 116-128) + the STT specs (lines 32-41 `_BALANCED_STT` → `Systran/faster-whisper-large-v3`, lines 62-71 `_SMALL_STT` → `Systran/faster-whisper-small`, line 101 `"large.stt": _BALANCED_STT`).
**Apply to:** `app/cli/transcribe.py` resolves `--preset` → `"balanced.stt"` / `"small.stt"` / `"large.stt"`, calls `get_spec(f"{preset}.stt")` + `get_category(...)`, then `ModelManager.ensure_downloaded(spec, ModelCategory.STT)` to get the on-disk model path handed to the adapter.
```python
# registry.py lines 116-128:
def get_spec(id: str) -> ModelSpec:
    try:
        return REGISTRY[id]
    except KeyError as exc:
        raise KeyError(
            f"unknown model id: {id!r}; available: {sorted(REGISTRY.keys())}"
        ) from exc
```

### Settings accessor (Phase 1/2)
**Source:** `app/settings/service.py` `current()` (lines 139-147) — `RuntimeError` if the lifespan never installed a value.
**Apply to:** `app/cli/transcribe.py` — BUT the CLI is a standalone entry point with no FastAPI lifespan, so the planner MUST add a CLI-side bootstrap step (`load_settings_from_disk()` or a direct `bootstrap_settings_path()` read) before calling `current()`. Flag this as a planner decision (the RESEARCH.md sketch calls `current()` without showing the bootstrap).

### Test-seam mocking (lazy-import patch)
**Source:** `tests/conftest.py` `mock_hf_hub_download` (lines 229-265) — imports the real upstream module, `monkeypatch.setattr` the attribute the SUT lazy-imports.
**Apply to:** the new `mock_stt_adapter` fixture (patches `faster_whisper.WhisperModel` so `adapter.py`'s `from faster_whisper import WhisperModel` resolves to the mock). Also the pattern for any `ctranslate2.get_supported_compute_types` patching the int8-verification test needs.

### Structured logging (SC-2-style)
**Source:** `app/models/manager.py` lines 474-489 — `_log.info(json.dumps({"event": "model_loaded", ...}, sort_keys=True))`.
**Apply to:** the adapter's `load()` (log `compute_type` requested vs loaded + `get_supported_compute_types` result) and the chunker's per-chunk progress (log chunk index, size, OOM-retry events). Module-level `_log = logging.getLogger(__name__)` in every new source file.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `app/cli/transcribe.py` | controller/CLI | request-response (argv→stdout + file out) | No existing CLI in the codebase (`app/cli/` does not exist). The planner should follow RESEARCH.md Code Examples lines 454-490 (the argparse sketch) + the `current()` settings-accessor pattern + the `atomic_write_json` output pattern. The CLI-side settings bootstrap (no lifespan) is an open planner decision. |
| `tests/test_stt_boundary.py` | test (grep boundary) | unit | No existing "grep the source tree and assert" test; `tests/test_spike_documented.py` is the closest text-assertion test but uses a different mechanism. RESEARCH.md Validation Architecture row SC-4 specifies the exact `grep -rE` command. |

## Metadata

**Analog search scope:** `app/` (all subdirs), `tests/` (all), `pyproject.toml`. Confirmed `app/cli/` and `app/models/stt/` do NOT yet exist (`ls` verified).
**Files scanned:** 11 analog files read in full (`manager.py`, `backend.py`, `atomic.py`, `transcript.py`, `registry.py`, `settings/service.py`, `diagnostics.py`, `hf_token.py`, `storage/models_dir.py`, `conftest.py`, `pyproject.toml`) + 2 test files sampled (`test_manager_download.py`, `test_concurrent_models.py`) + 1 orchestrator file sampled (`app/jobs/reconcile.py`).
**Pattern extraction date:** 2026-06-19