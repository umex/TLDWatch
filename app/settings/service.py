"""Settings service: load, save, and PATCH the on-disk settings file.

The settings file is the serialisation of :class:`Settings` (D-14).
The model is the source of truth; the file is a snapshot.

In-memory state is held in a tiny module-level :class:`_State`. The
lifespan in :mod:`app.main` calls :func:`load_settings_from_disk` to
read the bootstrap file, then :func:`configure` to install the
result. Route handlers read the in-memory value via :func:`current`,
and :func:`apply_update` performs a PATCH that persists to disk and
updates the in-memory state only AFTER the disk write succeeds
(Codex HIGH item 16).
"""

from __future__ import annotations

from pathlib import Path

from app.models.settings import Settings, UpdateSettingsRequest
from app.storage.atomic import atomic_write_json
from app.storage.fs import bootstrap_settings_path


class _State:
    """Module-level holder for the in-memory :class:`Settings` and its path.

    Tracking the path lets :func:`apply_update` write back to the
    SAME file that was loaded from, so tests can load from a temp
    path and still see the PATCH land on that file (production loads
    from the bootstrap path and writes back to it; tests that use
    ``load_settings_from_disk(p)`` get the same round-trip).
    """

    settings: Settings | None = None
    path: Path | None = None


def _default_settings_path() -> Path:
    """Return the stable absolute path of the bootstrap settings file."""
    return bootstrap_settings_path()


def load_settings_from_disk(path: Path | None = None) -> Settings:
    """Read and validate the settings file.

    Raises :class:`FileNotFoundError` if the file does not exist. The
    lifespan in :mod:`app.main` is the only caller that handles the
    missing case by writing the bootstrap file first; everything else
    assumes the file is present and parses cleanly.
    """
    target = path or _default_settings_path()
    raw = target.read_text(encoding="utf-8")
    settings = Settings.model_validate_json(raw)
    # Record the path so :func:`apply_update` writes back to the same
    # file (matters for tests that load from a temp path).
    _State.path = target
    return settings


async def save_settings_to_disk(path: Path | None, settings: Settings) -> None:
    """Atomically write ``settings`` to ``path``.

    If ``path`` is ``None``, the in-memory path recorded by
    :func:`load_settings_from_disk` is used; if that is also ``None``,
    the bootstrap path is the final fallback.
    """
    if path is None:
        path = _State.path or _default_settings_path()
    await atomic_write_json(path, settings.model_dump())


def configure(settings: Settings) -> None:
    """Install ``settings`` as the in-memory current value."""
    _State.settings = settings


def current() -> Settings:
    """Return the in-memory current :class:`Settings`.

    Raises :class:`RuntimeError` if the lifespan has not yet installed
    a value (i.e. :func:`configure` was never called).
    """
    if _State.settings is None:
        raise RuntimeError("settings not configured (lifespan not installed)")
    return _State.settings


async def apply_update(patch: UpdateSettingsRequest) -> tuple[Settings, bool]:
    """Apply a PATCH and return ``(new_settings, restart_required)``.

    ``restart_required`` is True when the patch's ``data_dir`` field
    is set AND the new value differs from the current value. A PATCH
    that omits ``data_dir`` (or sets the same value) is not
    restart-required.

    Ordering: build the new model -> write to disk (atomic) -> on
    success update in-memory state. A disk-write failure leaves the
    in-memory state untouched and re-raises.
    """
    existing = current()
    # ``exclude_unset=True`` gives us ONLY the fields the client
    # actually sent; ``model_fields_set`` is the same set on the
    # request model. This lets us distinguish a missing field from a
    # field set to its default value.
    updates = patch.model_dump(exclude_unset=True)
    new = existing.model_copy(update=updates)

    restart_required = (
        "data_dir" in patch.model_fields_set and new.data_dir != existing.data_dir
    )

    await save_settings_to_disk(None, new)
    # In-memory state is updated only AFTER the disk write succeeds.
    _State.settings = new
    return new, restart_required


__all__ = [
    "apply_update",
    "configure",
    "current",
    "load_settings_from_disk",
    "save_settings_to_disk",
]
