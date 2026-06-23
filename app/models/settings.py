from __future__ import annotations

import base64
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.models.diagnostics import (
    BackendProbe,
    GpuBackend,
    ModelSet,
    QualityPreset,
)


def _b64_encode(value: str) -> str:
    """Base64-encode a cleartext HF token for on-disk storage (D-05)."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _b64_decode(value: str) -> str:
    """Base64-decode an on-disk HF token back to cleartext (D-05).

    Raises ``ValueError`` if ``value`` is not valid base64 or does not
    decode to UTF-8; the caller (the field_validator) treats this as
    "not base64" and falls back to treating the input as cleartext.
    """
    raw = base64.b64decode(value, validate=True)
    return raw.decode("utf-8")


class Settings(BaseModel):
    """Persisted application settings (D-14: model is source of truth).

    Phase 2 extends the Phase 1 ``data_dir``-only model with seven new
    fields per D-08 (declare-now): ``backend``, ``backend_probe``,
    ``hf_token``, ``quality_preset``, ``per_category_overrides``,
    ``concurrent_models``, ``vram_budget_fraction``. A fresh boot
    writes a single stable on-disk format carrying every field the
    model manager (02-02) and the Phase 10 settings panel will read.

    ``backend`` has NO default: it is set by the first-run detect path
    (``app.main`` lifespan) and by ``POST /diagnostics/gpu-burn`` only.
    The other six new fields have defaults so the detect path can
    construct a ``Settings`` with just ``data_dir`` + ``backend`` +
    ``backend_probe``.

    ``hf_token`` is base64-encoded on the on-disk dump via
    :func:`_serialize_hf_token` and base64-decoded on load via
    :func:`_decode_hf_token` (D-05 — no accidental cleartext on
    ``cat settings.json``). The ``GET /settings`` response NULLS the
    field regardless of the on-disk value (handled in the route layer
    so the model itself stays the single source of truth for the
    on-disk format).
    """

    model_config = ConfigDict(extra="forbid")

    data_dir: str
    # Required (no default): set by first-run detect / re-detect only.
    backend: GpuBackend
    backend_probe: BackendProbe | None = None
    # D-05: base64 on disk, never returned in GET /settings.
    hf_token: str | None = None
    # D-09: BALANCED is the default preset.
    quality_preset: QualityPreset = QualityPreset.BALANCED
    per_category_overrides: ModelSet | None = None
    # SC-5: concurrent_models is opt-in (default False, hidden by default).
    concurrent_models: bool = False
    # SC-4: 85% VRAM budget gate default.
    vram_budget_fraction: float = 0.85
    # Phase 4 D-10: worker=1 serial dispatch toggle. When True the
    # lifespan (wired in plan 04-02) auto-starts the single in-process
    # worker that drains the queue. Tests set it False so they can
    # drive the worker manually and assert on synchronous state. Has a
    # default so existing settings files without the field load cleanly
    # (the model is extra="forbid" -- a defaulted field is the safe way
    # to add it; the Phase 2 apply_pending / load_settings_from_disk
    # path still round-trips because the field is always emitted on
    # dump).
    run_worker: bool = True
    # Phase 4 plan 04-03 (T-04-02 DoS guard): cap on concurrent WS
    # subscribers per job_id. The SubscriberRegistry on app.state
    # rejects extra subscribers with an error close (1008) so a single
    # job_id cannot accumulate unbounded WS connections. Defaulted so
    # existing settings files without the field load cleanly under
    # extra="forbid".
    ws_subscriber_cap: int = 16
    # Phase 4 plan 04-03 (Codex LOW): idempotency-key TTL in hours.
    # The janitor task (started in lifespan guarded by run_worker)
    # periodically DELETEs idempotency_keys rows older than this. 24h
    # matches the common "retry within a day" pattern; clients that
    # need longer-lived idempotency can raise this.
    idempotency_ttl_hours: int = 24

    @field_serializer("hf_token")
    def _serialize_hf_token(self, value: str | None) -> str | None:
        """Base64-encode ``hf_token`` for the on-disk dump (D-05).

        Conditional: only encodes if ``value is not None`` so a missing
        token serializes as ``null``, not an empty base64 string.
        """
        if value is None:
            return None
        return _b64_encode(value)

    @field_validator("hf_token", mode="before")
    @classmethod
    def _decode_hf_token(cls, value):  # type: ignore[no-untyped-def]
        """Base64-decode ``hf_token`` on load (D-05).

        ``None`` passes through unchanged. A string that is valid base64
        AND decodes to UTF-8 is treated as the on-disk base64 form and
        decoded. A string that is NOT valid base64 (e.g. a cleartext
        token passed to the constructor in tests) is treated as
        cleartext and returned unchanged — this lets
        ``Settings(hf_token='hf_abc123')`` work without pre-encoding.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        if value == "":
            return None
        try:
            return _b64_decode(value)
        except Exception:
            # Not valid base64 (or not UTF-8) — treat as cleartext.
            return value


