"""Pydantic models for the Phase 2 diagnostics + model-manager surface.

This module is the SINGLE declaration site for the enums and typed
result models that the back-end, the diagnostics API, and the
OpenAPI schema all share (D-08 declare-now). Downstream modules
(``app.models.settings``, ``app.models.backend``, ``app.models.vram``,
``app.api.routes_diagnostics``) re-import from here so there is one
source of truth.

Strict-vs-lax discipline (D-15):

- ``BackendProbe``, ``ModelSpec``, ``ModelSet`` are STRICT
  (``ConfigDict(extra="forbid")``) because they are inputs to internal
  mutators (the burn-test result is written to disk; a model spec is
  user-selected in 02-02). An unknown field here is a bug, not
  forward-compat.
- The response / state models (``VRAMState``, ``LoadedModelInfo``,
  ``HfTokenResult``, ``GpuBurnResult``) are LAX (default config) so a
  future field added to a response does not break a stale reader.
- The enums (``GpuBackend``, ``QualityPreset``, ``ModelCategory``) are
  ``str, Enum`` so they JSON-encode as their string value and Pydantic
  round-trips them across the wire without an explicit serializer.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.time import utcnow_iso


class GpuBackend(str, Enum):
    """Active GPU backend detected on this machine.

    Values are lowercase short strings so the on-disk ``settings.json``
    reads cleanly (``"backend": "cuda"``) and the OpenAPI enum surfaces
    the same tokens the React settings panel will display.
    """

    CUDA = "cuda"
    ROCM = "rocm"
    CPU = "cpu"


class QualityPreset(str, Enum):
    """Model-set preset (D-09). Values filled by 02-02's ``presets.py``."""

    SMALL = "small"
    BALANCED = "balanced"
    LARGE = "large"


class ModelCategory(str, Enum):
    """Per-category model slot used by the model manager (02-02)."""

    STT = "stt"
    DIARIZE = "diarize"
    LLM = "llm"


class BackendProbe(BaseModel):
    """Result of a real-kernel burn test on the active backend.

    ``device_name`` is the GPU marketing name (``"NVIDIA RTX 2000 Ada"``,
    ``"AMD Radeon RX 6800 XT"``) or ``"CPU"`` on the silent fallback
    path (D-06). ``vram_total_mb`` and ``burn_test_ms`` are ``None`` on
    CPU: the CPU path has no VRAM and no kernel to time. ``probed_at``
    is the ISO-8601 UTC timestamp of the probe (D-06 log-only verdict
    that Phase 10 surfaces).
    """

    model_config = ConfigDict(extra="forbid")

    backend: GpuBackend
    device_name: str
    driver_version: str | None = None
    vram_total_mb: int | None = None
    burn_test_ms: float | None = None
    # ``default_factory`` is invoked at instance creation time in
    # Pydantic v2, so each ``BackendProbe`` gets a fresh timestamp
    # rather than the module-import timestamp.
    probed_at: str = Field(default_factory=utcnow_iso)
    notes: str = ""


class LoadedModelInfo(BaseModel):
    """One entry in :class:`VRAMState.loaded` (02-02 plumbs the real values)."""

    category: ModelCategory
    model_id: str
    vram_mb: int
    loaded_at: str


class VRAMState(BaseModel):
    """Snapshot of GPU/CPU memory state returned by ``GET /diagnostics/vram``.

    ``loaded`` is empty until 02-02's model manager wires in
    (``ManagerState.live_vram_bytes`` is the source for this list).
    """

    backend: GpuBackend
    total_mb: int
    available_mb: int
    used_mb: int
    loaded: list[LoadedModelInfo] = Field(default_factory=list)


class HfTokenResult(BaseModel):
    """Four-state result of ``POST /diagnostics/test-hf-token`` (D-05, Pitfall 3).

    - ``skipped``: no token configured, or HF Hub unreachable (network
      error never blocks the app — Pitfall 3).
    - ``ok``: the token authenticated against HF Hub; ``user`` carries
      the HF username (from the ``x-repo-author`` response header).
    - ``rejected``: the token is invalid (401) or the gated pyannote
      repo's terms have not been accepted (403); ``reason`` + ``fix``
      carry the user-facing explanation.
    """

    status: Literal["skipped", "ok", "rejected"]
    reason: str | None = None
    user: str | None = None
    fix: str | None = None


class GpuBurnResult(BaseModel):
    """Response of ``POST /diagnostics/gpu-burn`` (the re-detect path)."""

    probe: BackendProbe
    active_backend: GpuBackend
    settings_written: bool


class ModelSpec(BaseModel):
    """One model slot in a :class:`ModelSet` (values filled in 02-02)."""

    model_config = ConfigDict(extra="forbid")

    repo_id: str
    file: str | None = None
    revision: str | None = None
    expected_size_bytes: int | None = None
    expected_sha256: str | None = None


class ModelSet(BaseModel):
    """Per-category model set selected by a :class:`QualityPreset`."""

    stt: ModelSpec
    diarize: ModelSpec
    llm: ModelSpec


__all__ = [
    "BackendProbe",
    "GpuBackend",
    "GpuBurnResult",
    "HfTokenResult",
    "LoadedModelInfo",
    "ModelCategory",
    "ModelSet",
    "ModelSpec",
    "QualityPreset",
    "VRAMState",
]