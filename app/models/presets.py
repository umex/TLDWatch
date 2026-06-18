"""The presets table + the active-set resolver (Plan 02-02, D-09).

``PRESETS`` maps each :class:`QualityPreset` to its :class:`ModelSet`
triple (STT + diarize + LLM). The BALANCED triple is the default
(D-09): ``Systran/faster-whisper-large-v3`` +
``pyannote/speaker-diarization-3.1`` + ``Qwen/Qwen2.5-7B-Instruct-GGUF``
``qwen2.5-7b-instruct-q4_k_m.gguf`` (~4.5 GB).

``active_model_set(settings)`` resolves which triple is active given
the current settings:

1. Pick the preset from ``settings.quality_preset`` (D-09 BALANCED
   default).
2. If ``settings.per_category_overrides`` is set, merge it over the
   preset: ``overrides.stt or preset.stt`` (None falls through), so a
   per-category override wins over the preset and the un-overridden
   categories keep the preset (HW-06).

Phase 2 ships the mechanism (the typed data behind the future
settings panel); Phase 10 surfaces the picker UI.
"""

from __future__ import annotations

import logging

from app.models.diagnostics import ModelSet, QualityPreset
from app.models.registry import REGISTRY
from app.models.settings import Settings

_log = logging.getLogger(__name__)

# --- The three preset triples (D-09) ----------------------------------------

SMALL = ModelSet(
    stt=REGISTRY["small.stt"],
    diarize=REGISTRY["small.diarize"],
    llm=REGISTRY["small.llm"],
)

BALANCED = ModelSet(
    stt=REGISTRY["balanced.stt"],
    diarize=REGISTRY["balanced.diarize"],
    llm=REGISTRY["balanced.llm"],
)

LARGE = ModelSet(
    stt=REGISTRY["large.stt"],
    diarize=REGISTRY["large.diarize"],
    llm=REGISTRY["large.llm"],
)

PRESETS: dict[QualityPreset, ModelSet] = {
    QualityPreset.SMALL: SMALL,
    QualityPreset.BALANCED: BALANCED,
    QualityPreset.LARGE: LARGE,
}


def active_model_set(settings: Settings) -> ModelSet:
    """Resolve the active :class:`ModelSet` for ``settings`` (D-09 + HW-06).

    Per-category override wins over preset: ``overrides.stt or
    preset.stt`` (None falls through). With no overrides, the preset
    triple is returned as-is.
    """
    preset = PRESETS[settings.quality_preset]
    overrides = settings.per_category_overrides
    if overrides is None:
        return preset
    return ModelSet(
        stt=overrides.stt or preset.stt,
        diarize=overrides.diarize or preset.diarize,
        llm=overrides.llm or preset.llm,
    )


__all__ = ["BALANCED", "LARGE", "PRESETS", "SMALL", "active_model_set"]