class UpdateSettingsRequest(BaseModel):
    """Strict input model for ``PATCH /settings`` (D-15 strict input).

    Phase 2 extends the Phase 1 ``data_dir``-only request with five
    new optional fields (``hf_token``, ``quality_preset``,
    ``per_category_overrides``, ``concurrent_models``,
    ``vram_budget_fraction``). All fields are optional (``| None =
    None``) so a PATCH can hot-swap any single field without sending
    the others (H1: only ``data_dir`` is restart-required; the new
    fields are hot-swap).

    ``backend`` and ``backend_probe`` are NOT declared (D-08 — only
    the detect/burn path writes them). ``extra="forbid"`` rejects them
    at the API boundary with 422.

    A PATCH with NO fields set (empty body ``{}``) is rejected with
    422 — a no-op PATCH is invalid. This preserves the Phase 1
    ``test_empty_patch_returns_422`` contract while allowing single-
    field hot-swaps.

    The ``data_dir`` validator runs ONLY when ``data_dir`` is in the
    request (``model_fields_set``); a PATCH that omits ``data_dir``
    does not trigger path validation. An explicit ``null`` for
    ``data_dir`` is rejected (preserves ``test_data_dir_null_returns_422``).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    data_dir: str | None = None
    hf_token: str | None = None
    # ``strict=False`` on the enum + nested-model fields so the API
    # accepts the JSON string / dict form (lax coercion to the typed
    # value). The model-level ``strict=True`` stays for ``data_dir``,
    # ``hf_token``, ``concurrent_models``, ``vram_budget_fraction`` so
    # a wrong-typed scalar (int data_dir, string vram) is 422'd at the
    # API boundary (D-15).
    quality_preset: QualityPreset | None = Field(default=None, strict=False)
    per_category_overrides: ModelSet | None = Field(default=None, strict=False)
    concurrent_models: bool | None = None
    vram_budget_fraction: float | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> "UpdateSettingsRequest":
        # Reject an empty PATCH (no fields set) — a no-op PATCH is
        # invalid. This preserves the Phase 1 empty-body 422 contract.
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        # ``data_dir`` validation only runs when the client explicitly
        # sent the field. An explicit ``null`` is rejected (the Phase 1
        # contract: data_dir is a string, not nullable).
        if "data_dir" in self.model_fields_set:
            value = self.data_dir
            if value is None:
                raise ValueError("data_dir must not be null")
            if value == "":
                raise ValueError("data_dir must not be empty")
            p = Path(value)
            if not p.is_absolute():
                raise ValueError(
                    f"data_dir must be an absolute path; got {value!r}"
                )
            if p.exists() and p.is_file():
                raise ValueError(
                    f"data_dir must not point at an existing file; got {value!r}"
                )
        return self

    @field_validator("vram_budget_fraction")
    @classmethod
    def _validate_vram_budget(cls, value):  # type: ignore[no-untyped-def]
        """Reject out-of-range ``vram_budget_fraction`` (D-15 strict)."""
        if value is None:
            return value
        if value < 0.1 or value > 0.95:
            raise ValueError(
                "vram_budget_fraction must be between 0.1 and 0.95 (inclusive); "
                f"got {value}"
            )
        return value


__all__ = ["Settings", "UpdateSettingsRequest"]