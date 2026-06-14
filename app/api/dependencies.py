"""FastAPI dependencies for the current request scope.

The lifespan in :mod:`app.main` calls :func:`configure` to inject the
session factory for the duration of the process; route handlers read
it via :func:`get_session`.

Settings live in :mod:`app.settings.service` (Plan 01-02) - this
module only re-exports :func:`get_settings` as a thin shim so
existing call sites (``settings: Settings = Depends(get_settings)``)
keep working without an import change.
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Settings
from app.settings.service import current as _settings_current

session_factory: async_sessionmaker[AsyncSession] | None = None


def configure(
    session_factory_: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Install the session factory and settings for the request scope.

    ``settings`` is forwarded to :mod:`app.settings.service.configure`
    so the canonical holder of the in-memory settings is that module.
    Passing ``None`` for either argument resets both for a clean
    re-bootstrap (used by the lifespan teardown and the test fixture
    cleanup).
    """
    global session_factory
    session_factory = session_factory_
    if settings is None:
        # Clear the in-memory settings on teardown.
        from app.settings import service as _settings_service

        _settings_service._State.settings = None  # noqa: SLF001
    else:
        from app.settings import service as _settings_service

        _settings_service.configure(settings)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` from the configured session factory."""
    assert session_factory is not None, "session factory not configured"
    async with session_factory() as session:
        yield session


def get_settings() -> Settings:
    """Return the currently-loaded :class:`Settings` instance.

    Delegates to :func:`app.settings.service.current` so the
    canonical holder of the in-memory settings is the service module.
    """
    return _settings_current()
