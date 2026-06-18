"""Test fixtures: isolated temp data dir + a wired-up FastAPI app under test.

Each test gets:

- A freshly-created temp directory used as the project root
- A ``data/settings.json`` written with an ABSOLUTE ``data_dir`` value
  so the test does not depend on the process cwd
- The FastAPI lifespan driven manually so the engine, session
  factory, and settings are installed for the test
- An :class:`httpx.AsyncClient` bound to the app via
  :class:`httpx.ASGITransport`
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from app.api.dependencies import configure
from app.main import app
from app.models.diagnostics import BackendProbe, GpuBackend, VRAMState
from app.models.settings import Settings
from app.storage.fs import bootstrap_settings_path


@pytest.fixture
def tmp_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a temp project root with a valid ``data/settings.json``.

    The bootstrap path is overridden to point inside the temp dir via
    :func:`app.storage.fs.bootstrap_settings_path`. We use
    :func:`monkeypatch.setattr` on the module so the change only
    affects this test, and we patch the module attribute used by
    ``app.main.lifespan`` to read it.
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="tan-test-"))
    data_dir = tmp_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write the bootstrap settings file inside the temp project root.
    # The file is the serialisation of the :class:`Settings` Pydantic
    # model; ``data_dir`` is the ABSOLUTE path of the data dir.
    # Phase 2: the model now has a required ``backend`` field (D-08);
    # the fixture writes a Phase 2-shaped file with ``backend=CPU`` and
    # all the new field defaults so the lifespan does NOT re-run the
    # first-boot detect on every test boot.
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        Settings(
            data_dir=str(data_dir.resolve()),
            backend=GpuBackend.CPU,
        ).model_dump_json(),
        encoding="utf-8",
    )

    # The lifespan reads bootstrap_settings_path() directly. Patch the
    # module attribute to return our test path.
    from app.storage import fs as fs_module

    monkeypatch.setattr(fs_module, "bootstrap_settings_path", lambda: settings_path)
    # The lifespan also imports the function by name; patch the
    # alias in app.main too.
    from app import main as main_module

    monkeypatch.setattr(main_module, "bootstrap_settings_path", lambda: settings_path)

    try:
        yield tmp_root
    finally:
        # Make sure the lifespan fully tears down before we delete the
        # temp dir, otherwise SQLite may still hold a handle.
        configure(None, None)  # type: ignore[arg-type]
        # Best-effort cleanup; on Windows antivirus may briefly hold
        # the files, so we ignore errors and let the OS clean up.
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


@pytest_asyncio.fixture
async def app_under_test(tmp_data_dir: Path) -> AsyncIterator[object]:
    """Drive the FastAPI lifespan manually for the test app."""
    # Use the ASGI lifespan protocol via httpx's client below; we
    # also need to call the lifespan body directly so ``configure``
    # is invoked. The cleanest way is to drive the lifespan context
    # manager manually here.
    from contextlib import asynccontextmanager

    # Import the lifespan from app.main and run it as a context
    # manager around the test. The app instance is the module-level
    # ``app`` - re-using it is fine because each test gets a fresh
    # engine + session factory and ``configure`` resets state.
    @asynccontextmanager
    async def _lifespan_context():
        # Run the real lifespan body by stepping into the generator.
        agen = app.router.lifespan_context(app)
        await agen.__aenter__()
        try:
            yield
        finally:
            await agen.__aexit__(None, None, None)

    async with _lifespan_context():
        yield app


@pytest_asyncio.fixture
async def client(app_under_test: object) -> AsyncIterator[httpx.AsyncClient]:
    """An :class:`httpx.AsyncClient` bound to the test app via ASGI."""
    transport = httpx.ASGITransport(app=app_under_test)
    # Use ``http://localhost`` as the base URL so the request Host
    # header is on the TrustedHostMiddleware allow-list.
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        yield ac


# --- Phase 2 mock fixtures (Plan 02-01 Task 3) ---------------------------
#
# Each fixture patches a module-level seam via ``monkeypatch.setattr``
# so the mock is auto-undone at end-of-test. Tests override the
# ``return_value`` / ``side_effect`` per-case.


@pytest.fixture
def mock_backend_detect(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch ``app.models.backend.detect`` + ``burn_test`` with AsyncMocks.

    Default: ``detect`` returns ``GpuBackend.CPU``; ``burn_test`` returns
    a CPU-shaped :class:`BackendProbe` (``burn_test_ms=None``,
    ``vram_total_mb=None``, ``device_name="CPU"``). Tests override the
    ``return_value`` per-case, e.g.
    ``mock_backend_detect.detect.return_value = GpuBackend.CUDA``.

    Returns a :class:`types.SimpleNamespace` with ``detect`` and
    ``burn_test`` attributes pointing at the AsyncMocks so tests can
    also assert call counts (``mock_backend_detect.detect.assert_not_called()``).
    """
    from app.models import backend as backend_module

    detect_mock = AsyncMock(return_value=GpuBackend.CPU)
    burn_mock = AsyncMock(
        return_value=BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            burn_test_ms=None,
            vram_total_mb=None,
            notes="no GPU detected; running in CPU mode",
        )
    )
    monkeypatch.setattr(backend_module, "detect", detect_mock)
    monkeypatch.setattr(backend_module, "burn_test", burn_mock)
    return SimpleNamespace(detect=detect_mock, burn_test=burn_mock)


@pytest.fixture
def mock_hf_hub_url(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch ``app.models.hf_token._head`` + ``_hf_hub_url``.

    Default: ``_head`` returns ``(401, {})`` (token invalid). Tests
    override the ``return_value`` per-case, e.g.
    ``mock_hf_hub_url.return_value = (200, {"x-repo-author": "alice"})``,
    or set ``side_effect = httpx.ConnectError(...)`` to simulate a
    network error (Pitfall 3).

    Returns the ``_head`` AsyncMock so tests can configure it
    directly. ``_hf_hub_url`` is replaced with a deterministic lambda
    so the test does not need ``huggingface_hub`` installed.
    """
    from app.models import hf_token as hf_module

    head_mock = AsyncMock(return_value=(401, {}))
    monkeypatch.setattr(hf_module, "_head", head_mock)
    monkeypatch.setattr(
        hf_module,
        "_hf_hub_url",
        lambda repo_id, filename: (
            f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        ),
    )
    return head_mock


@pytest.fixture
def mock_probe_vram(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``app.api.routes_diagnostics.probe_vram`` with a MagicMock.

    Default: returns a zeroed :class:`VRAMState` with
    ``backend=GpuBackend.CPU`` and ``loaded=[]``. Tests override the
    ``return_value`` per-case. The patch targets the route module's
    bound reference (``from app.models.vram import probe_vram``) so
    the mock is seen by ``GET /diagnostics/vram``.
    """
    from app.api import routes_diagnostics as routes_module

    mock = MagicMock(
        return_value=VRAMState(
            backend=GpuBackend.CPU,
            total_mb=0,
            available_mb=0,
            used_mb=0,
            loaded=[],
        )
    )
    monkeypatch.setattr(routes_module, "probe_vram", mock)
    return mock
