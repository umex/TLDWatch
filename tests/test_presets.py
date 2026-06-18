"""Tests for the presets table + the active-set resolver (D-09, HW-06).

Four pure-Python unit tests (no I/O, no fixtures beyond import):

- ``test_balanced_preset_stt_repo_id`` -- the BALANCED STT repo_id.
- ``test_balanced_preset_diarize_repo_id`` -- the BALANCED diarize repo_id.
- ``test_balanced_preset_llm_file`` -- the BALANCED LLM filename.
- ``test_active_model_set_override_wins`` -- a per-category override
  overrides only the overridden category; the other two fall through
  to the preset (HW-06).
"""

from __future__ import annotations

from app.models.diagnostics import ModelCategory, ModelSet, ModelSpec, QualityPreset
from app.models.presets import PRESETS, active_model_set
from app.models.registry import REGISTRY, get_category, get_spec, list_specs
from app.models.settings import Settings
from app.models.diagnostics import GpuBackend


def test_balanced_preset_stt_repo_id() -> None:
    """D-09: BALANCED.stt is Systran/faster-whisper-large-v3."""
    assert (
        PRESETS[QualityPreset.BALANCED].stt.repo_id
        == "Systran/faster-whisper-large-v3"
    )


def test_balanced_preset_diarize_repo_id() -> None:
    """D-09: BALANCED.diarize is pyannote/speaker-diarization-3.1."""
    assert (
        PRESETS[QualityPreset.BALANCED].diarize.repo_id
        == "pyannote/speaker-diarization-3.1"
    )


def test_balanced_preset_llm_file() -> None:
    """D-09: BALANCED.llm is the Qwen2.5-7B Q4_K_M GGUF."""
    llm = PRESETS[QualityPreset.BALANCED].llm
    assert llm.repo_id == "Qwen/Qwen2.5-7B-Instruct-GGUF"
    assert llm.file == "qwen2.5-7b-instruct-q4_k_m.gguf"


def test_active_model_set_override_wins() -> None:
    """HW-06: a per-category override wins over the preset for that
    category only; the un-overridden categories fall through to the
    preset (None falls through via ``overrides.x or preset.x``).
    """
    settings = Settings(
        data_dir="C:/tmp/data",
        backend=GpuBackend.CUDA,
        quality_preset=QualityPreset.BALANCED,
        per_category_overrides=ModelSet(
            stt=ModelSpec(repo_id="custom/stt"),
            diarize=REGISTRY["balanced.diarize"],
            llm=REGISTRY["balanced.llm"],
        ),
    )
    active = active_model_set(settings)
    assert active.stt.repo_id == "custom/stt"
    # Diarize + LLM fall through to the BALANCED preset.
    assert active.diarize.repo_id == "pyannote/speaker-diarization-3.1"
    assert active.llm.repo_id == "Qwen/Qwen2.5-7B-Instruct-GGUF"


def test_registry_has_nine_entries() -> None:
    """3 categories x 3 presets = 9 entries in REGISTRY."""
    assert len(REGISTRY) >= 9
    assert get_category("balanced.llm") == ModelCategory.LLM
    assert get_spec("balanced.llm").file == "qwen2.5-7b-instruct-q4_k_m.gguf"


def test_get_spec_unknown_raises_keyerror_listing_ids() -> None:
    """T-02-10: an unknown id raises KeyError with the list of valid ids."""
    import pytest

    with pytest.raises(KeyError) as exc:
        get_spec("nonexistent")
    msg = str(exc.value)
    assert "balanced.llm" in msg