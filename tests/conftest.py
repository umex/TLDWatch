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
from typing import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio

from app.api.dependencies import configure
from app.main import app
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
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        Settings(data_dir=str(data_dir.resolve())).model_dump_json(),
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
