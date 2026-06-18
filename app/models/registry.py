"""The model registry: short id -> :class:`ModelSpec` (Plan 02-02).

The registry is the TYPED source of truth for every model the app
knows how to download + load. Keys follow the
``<preset_short>.<category_short>`` convention so a route path
parameter (``/models/balanced.llm/load``) maps directly to a spec
plus a :class:`ModelCategory`.

The BALANCED triple (D-09) is the default model set:

- ``balanced.stt``    -> ``Systran/faster-whisper-large-v3``
- ``balanced.diarize`` -> ``pyannote/speaker-diarization-3.1`` (gated)
- ``balanced.llm``    -> ``Qwen/Qwen2.5-7B-Instruct-GGUF`` +
  ``qwen2.5-7b-instruct-q4_k_m.gguf`` (~4.5 GB; fits the 8 GB laptop
  one-at-a-time per RESEARCH math).

The SMALL triple (Qwen2.5-3B ~2 GB) and the LARGE triple
(Qwen2.5-14B ~10 GB; HW-08 desktop opt-in) are declared alongside.

``expected_sha256`` is left ``None`` per the CONTEXT deferred item
(re-verify the actual SHA from HF at registry-build time in a later
phase); ``expected_size_bytes`` is an approximation used for VRAM
budget math only and is NOT the integrity check (SHA256 is).
"""

from __future__ import annotations

from app.models.diagnostics import ModelCategory, ModelSpec

# --- BALANCED triple (D-09 default) -----------------------------------------

_BALANCED_STT = ModelSpec(
    repo_id="Systran/faster-whisper-large-v3",
    file=None,
    revision=None,
    expected_size_bytes=None,
    expected_sha256=None,
)
_BALANCED_DIARIZE = ModelSpec(
    repo_id="pyannote/speaker-diarization-3.1",
    file=None,
    revision=None,
    expected_size_bytes=None,
    expected_sha256=None,
)
_BALANCED_LLM = ModelSpec(
    repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
    file="qwen2.5-7b-instruct-q4_k_m.gguf",
    revision=None,
    expected_size_bytes=4_500_000_000,
    expected_sha256=None,
)

# --- SMALL triple -----------------------------------------------------------

_SMALL_STT = ModelSpec(
    repo_id="Systran/faster-whisper-small",
    file=None,
    revision=None,
    expected_size_bytes=None,
    expected_sha256=None,
)
_SMALL_LLM = ModelSpec(
    repo_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
    file="qwen2.5-3b-instruct-q4_k_m.gguf",
    revision=None,
    expected_size_bytes=2_000_000_000,
    expected_sha256=None,
)

# --- LARGE triple (HW-08 desktop opt-in) ------------------------------------

_LARGE_LLM = ModelSpec(
    repo_id="Qwen/Qwen2.5-14B-Instruct-GGUF",
    file="qwen2.5-14b-instruct-q4_k_m.gguf",
    revision=None,
    expected_size_bytes=10_000_000_000,
    expected_sha256=None,
)


REGISTRY: dict[str, ModelSpec] = {
    # BALANCED (D-09).
    "balanced.stt": _BALANCED_STT,
    "balanced.diarize": _BALANCED_DIARIZE,
    "balanced.llm": _BALANCED_LLM,
    # SMALL.
    "small.stt": _SMALL_STT,
    "small.diarize": _BALANCED_DIARIZE,
    "small.llm": _SMALL_LLM,
    # LARGE (desktop opt-in, HW-08).
    "large.stt": _BALANCED_STT,
    "large.diarize": _BALANCED_DIARIZE,
    "large.llm": _LARGE_LLM,
}


# ``category_short`` -> ``ModelCategory``. Used by :func:`get_category`
# to derive the category from a registry id like ``balanced.llm``.
_CATEGORY_SHORTS: dict[str, ModelCategory] = {
    "stt": ModelCategory.STT,
    "diarize": ModelCategory.DIARIZE,
    "llm": ModelCategory.LLM,
}


def get_spec(id: str) -> ModelSpec:
    """Return the :class:`ModelSpec` for ``id`` or raise :class:`KeyError`.

    The error message lists every valid id so a caller sending a bad
    path parameter (``/models/nonexistent/load``) gets an actionable
    message (T-02-10 -- unknown ids do not reach the filesystem).
    """
    try:
        return REGISTRY[id]
    except KeyError as exc:
        raise KeyError(
            f"unknown model id: {id!r}; available: {sorted(REGISTRY.keys())}"
        ) from exc


def get_category(id: str) -> ModelCategory:
    """Parse ``id`` as ``<preset_short>.<category_short>`` -> :class:`ModelCategory`.

    Raises :class:`ValueError` if the id is malformed or the category
    short is unknown. The preset half is NOT validated here (any
    preset short is accepted so future presets do not need to touch
    this function); only the category half must map to a known
    :class:`ModelCategory`.
    """
    if not isinstance(id, str) or "." not in id:
        raise ValueError(
            f"invalid model id: {id!r}; expected '<preset>.<category>'"
        )
    _, _, category_short = id.rpartition(".")
    try:
        return _CATEGORY_SHORTS[category_short]
    except KeyError as exc:
        raise ValueError(
            f"unknown model category short: {category_short!r}; "
            f"expected one of {sorted(_CATEGORY_SHORTS.keys())}"
        ) from exc


def list_specs() -> list[tuple[str, ModelSpec]]:
    """Return ``sorted(REGISTRY.items())`` (stable for test snapshots)."""
    return sorted(REGISTRY.items())


__all__ = ["REGISTRY", "get_category", "get_spec", "list_specs"]