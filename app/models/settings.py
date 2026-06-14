from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


class Settings(BaseModel):
    """Persisted application settings.

    Phase 1 ships only ``data_dir`` (D-17). Future phases add ``gpu_backend``,
    ``hf_token``, ``quality_preset``, ``per_category_overrides`` and any
    other field they need. The settings file is the serialisation of this
    model; the model is the source of truth (D-14).
    """

    model_config = ConfigDict(extra="forbid")

    data_dir: str


class UpdateSettingsRequest(BaseModel):
    """Strict input model for ``PATCH /settings``.

    Plan 01-04 (T8): the ``data_dir`` field is now NON-OPTIONAL (the
    only Phase 1 field; the client MUST send it). A model_validator
    rejects:

    - ``None`` (the field is ``str``, not ``str | None``)
    - empty string
    - relative paths (the path must be absolute)
    - existing file paths (the path must not point at a regular file
      - it can be an existing directory OR a creatable path whose
      parent does not need to exist yet)

    Strict input means a wrong-typed field (``data_dir: 123``) or an
    unknown field is rejected at the API boundary with a 422 (D-15).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    data_dir: str

    @model_validator(mode="after")
    def _validate_data_dir(self) -> "UpdateSettingsRequest":
        value = self.data_dir
        # Reject empty string.
        if value == "":
            raise ValueError("data_dir must not be empty")
        # Reject relative paths. ``Path.is_absolute`` is the canonical
        # check; ``C:/some/path``, ``/abs/path`` are absolute on the
        # respective OS, ``relative/path`` is not on either.
        p = Path(value)
        if not p.is_absolute():
            raise ValueError(
                f"data_dir must be an absolute path; got {value!r}"
            )
        # Reject existing file paths (the path must be a directory or
        # a creatable path; an existing regular file is not a valid
        # data dir).
        if p.exists() and p.is_file():
            raise ValueError(
                f"data_dir must not point at an existing file; got {value!r}"
            )
        return self


__all__ = ["Settings", "UpdateSettingsRequest"]
