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

Restart-only ``data_dir`` semantics (Plan 01-04 H1):

A PATCH that changes ``data_dir`` does NOT swap the in-memory
``_State.settings`` value. Instead the new value is written to disk
under the sibling key ``pending`` (the active ``data_dir`` is
unchanged) and stored in ``_State.pending``. The response header
``X-Restart-Required: true`` signals the caller that a restart is
needed before the change takes effect.

On boot, the lifespan calls :func:`apply_pending` after loading the
disk file; that helper installs the pending value as the in-memory
current and rewrites the disk file without the ``pending`` key.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models.settings import Settings, UpdateSettingsRequest
from app.storage.atomic import atomic_write_json
from app.storage.fs import bootstrap_settings_path

# The sibling key in the on-disk settings JSON that carries a pending
# restart-required change. It is the ONLY string literal used by the
# disk-dict layer; the Pydantic :class:`Settings` model does not
# include it.
_PENDING_KEY = "pending"


class _State:
    """Module-level holder for the in-memory :class:`Settings` and its path.

    Tracking the path lets :func:`apply_update` write back to the
    SAME file that was loaded from, so tests can load from a temp
    path and still see the PATCH land on that file (production loads
    from the bootstrap path and writes back to it; tests that use
    ``load_settings_from_disk(p)`` get the same round-trip).

    ``pending`` carries any deferred-on-restart change that was
    persisted to disk but not yet installed as the in-memory current.
    It is ``None`` whenever no such change exists.
    """

    settings: Settings | None = None
    path: Path | None = None
    pending: Settings | None = None


def _default_settings_path() -> Path:
    """Return the stable absolute path of the bootstrap settings file."""
    return bootstrap_settings_path()


def _read_disk_dict(path: Path) -> dict:
    """Return the raw on-disk settings dict (no Pydantic validation).

    The on-disk format is ``{"data_dir": str, "pending": dict | None}``
    where the ``pending`` key is OPTIONAL and only present when a
    restart-required change has been queued by :func:`apply_update`.
    Returns an empty dict if the file does not exist; the caller
    handles the missing-file path.
    """
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


async def _write_disk_dict(path: Path, payload: dict) -> None:
    """Atomically write ``payload`` (a raw dict, including any pending key)."""
    await atomic_write_json(path, payload)


def load_settings_from_disk(path: Path | None = None) -> tuple[Settings, Settings | None]:
    """Read and validate the settings file.

    Returns ``(active_settings, pending_settings_or_none)``. The active
    settings are the in-memory current value; the pending value (if
    any) is what the lifespan should install via :func:`apply_pending`
    after the engine/session factory are built.

    Raises :class:`FileNotFoundError` if the file does not exist. The
    lifespan in :mod:`app.main` is the only caller that handles the
    missing case by writing the bootstrap file first; everything else
    assumes the file is present and parses cleanly.
    """
    target = path or _default_settings_path()
    raw_dict = _read_disk_dict(target)

    pending_dict = raw_dict.get(_PENDING_KEY)
    pending: Settings | None = None
    if pending_dict is not None:
        pending = Settings.model_validate(pending_dict)

    # The active settings are the raw dict MINUS the pending key
    # (Settings has ``extra="forbid"`` so we cannot pass ``pending``
    # through). Build a clean dict for validation.
    active_dict = {k: v for k, v in raw_dict.items() if k != _PENDING_KEY}
    active = Settings.model_validate(active_dict)

    # Record the path so :func:`apply_update` writes back to the same
    # file (matters for tests that load from a temp path).
    _State.path = target
    _State.pending = pending
    return active, pending


async def save_settings_to_disk(path: Path | None, settings: Settings) -> None:
    """Atomically write ``settings`` to ``path``.

    If ``path`` is ``None``, the in-memory path recorded by
    :func:`load_settings_from_disk` is used; if that is also ``None``,
    the bootstrap path is the final fallback. This helper does NOT
    touch any ``pending`` key on disk - callers that need to manage
    pending state use :func:`apply_update` / :func:`apply_pending`.
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
    """Apply a PATCH and return ``(in_memory_settings, restart_required)``.

    ``restart_required`` is True when the patch's ``data_dir`` field
    is set AND the new value differs from the current value. A PATCH
    that omits ``data_dir`` (or sets the same value) is not
    restart-required.

    Behavior (Plan 01-04 H1 + Phase 2 hot-swap):

    - On a restart-required change: persist the new model under the
      ``pending`` sibling key (the active settings stay at the BOOT
      value). Set ``_State.pending`` to the new model. Do NOT swap
      ``_State.settings``. The returned in-memory value is the
      unchanged current; the X-Restart-Required header is the
      explicit signal that a restart is needed.
    - On a non-restart change (omitted ``data_dir`` or set to the
      current value, OR a hot-swap of any Phase 2 field): drop any
      prior pending slot, write the FULL new model to disk
      (so ``quality_preset`` / ``hf_token`` / ``concurrent_models`` /
      ``vram_budget_fraction`` / ``per_category_overrides`` hot-swaps
      persist — Phase 2 D-08), and swap ``_State.settings`` to the
      new model. The on-disk file is the serialization of the new
      model (D-14: model is source of truth).

    Ordering: build the new model -> write the updated disk dict
    (atomic) -> on success update in-memory state. A disk-write
    failure leaves the in-memory state untouched and re-raises.
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

    target_path = _State.path or _default_settings_path()

    if restart_required:
        # H1: persist the full new model under the pending key; the
        # active settings stay at the BOOT model. We write the full
        # existing.model_dump() as the active dict (not the raw disk
        # dict) so the on-disk file is the canonical serialization of
        # the active Settings (D-14).
        disk = existing.model_dump()
        disk[_PENDING_KEY] = new.model_dump()
        await _write_disk_dict(target_path, disk)
        _State.pending = new
        # Do NOT swap _State.settings. The route layer surfaces the
        # X-Restart-Required header; the next boot's apply_pending
        # installs the new value.
        return existing, True

    # Non-restart change: write the FULL new model to disk (so Phase 2
    # hot-swap fields persist), drop any prior pending, swap in-memory.
    disk = new.model_dump()
    await _write_disk_dict(target_path, disk)
    _State.pending = None
    _State.settings = new
    return new, False


def apply_pending() -> bool:
    """Install any pending-restart change as the in-memory current.

    Called by the lifespan AFTER :func:`load_settings_from_disk` and
    the engine/session factory are built. If ``_State.pending`` is
    non-None, the value is installed as ``_State.settings`` and the
    on-disk file is rewritten as the canonical serialization of the
    new model (D-14) without the pending key. Returns True if a
    pending change was installed, False otherwise.

    The on-disk rewrite writes the FULL ``new.model_dump()`` (not just
    ``data_dir``) so Phase 2 fields carried in the pending model
    persist cleanly. Synchronous write: ``apply_pending`` is called
    from the lifespan on the event loop but is not itself async; the
    file is small and ``atomic_write_json`` is async-only.
    """
    if _State.pending is None:
        return False
    new = _State.pending
    _State.settings = new
    _State.pending = None
    target_path = _State.path or _default_settings_path()
    # Rewrite the disk file as the canonical serialization of the
    # new model (no pending key).
    disk = new.model_dump()
    import os
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_", dir=str(target_path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(disk, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return True


__all__ = [
    "apply_pending",
    "apply_update",
    "configure",
    "current",
    "load_settings_from_disk",
    "save_settings_to_disk",
]
