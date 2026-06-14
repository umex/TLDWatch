from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """Persisted application settings.

    Phase 1 ships only ``data_dir`` (D-17). Future phases add ``gpu_backend``,
    ``hf_token``, ``quality_preset``, ``per_category_overrides`` and any
    other field they need. The settings file is the serialisation of this
    model; the model is the source of truth (D-14).
    """

    model_config = ConfigDict(extra="forbid")

    data_dir: str


__all__ = ["Settings"]
