"""``GET /settings`` + ``PATCH /settings`` routes.

``GET /settings`` returns the in-memory current :class:`Settings`
(lax output - the model is the source of truth, D-14, D-15).

``PATCH /settings`` accepts a strict :class:`UpdateSettingsRequest`,
atomically rewrites ``data/settings.json`` (via the settings
service), and updates the in-memory state. The response includes
the ``X-Restart-Required: true`` header when the patch actually
changed ``data_dir`` (Codex HIGH item 9). The change is PERSISTED
at PATCH time, but the engine, session factory, and settings-file
path are NOT hot-swapped - the new ``data_dir`` takes effect on
restart.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.models.settings import Settings, UpdateSettingsRequest
from app.settings.service import apply_update, current

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    """Return the current :class:`Settings` (lax output)."""
    return current()


@router.patch("", response_model=Settings)
async def patch_settings(
    payload: UpdateSettingsRequest,
    response: Response,
) -> Settings:
    """Apply a PATCH to the settings; emit ``X-Restart-Required: true``
    on the response when ``data_dir`` actually changed.
    """
    new, restart_required = await apply_update(payload)
    if restart_required:
        response.headers["X-Restart-Required"] = "true"
    return new
