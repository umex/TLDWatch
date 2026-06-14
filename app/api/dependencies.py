"""FastAPI dependencies for the current request scope.

The lifespan in :mod:`app.main` calls :func:`configure` to inject the
session factory and the loaded :class:`Settings` for the duration of
the process. Route handlers read them via :func:`get_session` and
:func:`get_settings`. This indirection keeps route signatures free of
``Depends(partial(...))`` and means the dependency module is the
single owner of "what is currently loaded into the app".
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Settings

session_factory: async_sessionmaker[AsyncSession] | None = None
current_settings: Settings | None = None


def configure(
    session_factory_: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Install the session factory and settings for the request scope."""
    global session_factory, current_settings
    session_factory = session_factory_
    current_settings = settings


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` from the configured session factory."""
    assert session_factory is not None, "session factory not configured"
    async with session_factory() as session:
        yield session


def get_settings() -> Settings:
    """Return the currently-loaded :class:`Settings` instance."""
    assert current_settings is not None, "settings not configured"
    return current_settings
