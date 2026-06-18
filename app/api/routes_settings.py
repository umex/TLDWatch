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
    """Return the current :class:`Settings` (lax output).

    D-05: ``hf_token`` is NEVER returned in the response regardless of
    ``?reveal=``. The on-disk file holds the base64-encoded value; the
    response nulls it so a stray ``GET /settings`` does not leak the
    token to a caller reading the body. We build the response body
    from ``current().model_dump()`` and explicitly null ``hf_token``
    before returning; ``response_model=Settings`` re-validates the
    dict (the ``hf_token`` field_validator passes ``None`` through, and
    the field_serializer returns ``None`` for ``None``), so the wire
    body carries ``"hf_token": null``.
    """
    body = current().model_dump()
    body["hf_token"] = None
    return body  # type: ignore[return-value]


@router.patch("", response_model=Settings)
async def patch_settings(
    payload: UpdateSettingsRequest,
    response: Response,
) -> Settings:
    """Apply a PATCH to the settings; emit ``X-Restart-Required: true``
    on the response when ``data_dir`` actually changed.

    The response body is the in-memory state AFTER the PATCH:

    - When ``data_dir`` changes (restart-required), the in-memory
      state is unchanged (Plan 01-04 H1: defer the swap to restart).
      The body is the BOOT value of ``data_dir``; the new value is
      durable on disk under the ``pending`` key.
    - When no restart is required (omitted ``data_dir`` or same
      value), the body is the new in-memory state (which equals the
      patched value).
    """
    result, restart_required = await apply_update(payload)
    if restart_required:
        response.headers["X-Restart-Required"] = "true"
    # D-05: ``hf_token`` is NEVER returned in the response, mirroring
    # ``get_settings``. Without this, ``response_model=Settings``
    # serializes the in-memory token via the base64 field_serializer
    # and leaks the (trivially decodable) credential in the body.
    body = result.model_dump()
    body["hf_token"] = None
    return body  # type: ignore[return-value]
