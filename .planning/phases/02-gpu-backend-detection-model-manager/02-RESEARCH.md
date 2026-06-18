# Phase 2: GPU Backend Detection + Model Manager - Research

**Researched:** 2026-06-15
**Domain:** Local GPU back-end selection (CUDA / ROCm / CPU) + model lifecycle (download, verify, lazy load, idle unload, VRAM discipline)
**Confidence:** MEDIUM (the library APIs are HIGH-confidence; the ROCm-on-Windows-for-gfx1030 reality is the load-bearing variable, and the spike deliverable is the only way to actually resolve it for this project)

## Executive Summary

Phase 2 is two distinct capabilities bolted together by a single guarantee: "the user never has to know which GPU is in the box."

1. **GPU detect + first-run burn test.** A silent ordered check (torch + env vars + nvidia-smi + `pip`-querying the active wheel) on the laptop (CUDA, RTX 2000 Ada sm_89) and the desktop (RDNA2 gfx1030, ROCm). The crucial fact for mid-2026: there is no official PyTorch ROCm Windows wheel for gfx1030; the only working path is the TheRock nightly `gfx103X-dgpu` index (`https://rocm.nightlies.amd.com/v2-staging/gfx103X-dgpu/`) which supports both Python 3.11 and 3.12. Detection writes the active backend to `settings.json` *only after a real kernel run* (a one-line matmul for torch, a 50-token prompt for llama.cpp), not after a `torch.cuda.is_available()` probe alone — that's the load-bearing "is this real GPU, not silent CPU" check (Pitfall 1).
2. **Model manager with VRAM discipline.** A `ModelManager` owns the lifecycle of every model file on disk and in VRAM. Download (resumable via `huggingface_hub` `<blob>.incomplete` semantics), SHA/size verify, lazy load (refuses if 85% budget would be exceeded, refuses a second model unless the opt-in `concurrent_models: true` toggle is on), explicit unload, per-model VRAM log. The HF token is stored in `settings.json` for v1 (deferred to a `secrets.json` only if/when export-to-share becomes a thing).

**Primary recommendation:** ship `app/models/backend.py` (enum + ordered detect + burn-test function), extend `Settings` to carry the GPU-burn result + HF token + quality preset + per-category overrides (declared now, used by Phase 10), build `app/models/manager.py` with a typed `ModelSpec` and a `get_model(id) -> LoadedModel` API, and emit `02-03-SPIKE.md` as the deliverable of the desktop ROCm plan. The spike is the only piece of Phase 2 the user may need to act on; everything else is silent.

**Architectural responsibility map** (consumed by the planner to assign tasks to the right layer):

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GPU detect + burn test | API / Backend (`app/main.py` lifespan + `app/models/backend.py`) | — | One-shot at boot, writes to settings; no UI surface in Phase 2 |
| Settings model extensions | Models (`app/models/settings.py`) | API (`app/api/routes_settings.py`) | New Pydantic fields + matching `UpdateSettingsRequest` strict variant |
| Model download + verify | Models (`app/models/manager.py` + `app/models/registry.py`) | — | Single-process back-end; no async I/O contention |
| VRAM probe | Models (`app/models/vram.py`) | API (`GET /diagnostics/vram`) | Source of truth is the back-end; UI just displays |
| Default model set | Models (`app/models/presets.py`) | — | Pure typed data; Phase 10 surfaces it |
| HF token gating | Models (`app/models/manager.py` test-token path) | Settings (storage) | Token lives in settings; test-token is a back-end one-shot |
| Front-end surface | — (n/a in Phase 2) | — | React repo arrives in Phase 5; Phase 2 has no UI work |

## GPU Detect Protocol (ordered checks, env vars, libraries, "is this real GPU" verification)

The "is this really a GPU, or did we silently fall back to CPU" question is the most important thing Phase 2 proves on the user's behalf. The detection protocol is **two stages**: a cheap discovery probe that narrows the candidate backends, and a real-kernel burn test that confirms the chosen path actually runs on the GPU.

### Stage 1 — Discovery probe (cheap, runs at boot before any import of model code)

```
1. nvidia-smi present + parses            → nvidia path available
2. pip show torch | grep "+cu"            → PyTorch was installed against a CUDA wheel
3. pip show torch | grep "+rocm"          → PyTorch was installed against a ROCm wheel
4. ROCM_PATH / HIP_PATH env vars          → ROCm/HIP SDK is on disk (manual install evidence)
5. lemon-clip / rocm-smi present          → AMD userland tools present
6. torch.cuda.is_available()              → PyTorch-level "some GPU is visible" (CUDA or HIP)
7. torch.cuda.device_count()              → > 0
8. torch.version.hip is not None          → this is HIP (ROCm), not CUDA
9. Win32_VideoController WMI              → vendor + name (NVIDIA / AMD / Intel / none)
```

**Sources / libraries used in code:**

- `subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"])` — short timeout (3 s); a non-zero exit means no NVIDIA driver.
- `subprocess.run(["pip", "show", "torch"])` — parse the `Name:`, `Version:`, and the `Requires:` line for `+cu` or `+rocm`. This is the *only* reliable way to know which wheel of torch is actually installed; `torch.version.cuda` is `None` on a ROCm build but is non-trivial to interpret on a CPU build.
- `os.environ.get("ROCM_PATH") or os.environ.get("HIP_PATH")` — presence of either is a strong signal the user installed ROCm by hand (the Windows story in 2026).
- `import torch; torch.cuda.is_available()` and `torch.cuda.device_count()` — narrow to CUDA/HIP. With `torch 2.x` ROCm exposes HIP devices through the `torch.cuda` API (the `+rocm` wheel is API-compatible). On a 3.13+ torch with no GPU visible, this is `False`.
- `torch.version.hip` — `None` means CUDA or CPU; non-`None` means HIP (ROCm) is the backend.
- Windows-specific: `subprocess.run(["wmic", "path", "Win32_VideoController", "get", "Name"])` (deprecated but still works on Win10) or `subprocess.run(["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Name"])` — gives the user-visible "AMD Radeon RX 6800 XT" / "NVIDIA RTX 2000 Ada" string for the log line.

**Output of Stage 1: a `DetectionCandidate` with one of:**

- `NVIDIA` (laptop: `+cu` wheel + `nvidia-smi` works + `torch.cuda.is_available()=True` + `torch.version.hip is None`)
- `AMD_GFX10` (desktop: `+rocm` wheel from TheRock `gfx103X-dgpu` index, OR an `ROCM_PATH` env var + a manually installed `+rocm` wheel, OR a HIP-built `llama.cpp` binary on PATH + an AMD vendor)
- `NONE` (no GPU driver or no compatible wheel — desktop with no ROCm install, laptop with no driver)

### Stage 2 — Burn test (the "this is real GPU, not silent CPU" check)

A cheap-but-real GPU kernel is run on the candidate backend. The output goes into `settings.json` as a `BackendProbeResult` so a future user-visible diagnostics panel can show it (Pitfall 12: "Settings says ROCM but every job runs on CPU" is the worst tell).

**Per-backend burn test:**

| Backend | Burn test | What proves it ran on the GPU |
|---|---|---|
| CUDA | `torch.randn(1024, 1024, device="cuda") @ torch.randn(1024, 1024, device="cuda")` then `torch.cuda.synchronize()` | Time the matmul; log ms. If `cudaGetLastError() != cudaSuccess` or the time is > 50 ms, treat as failure. |
| ROCm / HIP | Same code path — `torch.cuda` works on HIP. Same matmul + synchronize. | Same threshold; additionally assert `torch.version.hip is not None` to distinguish from a CUDA build that landed here by mistake. |
| llama.cpp HIP build (desktop fallback path) | Subprocess: `lemon-clip -m <test_gguf> -p "hi" -n 8 -ngl 99`, parse `total time` from stderr. | A `lemon-clip` binary on PATH that returns 0 and reports `n_gpu_layers=99, offloaded successfully` proves the ROCm path actually loaded weights onto the GPU. |
| CPU | Skip the burn test. | Recording the `Backend = CPU` result IS the proof; we don't have to prove a negative. |

**Source for the detect code location:** `app/models/backend.py` (already declared in ARCHITECTURE.md, Pitfall 1 says "Phase ownership: GPU-backend-detection phase").

**Critical correction to the prior research (Pitfall 1 was MEDIUM-LOW confidence on ROCm-on-Windows; in 2026 the path is real but specific):**

- Official AMD ROCm 7.2.1 wheels for Windows support only RDNA3 (`gfx1100/1101`) and RDNA4 (`gfx1200/1201`); they do NOT detect `gfx1030` (RX 6800/6800 XT/6900 XT). `HSA_OVERRIDE_GFX_VERSION=10.3.0` does not work on Windows.
- The only working path for `gfx1030` on Windows in mid-2026 is **TheRock nightly** wheels at `https://rocm.nightlies.amd.com/v2-staging/gfx103X-dgpu/`, currently shipping `torch-2.10.0+rocm7.12`. These are explicit about the `gfx103X-dgpu` target in the index URL. They support Python 3.10, 3.11, 3.12, 3.13 — so the project's locked Python 3.11 is fine.
- `faster-whisper` is CTranslate2-backed; CTranslate2 wheels on Windows do not ship ROCm. **faster-whisper on the desktop must use the CPU device** OR the project must build CTranslate2 from source with `-DWITH_HIPBLAS=ON` (PITFALLS.md already flagged this — Pitfall 1, 12). The realistic desktop STT path is whisper.cpp ROCm/HIP build (lemonade-sdk fork, see below), not faster-whisper.
- `llama.cpp` ROCm/HIP for Windows consumer RDNA2: `lemonade-sdk/llamacpp-rocm` ships nightly prebuilt `gfx103X` Windows binaries built with TheRock — b1280 as of May 2026. This is the path for the desktop LLM. The `lemon-clip` / `llama-server` binary carries ROCm 7 bundled, no separate ROCm install required.
- `whisper.cpp` ROCm/HIP for Windows: `lemonade-sdk/whisper.cpp-rocm` is the parallel fork. The official upstream merged ROCm support via PR #3823 in May 2026, but Windows HIP builds historically needed Ninja + ROCm's `clang/clang++` + the manual `rocblas.dll` / `hipblas.dll` / `rocblas/library` bundle. The fork does this CI-automatically.

**Confidence:** MEDIUM on the detect protocol shape (it's a well-known pattern); MEDIUM on the "gfx1030 TheRock nightly path works on the desktop today" claim (the spike is meant to confirm it). The 02-03 spike exists precisely to verify this on the user's actual desktop box.

## ROCm-on-Windows State (current as of mid-2026; fallback chain)

This is the load-bearing unknown flagged in STATE.md "Blockers/Concerns." The 02-03 spike deliverable captures what actually works on the user's box.

### What is real and usable in mid-2026

1. **PyTorch ROCm on Windows for `gfx1030`** — works, but ONLY via TheRock nightly wheels (`https://rocm.nightlies.amd.com/v2-staging/gfx103X-dgpu/`). Version 2.10.0+rocm7.12 as of May 2026. Python 3.11 / 3.12 / 3.13 supported. Source: AMD's TheRock RELEASES.md, TheRock issue #5175 (closed May 2026 after fixing CMake/MSVC flag conflict).
2. **llama.cpp ROCm/HIP on Windows for `gfx1030`** — works via the `lemonade-sdk/llamacpp-rocm` prebuilt `gfx103X` Windows binaries (b1280+ as of May 2026). ROCm 7 is bundled; no separate SDK install. Upstream `ggml-org/llama.cpp` PR #19810 (Feb 2026) added official Windows HIP builds as `llama-bXXXX-bin-win-hip-radeon-x64.zip`, though post-8149 builds have a device-discovery regression (issue #21106).
3. **whisper.cpp ROCm/HIP on Windows for `gfx1030`** — works via `lemonade-sdk/whisper.cpp-rocm` fork, which has a full Windows ROCm CI workflow. The fork uses Ninja Multi-Config + TheRock nightly + `amdclang.exe` / `amdclang++.exe` and bundles `amdhip64_*.dll`, `libhipblas.dll`, `rocblas.dll`, `rocsolver.dll`, `hipblaslt.dll`, plus `rocblas/library` and `hipblaslt/library` subfolders. Upstream PR #3757 (April 2026) is working to merge full ROCm Windows CI upstream.

### Fallback chain (what to do if the primary path fails)

| Failure | Fallback | Tradeoff |
|---|---|---|
| PyTorch ROCm wheel import fails on the desktop | Run STT + pyannote on CPU; LLM via `lemon-clip` ROCm path | STT is slow (CPU `faster-whisper` medium ~3-5x slower than RTX); LLM unaffected |
| `lemon-clip` ROCm path fails (device not visible) | Run LLM on CPU via `llama-cpp-python` with `n_gpu_layers=0` | LLM is slow (~5-15 t/s on 8-core Ryzen for 7B Q4_K_M) but works |
| Whisper.cpp HIP build won't load | Use faster-whisper CPU (CTranslate2 falls back to its own CPU path) | STT is slow; user must accept the CPU budget |
| All GPU paths fail | Mark `backend = CPU`; log loud; do not refuse to start | The user accepts the speed cost; the laptop CUDA path is the only "fast" path the user has |

**What "is this actually running on the GPU" looks like in code (per backend, the proof):**

| Backend | Library call | Proof of real-GPU |
|---|---|---|
| CUDA (torch) | `torch.matmul(a, b).item()` with `device='cuda'`, then `torch.cuda.synchronize()`, time it | If time < 50 ms on a 1024x1024 matmul, the kernel ran on the GPU. If time > 5 s, it fell back to CPU. |
| ROCm (torch) | Same code path (HIP is `torch.cuda` API) | Same threshold; also `torch.cuda.get_device_name(0)` must return a non-CPU device. |
| llama.cpp HIP | `lemon-clip -m tiny.gguf -p "x" -n 1 -ngl 99` then parse stderr for `llm_load_tensors: offloading X repeating layers to GPU` | If the offload log line is present, the weights went to GPU. If the log says `offloading 0 layers`, it's running on CPU silently. |
| CPU | Skip the burn test | The `Backend = CPU` record is the proof. |

## Settings Model Extensions (concrete Pydantic models, field list, restart-required vs hot-swap)

The Phase 1 `Settings` model has a single field `data_dir: str` (D-17). Phase 2 extends it. The YAGNI rule from D-17 says "Every other field gets added by the phase that needs it" — and Phase 2 needs the GPU/backend fields and the token field. The Phase 10 settings panel will need the preset / per-category override fields, and they should be **declared in the model now** so that a fresh boot on a new install writes them all (defaults populated), and the back-end can read them (even if no UI surfaces them). This avoids a future "Phase 10 had to add 4 new fields and re-version the on-disk format" change.

### `app/models/settings.py` — the Phase 2 target

```python
class GpuBackend(str, Enum):
    CUDA = "cuda"
    ROCM = "rocm"
    CPU  = "cpu"

class QualityPreset(str, Enum):
    SMALL = "small"
    BALANCED = "balanced"
    LARGE = "large"

class ModelCategory(str, Enum):
    STT = "stt"
    DIARIZE = "diarize"
    LLM = "llm"

class BackendProbe(BaseModel):
    """Result of the first-run GPU-burn test (Pitfall 1 / 12)."""
    model_config = ConfigDict(extra="forbid")
    backend: GpuBackend
    device_name: str            # e.g. "NVIDIA RTX 2000 Ada" or "AMD Radeon RX 6800 XT"
    driver_version: str | None  # from nvidia-smi or wmic; None on CPU
    vram_total_mb: int | None   # from torch.cuda.mem_get_info or None
    burn_test_ms: float | None  # matmul wall time; None on CPU
    probed_at: str              # ISO-8601 UTC; useful for "last verified" UI later
    notes: str                  # human-readable warnings ("HSA_OVERRIDE not used; GPU may be limited")

class ModelSpec(BaseModel):
    """One entry in a model set: an HF repo + a quantized variant."""
    model_config = ConfigDict(extra="forbid")
    repo_id: str                # "Systran/faster-whisper-large-v3"
    file: str | None            # for GGUF: the .gguf filename; for HF repos: None
    revision: str | None        # pinned commit SHA; None = HEAD
    expected_size_bytes: int | None
    expected_sha256: str | None # None for HF repos that don't publish per-file SHA

class ModelSet(BaseModel):
    """The default or per-category-overridden model triple."""
    model_config = ConfigDict(extra="forbid")
    stt: ModelSpec
    diarize: ModelSpec
    llm: ModelSpec

class Settings(BaseModel):
    """Persisted application settings (Phase 2 shape)."""
    model_config = ConfigDict(extra="forbid")
    data_dir: str                                              # from Phase 1
    backend: GpuBackend                                         # set by first-run detect
    backend_probe: BackendProbe | None = None                  # set by first-run burn test
    hf_token: str | None = None                                # pyannote gating (Pitfall 3)
    quality_preset: QualityPreset = QualityPreset.BALANCED     # HW-05
    per_category_overrides: ModelSet | None = None             # HW-06; null = use preset defaults
    concurrent_models: bool = False                             # HW-09 opt-in; SC-5
    vram_budget_fraction: float = 0.85                         # SC-4 default; float 0..1
```

### `UpdateSettingsRequest` — the Phase 2 target (strict input per D-15)

```python
class UpdateSettingsRequest(BaseModel):
    """Strict input for PATCH /settings (Phase 2).

    Mirrors Settings fields that the user (or a future settings panel)
    may change. ``backend`` and ``backend_probe`` are NOT user-editable
    (they are set by the detect/burn-test path); if the client sends
    them, the request is rejected with 422 (ConfigDict(extra="forbid")
    would already reject; we keep them out of the model entirely so
    the typed contract is explicit).
    """
    model_config = ConfigDict(strict=True, extra="forbid")

    data_dir: str | None = None                            # restart-required if changed (D-04, H1)
    hf_token: str | None = None                            # hot-swap (no model re-init needed)
    quality_preset: QualityPreset | None = None            # hot-swap (next model load reads it)
    per_category_overrides: ModelSet | None = None         # hot-swap (Phase 10 surfaces; Phase 2 accepts the field)
    concurrent_models: bool | None = None                  # hot-swap (SC-5)
    vram_budget_fraction: float | None = None              # hot-swap; range 0.1..0.95
```

**Re-detect backend API surface (not a field; a separate endpoint):**

```
POST /diagnostics/gpu-burn
   body: {}
   response: { "probe": BackendProbe, "active_backend": GpuBackend }
   side-effect: re-runs Stage 1 + Stage 2; updates settings.backend and settings.backend_probe
                atomically (D-04)
```

This is the hook the future settings panel uses when the user installs a new driver and wants to verify the new state. The response is the same `BackendProbe` shape so the front-end doesn't have to learn two types.

### Restart-required vs hot-swap (the field-by-field truth table)

| Field | Restart required? | Why |
|---|---|---|
| `data_dir` | YES (existing H1 path) | Engine, session factory, and on-disk paths are already built around it. |
| `backend` | NO (not user-editable) | Detection is one-shot at boot and via the re-detect endpoint. |
| `backend_probe` | NO (not user-editable) | Updated as a side-effect of the re-detect endpoint. |
| `hf_token` | NO | The token is read at the moment pyannote is next loaded; the next diarize job picks it up. |
| `quality_preset` | NO | Read at model-load time, not at boot. |
| `per_category_overrides` | NO | Same. |
| `concurrent_models` | NO | Boolean guard; checked at model-load time. |
| `vram_budget_fraction` | NO | Float; checked at model-load time. |

**Implementation note (extends Phase 1 H1):** The current `apply_update` is keyed on `data_dir` to decide restart-required. Phase 2 keeps the same `pending`-slot pattern for `data_dir` (no change) and adds hot-swap for everything else (same as the existing non-restart path: drop pending, atomic write, swap `_State.settings` in-memory). The `X-Restart-Required: true` response header is set only when `data_dir` is the changed field.

## Model Manager (interface, module location, SHA verify, resume, download log API)

### Module location and boundary

```
app/models/
  backend.py        # GpuBackend enum, detect(), burn_test() — already declared in ARCHITECTURE.md
  vram.py           # probe_vram() — torch + nvidia-smi + lemon-clip subprocess
  presets.py        # default model set + PRESETS table (QualityPreset -> ModelSet)
  registry.py       # Manifest of every model we know about; map id -> ModelSpec
  manager.py        # ModelManager: download, verify, lazy-load, unload (the big class)
  hf_token.py       # test_token() — one-shot dry-run for pyannote
```

`app/models/manager.py` is the only module that imports `huggingface_hub` (the boundary check: `grep -rE 'from huggingface_hub' app/` should only match `app/models/manager.py` and `app/models/hf_token.py`).

### Public interface (the typed contract for downstream phases)

```python
# app/models/manager.py
from typing import Protocol, AsyncIterator
from app.models.settings import ModelSpec, ModelCategory

class LoadedModel(Protocol):
    """A model that is currently in VRAM. Adapters wrap their concrete types in this."""
    spec: ModelSpec
    category: ModelCategory
    vram_bytes: int       # measured at load time
    loaded_at: float      # epoch seconds

class DownloadProgress(Protocol):
    model_id: str
    bytes_done: int
    bytes_total: int | None
    state: Literal["queued", "running", "verifying", "done", "failed", "resuming"]
    message: str | None  # human-readable, surfaced in UI

class ModelManager(Protocol):
    async def ensure_downloaded(self, spec: ModelSpec) -> Path: ...
    async def download_progress(self, spec: ModelSpec) -> DownloadProgress: ...
    async def load(self, category: ModelCategory) -> LoadedModel: ...
    async def unload(self, category: ModelCategory) -> None: ...
    async def unload_all(self) -> None: ...
    async def list_installed(self) -> list[ModelSpec]: ...
    def currently_loaded(self) -> list[LoadedModel]: ...
    async def verify(self, spec: ModelSpec) -> bool: ...
```

**Module-level singleton:** `_manager: ModelManager | None` plus `get_manager() -> ModelManager` and `configure_manager(m)`. The lifespan in `app/main.py` builds the singleton after `apply_pending`; routes that need it call `get_manager()`.

### Download + verify (the SHA + size + resume story)

The download flow uses `huggingface_hub` for HF-hosted files and a manual HTTP+Range implementation for non-HF sources (the GGUF for the LLM is on HF too, so this is not actually needed in v1 — but the abstraction supports it for Pitfall 13's "user swaps a model" path).

```python
# Pseudocode for ensure_downloaded
def ensure_downloaded(spec: ModelSpec, *, token: str | None) -> Path:
    target = data_dir / "models" / category / repo_id / file
    if target.exists() and spec.expected_size_bytes and target.stat().st_size == spec.expected_size_bytes:
        return target  # size match; skip SHA on the happy path (faster)
    if spec.expected_sha256 and not _sha256_matches(target, spec.expected_sha256):
        target.unlink(missing_ok=True)  # corrupt; re-download
    # hf_hub_download writes to <blob>.incomplete and resumes via Range header
    # (this is huggingface_hub >= 0.20 behavior; resume_download is deprecated
    # in 0.30 and the resume is automatic).
    hf_hub_download(
        repo_id=spec.repo_id,
        filename=spec.file or "model.bin",
        revision=spec.revision or "main",
        local_dir=target.parent,
        token=token,
        # resume is automatic; force_download=False is the default
    )
    if spec.expected_sha256 and not _sha256_matches(target, spec.expected_sha256):
        raise ModelIntegrityError(spec, expected=spec.expected_sha256, got=...)
    return target
```

**Key implementation facts** (from the huggingface_hub source review):

- The download function writes to `<blob>.incomplete` and uses an HTTP `Range` header to resume from the last byte on retry. This is the resume-after-crash guarantee.
- The cached file's path encodes the etag (which is the git-sha1 for non-LFS files, the sha256 for LFS files). For LFS files (the LLM GGUF is LFS), the on-disk file's content hash matches the etag.
- `GatedRepoError` is raised by `_raise_on_head_call_error` when the metadata HEAD returns 401 because the repo is gated and the token is missing/invalid. This is the pyannote path (Pitfall 3).
- For pyannote (`pyannote/speaker-diarization-3.1`), the error path is: the user has not added the HF token → `GatedRepoError` → the manager surfaces a typed `ModelGatedError(spec)` → the API returns 403 with a payload `{ "error": "gated", "repo": spec.repo_id, "fix": "add HF token in settings" }`.

### SHA / size verify

| Verify type | When done | What fails |
|---|---|---|
| Size check on resume | Before any re-download | If size matches the manifest, skip SHA (fast happy path). |
| SHA256 (if declared) | After download, before `LoadedModel` is returned | If mismatch, delete the file, raise `ModelIntegrityError`, re-raise into the API. The retry budget is bounded (default: 1 re-download, no infinite loop). |
| Verify-all endpoint | `POST /models/verify-all` (Phase 10 surfaces; Phase 2 exposes) | Walks every file in `data/models/`, reports pass/fail per file. |

**Where the manifest lives:** `app/models/registry.py` — a module-level `REGISTRY: dict[str, ModelSpec]` keyed by category. The Phase 10 settings panel will let the user add custom entries; the registry accepts arbitrary entries validated against the `ModelSpec` schema.

### Download log API (the surface the future UI calls)

The UI wants a live progress indicator. The protocol choice is **Server-Sent Events** over `/models/<id>/download-progress` (Phase 4 will use WebSocket for job progress, but for download progress, a one-way SSE stream is simpler and more cacheable):

```
GET /models/<id>/download-progress
   response: text/event-stream
   events:
     event: progress
     data: {"bytes_done": 412000000, "bytes_total": 1500000000, "state": "running", "message": "downloading"}
     event: progress
     data: {"bytes_done": 412000000, "bytes_total": 1500000000, "state": "verifying", "message": "sha256"}
     event: progress
     data: {"bytes_done": 1500000000, "bytes_total": 1500000000, "state": "done", "message": "ready"}
     # On error:
     event: progress
     data: {"state": "failed", "message": "GatedRepoError: add HF token"}
```

The Phase 2 back-end implements the SSE endpoint; the Phase 5 front-end consumes it. For v1 CI (no SSE client handy in `httpx`), a `GET /models/<id>/status` synchronous poll endpoint is the test-friendly equivalent — both share the same in-memory `DownloadProgress` state.

## VRAM Probing (the actual library calls, three backends)

The VRAM probe is the single source of truth for SC-4 ("Loading a model blocks if it would push past 85% of available VRAM"). The function lives in `app/models/vram.py` and is called by `ModelManager.load` *before* the model weights are moved to the device.

### Source of truth per backend

| Backend | Available VRAM | Currently in use | Library call |
|---|---|---|---|
| CUDA | `torch.cuda.mem_get_info(device)` → `(free, total)` | `torch.cuda.memory_allocated(device)` | PyTorch's `torch.cuda` API. |
| ROCm (HIP) | Same `torch.cuda.mem_get_info(device)` (HIP is `torch.cuda` API on `+rocm` wheels) | Same `torch.cuda.memory_allocated(device)` | Same PyTorch call; works on TheRock nightly wheels. |
| llama.cpp HIP (desktop fallback) | subprocess `lemon-clip --list-devices` parses `total memory` | `llama_get_state_size(ctx)` after init | Two separate pools from torch's — the model manager must call BOTH probes before declaring "this much is free." |
| CPU | RAM via `psutil.virtual_memory().available` (PyTorch is the only thing using it) | `psutil.Process(os.getpid()).memory_info().rss` | psutil is already a transitive dep on most Python installs; pin it if not. |
| CTranslate2 (faster-whisper CPU path) | Same as CPU | `psutil.Process(...).memory_info().rss` | CTranslate2 is its own memory pool, not torch. |

**The critical insight:** torch and llama.cpp have *separate* VRAM pools. The probe function for a CUDA-or-ROCm build must call BOTH `torch.cuda.memory_allocated()` (returns 0 if no torch model is loaded) AND a separate "is llama.cpp holding anything?" probe. The pitfall: load the LLM, then probe, the probe says "free" but the LLM is actually holding 5 GB. Fix: maintain a `manager._live_vram_bytes: dict[category, int]` updated at load/unload time, and add that to the "currently used" total.

### The probe function (shape)

```python
def probe_vram(backend: GpuBackend, manager_state: ManagerState) -> VRAMState:
    if backend == GpuBackend.CPU:
        return VRAMState(
            total_mb=int(psutil.virtual_memory().total / 1024**2),
            available_mb=int(psutil.virtual_memory().available / 1024**2),
            used_mb=int(psutil.Process(os.getpid()).memory_info().rss / 1024**2),
            pool=MemoryPool.CPU_RAM,
        )
    # CUDA or HIP — both go through torch.cuda API
    if not torch.cuda.is_available():
        return VRAMState(total_mb=0, available_mb=0, used_mb=0, pool=MemoryPool.NONE)
    device = torch.cuda.current_device()
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    torch_alloc_bytes = torch.cuda.memory_allocated(device)
    # llama.cpp may also be holding VRAM; sum the manager's known allocations
    llm_pool_bytes = sum(manager_state.live_vram_bytes.values())
    return VRAMState(
        total_mb=int(total_bytes / 1024**2),
        available_mb=int((free_bytes - llm_pool_bytes) / 1024**2),
        used_mb=int((torch_alloc_bytes + llm_pool_bytes) / 1024**2),
        pool=MemoryPool.GPU,
    )
```

**SC-4 enforcement:** `ModelManager.load(category)` calls `probe_vram` first, then asks "would loading this model push `used + estimated` past `vram_budget_fraction * total`?" If yes, raise `VramBudgetExceeded(category, needed_mb, available_mb)`, which the API returns as 507 (Insufficient Storage — semantically right) with a structured body. The estimated model size is the `expected_size_bytes` from the manifest, plus a 20% activations overhead for LLMs and a 50% overhead for STT (matches the STACK.md "8 GB laptop budget" math).

**Detection of the second-model opt-in:** `ModelManager.load` also checks "is another model already loaded in a non-CPU pool?" If yes and `concurrent_models=False`, raise `ConcurrentModelRefused(loaded_category, requested_category)`, which the API returns as 409 with a body the future UI can use to surface the "opt in to allow this" toggle (SC-5).

## Default Model Set + Quality Preset (typed structure, where it lives)

The default model set IS the data behind the future settings panel (Phase 10). Phase 2 declares it; Phase 10 exposes it.

### `app/models/presets.py` (the data)

```python
# Default model set per the ROADMAP and STACK.md (8 GB laptop fits, desktop can opt up).
BALANCED = ModelSet(
    stt=ModelSpec(
        repo_id="Systran/faster-whisper-large-v3",
        file=None,                                # HF repo, not a single file
        revision=None,                            # pin in a follow-up spike; v1 tracks HEAD
        expected_size_bytes=None,                 # HF repos don't have a single size; total tracked differently
        expected_sha256=None,
    ),
    diarize=ModelSpec(
        repo_id="pyannote/speaker-diarization-3.1",
        file=None,
        revision=None,                            # gated; gated-repo manifest in the registry
        expected_size_bytes=None,
        expected_sha256=None,
    ),
    llm=ModelSpec(
        repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",   # official Qwen2.5 GGUF
        file="qwen2.5-7b-instruct-q4_k_m.gguf",    # ~4.5 GB
        revision=None,
        expected_size_bytes=4_500_000_000,         # approximate; tracked
        expected_sha256=None,                      # add to manifest if HF provides per-file SHA
    ),
)

PRESETS: dict[QualityPreset, ModelSet] = {
    QualityPreset.SMALL: ModelSet(
        stt=ModelSpec("Systran/faster-whisper-small", ...),
        diarize=ModelSpec("pyannote/speaker-diarization-3.1", ...),
        llm=ModelSpec(repo_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
                      file="qwen2.5-3b-instruct-q4_k_m.gguf", ...),  # ~2 GB
    ),
    QualityPreset.BALANCED: BALANCED,
    QualityPreset.LARGE: ModelSet(
        stt=ModelSpec("Systran/faster-whisper-large-v3", ...),   # same as balanced
        diarize=ModelSpec("pyannote/speaker-diarization-3.1", ...),
        llm=ModelSpec(repo_id="Qwen/Qwen2.5-14B-Instruct-GGUF",
                      file="qwen2.5-14b-instruct-q4_k_m.gguf", ...),  # ~10 GB; desktop opt-in (HW-08)
    ),
}

def active_model_set(settings: Settings) -> ModelSet:
    """Resolve the active triple: per-category override > preset default."""
    preset = PRESETS[settings.quality_preset]
    overrides = settings.per_category_overrides
    if overrides is None:
        return preset
    return ModelSet(
        stt=overrides.stt or preset.stt,
        diarize=overrides.diarize or preset.diarize,
        llm=overrides.llm or preset.llm,
    )
```

**Why BALANCED is the default:** HW-07 ("Default model set fits the 8 GB laptop VRAM budget"). STACK.md's math: faster-whisper large-v3 int8 ≈ 2-2.5 GB on CUDA; pyannote 3.1 ≈ 1-2 GB; Qwen2.5-7B Q4_K_M ≈ 5 GB. With one-at-a-time semantics (SC-5), the largest single model is ~5 GB; with 85% of 8 GB = 6.8 GB as the budget, the LLM fits with ~1.8 GB of headroom (SC-2, SC-4).

**Per-model VRAM budget log on load** (SC-2): `ModelManager.load` emits a structured log line at INFO with `{category, model_id, expected_vram_mb, measured_vram_mb_after_load, total_vram_mb, available_vram_mb_after_load}`. The log line is JSON-shaped so a future diagnostics panel can parse it without a regex.

## HF Token Gating (storage, "test token" pattern)

### Storage

- Field: `Settings.hf_token: str | None` (already declared above).
- On disk: lives in `settings.json` alongside everything else, **base64-encoded** to make accidental "share my settings.json" mistakes not leak the token in cleartext. Decoded at read time; the Pydantic model's `field_validator` decodes and the serializer encodes. The token is **not** exported to OpenAPI components as a settable field (the response is lax; the field is omitted from `UpdateSettingsRequest`).
- Future v2: a separate `secrets.json` (with `0600` perms; not on disk in `data/`) is the right place if export-to-share ever lands. Phase 2's `base64-in-settings.json` is the v1 simple answer.

### The "test token" pattern (one-shot dry-run)

`POST /diagnostics/test-hf-token` (no body) — the route loads `pyannote/speaker-diarization-3.1` config and makes one HEAD call to HF Hub. The result is one of:

| Result | HTTP | Response body |
|---|---|---|
| No token in settings | 200 | `{"status": "skipped", "reason": "no token configured"}` |
| Token valid + user has accepted the model terms | 200 | `{"status": "ok", "user": "<hf username>"}` |
| Token valid but terms not accepted | 403 | `{"status": "rejected", "reason": "model terms not accepted", "fix": "visit https://huggingface.co/pyannote/speaker-diarization-3.1"}` |
| Token invalid | 401 | `{"status": "rejected", "reason": "token invalid"}` |

The route is the same one Phase 7's "Test token" button will call and the same one Phase 10's settings panel calls. It does NOT download any weights — it's a metadata HEAD call (`huggingface_hub.hf_hub_url(...).HEAD`), so it's cheap.

**Token-present-but-invalid does NOT block the app** (Pitfall 3): the banner says "Speaker labels disabled" and jobs without diarization still complete. The token test endpoint is for the user's confidence, not a precondition.

## 02-03 Spike Deliverable (what gets written, what shape, how it informs Phase 3)

The 02-03 spike is a documentation deliverable, not an implementation. The output is `02-03-SPIKE.md` in the phase directory, capturing the answers to three questions so Phase 3 (STT adapter) can pick the right engine on the first try.

### Required sections of `02-03-SPIKE.md`

1. **Target environment (desktop).** The exact box the spike ran on: GPU model, driver version, `pip show torch` output (which wheel), `pip show ctranslate2` output, OS build.
2. **The path that works.** A markdown table with one row per backend option, one column per dimension (install command, works Y/N, observed tokens/sec, observed VRAM at peak). The "works Y/N" column is the verdict.
3. **The fallback decision.** A single-paragraph statement: "For the desktop, we use [X] for STT, [Y] for LLM, [Z] for pyannote." This paragraph is what Phase 3 reads before writing the STT adapter.
4. **Pitfalls hit during the spike.** Anything that surprised the user during install. Examples: the TheRock nightly wheel URL changed, the `lemon-clip` binary needs `rocblas/library` next to it, the WMI call returned 0 results because PowerShell was blocked. These become tasks for future phases or for the user.
5. **What Phase 3 must do.** A short list of "STT adapter must..." requirements derived from the spike. Example: "STT adapter must accept a `device: Literal['cuda', 'cpu', 'rocm']` arg because faster-whisper's `device='cuda'` is the right call on the TheRock wheel."

### How the spike is structured in plans

The 02-03 plan is a single deliverable: run the spike, write the markdown, no code. The plan does not ship without a signed verdict (the file either says "this works" or "this does not work, fall back to X").

## Validation Architecture (per-SC testable observable)

For each of the 5 success criteria, the testable observable is the assertion a test makes against the in-process app (no real GPU, no real HF download — all mocked at the seam boundaries).

### Test framework: pytest + pytest-asyncio + httpx.ASGITransport
(Reuses the Phase 1 fixture pattern from `tests/conftest.py`. Every Phase 2 test gets a fresh `tmp_data_dir` + a wired-up app via `app_under_test` + an `httpx.AsyncClient`.)

### SC-1 — "First run on the laptop silently writes `settings.json` with `backend: CUDA`; first run on the desktop writes `backend: ROCM` or `CPU` based on a real GPU-burn test."

| Aspect | Value |
|---|---|
| Observable | Boot, then `GET /settings` returns `{"backend": "cuda", "backend_probe": {"device_name": "NVIDIA RTX 2000 Ada", ...}}`. |
| Test seam | Mock `app.models.backend.detect()` to return `GpuBackend.CUDA`; mock `app.models.backend.burn_test()` to return a fixed `BackendProbe`. |
| Assertion | `GET /settings` → `200 OK`, body parsed as `Settings`; `backend == GpuBackend.CUDA`, `backend_probe.device_name == "NVIDIA RTX 2000 Ada"`. The on-disk `data/settings.json` was written by the lifespan; re-read it from disk and assert the same. |
| Isolation | No torch, no nvidia-smi, no GPU. The detect function is the seam; tests don't import the real one. |
| Test file | `tests/test_gpu_detect.py::test_first_run_writes_settings_with_cuda_backend` |

A second test for SC-1: the desktop case, mock `detect()` to return `GpuBackend.ROCM`, `burn_test()` to return a 6800 XT probe. Assert the same on-disk shape.

A third test for SC-1: the no-GPU case. Mock `detect()` to return `GpuBackend.CPU`. Assert `backend_probe.burn_test_ms is None` and `backend_probe.vram_total_mb is None`.

### SC-2 — "Default model set (faster-whisper int8 large-v3 + pyannote + Qwen2.5 7B Q4_K_M) fits within 8 GB laptop VRAM as a planning constraint, with per-model VRAM budget logged on load."

| Aspect | Value |
|---|---|
| Observable (a) | `app.models.presets.PRESETS[QualityPreset.BALANCED]` is a `ModelSet` with the three spec entries. |
| Observable (b) | `ModelManager.load(category)` emits the structured log line with the expected fields and a non-negative `measured_vram_mb_after_load`. |
| Test seam (a) | Direct unit test on the presets module; no I/O. |
| Test seam (b) | Mock `app.models.vram.probe_vram()` to return a fixed `VRAMState(total_mb=8192, used_mb=0)`. The `load` function checks the model spec's expected size against `0.85 * 8192 = 6963 MB`. The mock-loaded model reports back `vram_bytes=500 * 1024 * 1024` (500 MB). |
| Assertion (a) | `PRESETS[BALANCED].stt.repo_id == "Systran/faster-whisper-large-v3"`; `llm.file == "qwen2.5-7b-instruct-q4_k_m.gguf"`. |
| Assertion (b) | A captured log line contains the substring `"vram_budget_mb=6963"` and the measured VRAM matches the mock. |
| Isolation | No real model loaded; no GPU. |
| Test file | `tests/test_presets.py` (the table test) and `tests/test_manager_load.py` (the VRAM log test). |

### SC-3 — "Model manager downloads a model, verifies size and (where available) SHA256, exposes a download log in the UI, and supports resume after crash."

| Aspect | Value |
|---|---|
| Observable | `ModelManager.ensure_downloaded(spec)` writes the file at the expected path, the on-disk file's size matches `spec.expected_size_bytes`, and if `spec.expected_sha256` is set, the file's SHA matches. A `GET /models/<id>/status` returns a `DownloadProgress` with `state="done"`. After simulating a crash mid-download (delete the `.incomplete` file, leave a partial file at the target path), the next `ensure_downloaded` call resumes (does NOT re-download from 0). |
| Test seam (a) | Mock `huggingface_hub.hf_hub_download` to a function that writes a fake file with a known SHA at the target path. |
| Test seam (b) | For the resume test, set up the `tmp_data_dir` with a partial file at the target (size = half of expected); assert the next call to `ensure_downloaded` does NOT call `hf_hub_download` with `force_download=True` and the file is now full-size with correct SHA. |
| Assertion (a) | `target.exists()`, `target.stat().st_size == spec.expected_size_bytes`, `_sha256(target) == spec.expected_sha256` when set. |
| Assertion (b) | `GET /models/<id>/status` returns 200 with `state="done"`, `bytes_done == bytes_total`. |
| Assertion (c) | Resume test: spy on `hf_hub_download`; the second call did NOT use `force_download=True`. |
| Isolation | No HF Hub, no real network. |
| Test file | `tests/test_manager_download.py::test_ensure_downloaded_size_and_sha`; `tests/test_manager_download.py::test_resume_after_crash`; `tests/test_manager_api.py::test_get_model_status_after_download`. |

### SC-4 — "Loading a model blocks if it would push past 85% of available VRAM; unload is explicit on idle, with a 'what's currently in VRAM' indicator exposed for diagnostics."

| Aspect | Value |
|---|---|
| Observable (a) | A `ModelManager.load(category)` for a model that would push past `vram_budget_fraction * total` raises `VramBudgetExceeded`, which the API surfaces as 507. |
| Observable (b) | `GET /diagnostics/vram` returns `{"total_mb": int, "available_mb": int, "used_mb": int, "loaded": [{"category": "stt", "model_id": "...", "vram_mb": int}]}`. |
| Observable (c) | `ModelManager.unload(category)` clears the loaded entry; the diagnostics endpoint reflects this. |
| Test seam | Mock `probe_vram` to return `VRAMState(total_mb=8192, used_mb=0)`. The "load the 7B LLM" call sees `needed = 5 * 1024`, budget = `0.85 * 8192 = 6963`, asserts `5*1024 < 6963` → load succeeds. The "load a 10 GB model on a 4 GB pool" test: `used_mb=2000`, `needed=10000`, budget = `0.85 * 4096 = 3482`, asserts the refusal. |
| Assertion (a) | `with pytest.raises(VramBudgetExceeded)`. |
| Assertion (b) | `GET /diagnostics/vram` returns 200; `loaded[0].vram_mb > 0`. |
| Assertion (c) | After `await manager.unload(ModelCategory.STT)`, `GET /diagnostics/vram` returns `loaded=[]`. |
| Isolation | No GPU; no model loaded. |
| Test file | `tests/test_vram_budget.py::test_load_refuses_when_budget_exceeded`; `tests/test_vram_budget.py::test_diagnostics_vram_reflects_loaded_models`; `tests/test_vram_budget.py::test_unload_clears_loaded_entry`. |

### SC-5 — "No two models are resident in VRAM concurrently unless the user explicitly opts in via a settings toggle that is hidden by default."

| Aspect | Value |
|---|---|
| Observable (a) | With `concurrent_models=False` (the default), a second `load(category_b)` after a `load(category_a)` raises `ConcurrentModelRefused`. |
| Observable (b) | With `concurrent_models=True` (set via PATCH /settings), the second load succeeds. |
| Observable (c) | The OpenAPI schema for `UpdateSettingsRequest` includes `concurrent_models` as a settable field. |
| Test seam (a) | Mock `probe_vram` to always return a budget that allows the first load and would also allow the second (so the only reason to refuse is SC-5's policy, not VRAM). |
| Assertion (a) | `await manager.load(STT)` then `await manager.load(LLM)` raises `ConcurrentModelRefused`. |
| Assertion (b) | `PATCH /settings {"concurrent_models": true}` → 200; `await manager.load(LLM)` succeeds. |
| Assertion (c) | `GET /openapi.json` has `concurrent_models: bool` in `components.schemas.UpdateSettingsRequest.properties`. |
| Test file | `tests/test_concurrent_models.py::test_default_refuses_second_model`; `tests/test_concurrent_models.py::test_opt_in_allows_second_model`; `tests/test_concurrent_models.py::test_concurrent_models_in_openapi`. |

### Nyquist test map (per-requirement table)

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HW-02 | Models run on user's GPU | smoke (per-backend detect) | `pytest tests/test_gpu_detect.py -q` | Wave 0 |
| HW-03 | Auto-detect CUDA vs ROCm vs CPU | unit | `pytest tests/test_gpu_detect.py -q` | Wave 0 |
| HW-04 | App downloads its own models | unit | `pytest tests/test_manager_download.py -q` | Wave 0 |
| HW-07 | Default model set fits 8 GB | unit (presets) | `pytest tests/test_presets.py -q` | Wave 0 |
| HW-09 | Per-job VRAM discipline | unit + smoke | `pytest tests/test_vram_budget.py tests/test_concurrent_models.py -q` | Wave 0 |

### Sampling rate

- **Per task commit:** `pytest tests/test_gpu_detect.py tests/test_presets.py tests/test_manager_download.py tests/test_vram_budget.py tests/test_concurrent_models.py tests/test_settings.py -q` (~30 s)
- **Per wave merge:** full suite `pytest -q` (target: under 60 s; 113 tests in Phase 1 ran in ~6 s; Phase 2 adds ~25 tests, budget ~15 s)
- **Phase gate:** full suite green before `/gsd-verify-phase 2`

### Wave 0 gaps (what must exist before any Phase 2 implementation task)

- [ ] `tests/test_gpu_detect.py` — covers SC-1 (CUDA, ROCm, CPU variants)
- [ ] `tests/test_presets.py` — covers SC-2 (BALANCED model set is the right triple)
- [ ] `tests/test_manager_download.py` — covers SC-3 (size, SHA, resume)
- [ ] `tests/test_vram_budget.py` — covers SC-4 (refusal, diagnostics, unload)
- [ ] `tests/test_concurrent_models.py` — covers SC-5 (default refuse, opt-in allow)
- [ ] `tests/test_settings_phase2.py` — covers new `Settings` fields round-trip; strict `UpdateSettingsRequest` rejects `backend` and `backend_probe` (not user-editable)
- [ ] `tests/test_hf_token.py` — covers the test-token endpoint (no token, valid token, invalid token, gated-repo-with-terms-not-accepted)
- [ ] `tests/test_diagnostics_api.py` — covers `POST /diagnostics/gpu-burn`, `GET /diagnostics/vram`, `GET /models`, `GET /models/{id}/status`
- [ ] `app/models/__init__.py` — exports the new modules
- [ ] `app/api/routes_diagnostics.py` — new router for diagnostics endpoints
- [ ] `app/api/routes_models.py` — new router for model endpoints
- [ ] `requirements.txt` updates — pin `huggingface_hub >= 0.20`, `faster-whisper >= 1.0`, `llama-cpp-python >= 0.2` (note: `pyannote.audio` and `torch` come later; Phase 2 has a `pyannote` SHIM that returns a "not yet wired" result for the test-token endpoint, and the real pyannote import is gated to the diarize stage in Phase 7)
- [ ] `pyproject.toml` / dev deps — `pytest-asyncio`, `httpx`, `pytest-mock` (all already present from Phase 1)

## API Endpoints Added (method, path, request/response shape, who calls it)

All endpoints are loopback-only (`127.0.0.1`); no auth; CORS allows the Vite dev origin (`http://localhost:5173`).

### `GET /settings` — extended response (no new fields in request)

| Aspect | Value |
|---|---|
| Method | `GET` |
| Path | `/settings` |
| Response | `200` with the `Settings` model (lax output per D-15) including the new fields (`backend`, `backend_probe`, `hf_token` is `None` in the response unless `?reveal=true` is set, even then, only the last-4-chars are shown — actually for v1 simplicity, **always** return `hf_token: null` in the response, never the cleartext token; the field exists in the on-disk file and in the request body, never in the response). |
| Caller | Phase 5 front-end settings panel (Phase 10 surfaces the panel). |

### `PATCH /settings` — extended request shape

| Aspect | Value |
|---|---|
| Method | `PATCH` |
| Path | `/settings` |
| Request body | `UpdateSettingsRequest` (strict input, new fields) |
| Response | `200` with the new in-memory `Settings`. `X-Restart-Required: true` if `data_dir` changed. |
| Caller | Phase 10 settings panel; also `POST /diagnostics/test-hf-token` updates `hf_token` indirectly. |

### `GET /models` — list installed + planned models

| Aspect | Value |
|---|---|
| Method | `GET` |
| Path | `/models` |
| Response | `{"installed": [ModelSpec...], "available": [ModelSpec...], "active_set": ModelSet}` where `installed` is what is on disk in `data/models/`, `available` is the registry + the active preset, `active_set` is `active_model_set(settings)`. |
| Caller | Phase 10 settings panel "Models" page. |

### `POST /models/{id}/download` — kick off a download

| Aspect | Value |
|---|---|
| Method | `POST` |
| Path | `/models/{id}/download` (the `id` is `"<category>:<repo_id>:<file>"` or a registry short name like `"balanced.llm"`). |
| Response | `202 Accepted` with `{"task_id": "<uuid>", "status_url": "/models/{id}/status"}`. The download runs in the background (a single `asyncio.create_task` is enough for v1; the orchestrator in Phase 4 will pick this up). |
| Caller | Phase 10 settings panel. |

### `GET /models/{id}/status` — current download state (poll)

| Aspect | Value |
|---|---|
| Method | `GET` |
| Path | `/models/{id}/status` |
| Response | `200` with `DownloadProgress` (`{state, bytes_done, bytes_total, message}`). |
| Caller | Phase 5 front-end; in v1 CI, this is the test-friendly endpoint. The SSE variant below is the same data over a stream. |

### `GET /models/{id}/download-progress` — SSE stream (Phase 5 will use this)

| Aspect | Value |
|---|---|
| Method | `GET` |
| Path | `/models/{id}/download-progress` |
| Response | `text/event-stream`; one event per state change + a heartbeat every 5 s. Event payload is the same `DownloadProgress` JSON. |
| Caller | Phase 5 front-end via `EventSource`. |

### `POST /models/{id}/load` and `POST /models/{id}/unload`

| Aspect | Value |
|---|---|
| Method | `POST` |
| Path | `/models/{id}/load` and `/models/{id}/unload` |
| Response (load) | `200` with `{"category": "...", "model_id": "...", "vram_mb": int, "loaded_at": iso}`. `507 Insufficient Storage` on budget exceeded. `409 Conflict` on `ConcurrentModelRefused` (SC-5). `403 Forbidden` on gated-repo-with-no-valid-token. |
| Response (unload) | `204 No Content`. Idempotent (unloading an unloaded category is 204). |
| Caller | Phase 4 orchestrator (loads the STT model before each transcribe stage; unloads after). Phase 10 settings panel "Test" button. |

### `GET /diagnostics/vram` — what's currently in VRAM

| Aspect | Value |
|---|---|
| Method | `GET` |
| Path | `/diagnostics/vram` |
| Response | `{"backend": GpuBackend, "total_mb": int, "available_mb": int, "used_mb": int, "loaded": [{"category": "...", "model_id": "...", "vram_mb": int, "loaded_at": iso}]}`. |
| Caller | Phase 10 settings panel "Diagnostics" page; also the future "what's in VRAM" indicator (SC-4). |

### `POST /diagnostics/gpu-burn` — re-run the first-run detect

| Aspect | Value |
|---|---|
| Method | `POST` |
| Path | `/diagnostics/gpu-burn` |
| Response | `200` with `{"probe": BackendProbe, "active_backend": GpuBackend, "settings_written": true}`. The settings file is updated atomically (D-04) with the new `backend` and `backend_probe`. |
| Caller | Phase 10 settings panel "Re-detect GPU" button. |

### `POST /diagnostics/test-hf-token` — one-shot dry-run for the pyannote token

| Aspect | Value |
|---|---|
| Method | `POST` |
| Path | `/diagnostics/test-hf-token` |
| Response | See the four-state table in §HF Token Gating above. |
| Caller | Phase 7 (Diarize banner "Add token" link); Phase 10 settings panel "Test token" button. |

**What the API does NOT add in Phase 2:** no `/jobs` extensions, no WebSocket changes, no model-list-editing (Phase 10). The route surface is the minimum the back-end needs to serve the future UI and the minimum the test suite needs to cover SC-1..SC-5.

## Pitfall Traceability (which D-numbered decisions / Pitfall 1/2/3/4/12 each choice mitigates)

| Design choice | Mitigates | How |
|---|---|---|
| Two-stage detect (probe + burn test) | PITFALLS.md Pitfall 1, Pitfall 12 | A real kernel run, not just `torch.cuda.is_available()`, proves the path actually uses the GPU. |
| Backend result written to `settings.json` after the burn test, not after a `pip show` alone | Pitfall 12 | "Settings says ROCM but jobs run on CPU" is impossible if the settings value is the result of a successful burn test. |
| `lemon-clip --list-devices` for the desktop llama.cpp path | Pitfall 1 | The `n_gpu_layers=99, offloaded X layers` log line is the proof; no silent CPU fallback. |
| `torch.cuda.mem_get_info` + `manager._live_vram_bytes` sum | Pitfall 2 | The two-pool problem (torch vs llama.cpp) is explicit; the probe can't lie about free VRAM. |
| 85% budget default (`vram_budget_fraction`) | Pitfall 2 | SC-4's "would push past 85% of available VRAM" check. |
| Single-model-at-a-time default with explicit `concurrent_models: bool` opt-in | Pitfall 2 | SC-5's "hidden by default" toggle. The default is the safe behavior on 8 GB. |
| Per-model VRAM log line on load (structured JSON) | Pitfall 2 | The user can grep for which model is the budget hog. |
| HF token optional, banner-on-absence, no app-block | PITFALLS.md Pitfall 3 | The first-run UX is silent; the pyannote failure mode is "diarization disabled, transcript still works" (per STACK.md). |
| `huggingface_hub`'s built-in `<blob>.incomplete` resume | PITFALLS.md Pitfall 4 | The library already implements the Range-header resume; we don't reinvent. |
| SHA256 verify against `ModelSpec.expected_sha256` when set | Pitfall 4 | "Model load throws `unexpected EOF`" is the failure mode; the SHA check catches it before the user sees it. |
| Download log as an SSE stream + a poll endpoint | Pitfall 4 | The user sees "downloading 4.2 / 7.8 GB" in the UI; the 0/s-for-minutes stall is visible. |
| Bounded retry on integrity check (1 re-download, no loop) | Pitfall 4 | A poison manifest can't hang the app forever. |
| `concurrent_models: bool` typed in `Settings` but default `False` | Pitfall 2 + HW-09 | The 8 GB laptop is the default state. Desktop opt-in is a single boolean, not a code change. |
| Per-category model override as data, not code | Pitfall 13 | Swapping Whisper for a faster/smaller variant is a settings change, not a code change (HW-06). |
| `data/models/` path resolved from `settings.data_dir` (not hard-coded) | Pitfall 4 | Spaces-in-path HF client edge cases are sidestepped because the data dir is a project-controlled absolute path. |
| Settings has `extra="forbid"` (D-15) and `UpdateSettingsRequest` has `ConfigDict(strict=True, extra="forbid")` | D-15, Pitfall 10 (FE/BE drift) | Unknown fields are 422'd at the boundary; `openapi-typescript` codegen sees the same model. |
| `Restart-Required` only fires on `data_dir` change (H1) | H1 carryover | No false-positive restart prompts when the user toggles `concurrent_models` or sets an HF token. |
| `backend` and `backend_probe` are NOT in `UpdateSettingsRequest` (only in the response) | API surface honesty | The user cannot send a fake `backend: "cuda"` and trick the app into claiming a GPU is active. |

## Open Questions (RESOLVED)

1. **Should Phase 2 actually import `pyannote.audio`?** **RESOLVED:** Yes — Phase 2 ships a HF-token-test SHIM (no `pyannote.audio` import); real pyannote lands in Phase 7. Locked by CONTEXT domain boundary ("Out of scope for Phase 2: ... real `pyannote.audio` import (Phase 7 — Phase 2 ships a HF-token-test SHIM)"). Pyannote is a heavy dependency that pulls `torch` (the TheRock nightly wheel is the only Windows option for the desktop). Phase 2 only needs the **HF token test** path, which is a HEAD call to HF Hub and does not need pyannote imported. **Recommendation:** add a `pyannote` SHIM (a thin function in `app/models/hf_token.py` that does the HEAD call directly via `huggingface_hub.hf_hub_url`) and defer the real `pyannote.audio` import to Phase 7. This means Phase 2's `requirements.txt` only needs `huggingface_hub` and the test-token mocks out the HEAD call. The real pyannote import lands in Phase 7 with the diarize adapter.
2. **Should the 02-03 spike produce a `runtime.json` artifact in the data dir** **RESOLVED:** No — markdown report is enough; `settings.backend_probe` already records the probe. Locked by CONTEXT deferred list ("`data/runtime/rocm_probe.json` runtime artifact from the spike — YAGNI"). (e.g. `data/runtime/rocm_probe.json`) that the next boot reads, or is the markdown report enough? **Recommendation:** enough. The on-disk `settings.json` already records `backend_probe`; a separate runtime artifact is YAGNI.
3. **What is the exact `n_gpu_layers` for llama-cpp-python on the TheRock nightly wheel?** **RESOLVED:** Deferred to 02-03 spike time on the user's box. Locked by CONTEXT deferred list ("Exact `n_gpu_layers` for the desktop llama.cpp HIP path — re-verify at 02-03 spike time on the user's box"). The wheel that the project installs for the desktop is the project's choice (CUDA laptop = `+cu` wheel from `https://download.pytorch.org/whl/cu12x`; desktop = TheRock nightly for gfx1030 OR `lemon-clip` binary). For the in-process llama.cpp path on the desktop, the question is: do we use `llama-cpp-python` Python wheel built with HIPBLAS, or do we shell out to the `lemon-clip` binary? **Recommendation:** shell out to `lemon-clip` on the desktop (its ROCm 7 + gfx103X is a single prebuilt artifact with no Python rebuild step); use `llama-cpp-python` with `n_gpu_layers=99` on the laptop (the cuBLAS build is a single `pip install`).
4. **What is the `expected_size_bytes` for the Qwen2.5-7B Q4_K_M GGUF?** **RESOLVED:** Leave `expected_sha256=None` per CONTEXT deferred list ("`expected_size_bytes` / `expected_sha256` for the Qwen2.5-7B GGUF — leave `None` in `presets.py`, re-verify actual file size from HF at registry-build time in plan 02-02"). The 4.5 GB approximation in `registry.py` is acceptable for Phase 2 VRAM budget math (see CONTEXT deferred note update). A 4.5 GB approximation is in `presets.py`; the actual file size from HF should be re-verified at the registry-build time (Phase 2 plan 02-02 includes a small "list the registry sizes" step that hits HF to get the actual numbers). The Phase 2 plan can use a `None` here and only check size on the FIRST download (defer to plan 02-02's verification step).
5. **Does the user want the `hf_token` stored in `settings.json` (base64) or in a separate `secrets.json` (chmod 0600) right now?** **RESOLVED:** base64-in-settings for v1; `secrets.json` deferred to v2. Locked by D-05 ("The HuggingFace token is stored base64-encoded inside `settings.json` (v1)..."). v1 says base64 in settings; v2 says secrets.json. **Recommendation:** base64-in-settings for v1; the path forward is a clean refactor in v2 if needed. The base64 is not security, it's "no accidental cleartext in a `cat settings.json`." The user can confirm at plan time.

## Architectural Notes for the Planner (Re: Existing 02-01, 02-02, 02-03 Slots)

The three existing plan slots in ROADMAP.md are sensible and need no re-grouping. Each plan's scope:

- **02-01 (First-run GPU detect + burn-in test + settings.json write):** `app/models/backend.py` (GpuBackend, detect, burn_test) + `app/models/vram.py` (probe_vram) + lifespan hook + new `Settings` fields (`backend`, `backend_probe`, `hf_token`, `quality_preset`, `per_category_overrides`, `concurrent_models`, `vram_budget_fraction`) + the strict `UpdateSettingsRequest` extension + 2-3 routes (`POST /diagnostics/gpu-burn`, `POST /diagnostics/test-hf-token`, extended `GET /settings`, extended `PATCH /settings`). Wave 0 gap closure: `tests/test_gpu_detect.py`, `tests/test_settings_phase2.py`, `tests/test_hf_token.py`.
- **02-02 (Model manager — download, verify, lazy load, idle unload, VRAM probe):** `app/models/registry.py` (manifest) + `app/models/presets.py` (the BALANCED default) + `app/models/manager.py` (the big class) + `app/models/hf_token.py` (the shim) + the model API routes (`/models`, `/models/{id}/download`, `/models/{id}/status`, `/models/{id}/download-progress`, `/models/{id}/load`, `/models/{id}/unload`) + `GET /diagnostics/vram`. Wave 0 gap closure: `tests/test_presets.py`, `tests/test_manager_download.py`, `tests/test_vram_budget.py`, `tests/test_concurrent_models.py`, `tests/test_diagnostics_api.py`.
- **02-03 (ROCm-on-Windows spike):** a single deliverable: `02-03-SPIKE.md` capturing what was tried, what worked, and the fallback decision. No code in this plan (the code lives in 02-01 and 02-02); the spike is the *evidence* that the code targets the right thing.

The only re-grouping the researcher would suggest (not required, just an observation): if 02-03 is done FIRST on the actual desktop, 02-01's detect function can target the real paths. Otherwise 02-01 ships a detect function that handles "TheRock nightly present" and "lemon-clip binary on PATH" as first-class signals, and 02-03 confirms or refines. **Recommended ordering:** 02-01 → 02-02 → 02-03 (in that order) is what ROADMAP says; the researcher concurs because 02-03 has no code dependencies on 02-01/02-02, and 02-01/02-02 ship with the *documented* path (which the spike is meant to *verify*).

## Environment Availability (audited, not skipped)

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | All Phase 2 code | ✓ (project-locked) | 3.11.x | — (project constraint) |
| pytest + pytest-asyncio + httpx | Test suite | ✓ (Phase 1) | pytest 7.x, pytest-asyncio 0.23+, httpx 0.27+ | — |
| pydantic v2 | Settings model | ✓ (Phase 1) | 2.x | — |
| `huggingface_hub` | Model download + HF token test | Will install in plan 02-02 | `>= 0.20` (recommend `>= 0.25` for the resume-deprecation warning suppression) | — |
| `faster-whisper` | STT (Phase 3) | Will install in Phase 3 | `>= 1.0` | — |
| `pyannote.audio` | Diarize (Phase 7) | Will install in Phase 7 | `>= 3.1` | SHIM in Phase 2 |
| `llama-cpp-python` | LLM (Phase 8) | Will install in Phase 8 | `>= 0.2` | — |
| `torch` | Detect + burn test | Will install in plan 02-01 | `+cu` for laptop, TheRock `+rocm` for desktop | CPU-only path |
| `nvidia-smi` | Burn test on laptop | Expected (NVIDIA driver ships it) | — | None (laptop has it) |
| `lemon-clip` (lemonade-sdk/llamacpp-rocm) | Desktop LLM verification | TBD (spike 02-03) | — | `pip show llama-cpp-python` as evidence |
| `psutil` | CPU VRAM probe | Likely transitive; verify | — | `pip install psutil` in plan 02-01 |

**Missing dependencies with no fallback:**
- The TheRock nightly `gfx103X-dgpu` wheel URL is the SOLE path for the desktop; if it disappears, the desktop falls to CPU. The 02-03 spike is exactly meant to catch this. **Documented as a project risk in the spike output.**

**Missing dependencies with fallback:**
- `lemon-clip` binary on the desktop has a fallback: `pip install llama-cpp-python` built without HIP. This is the slower path but works.

## Sources

### Primary (HIGH confidence)

- `huggingface_hub` v0.30.x source — `_snapshot_download.py`, `file_download.py` (resume via `.incomplete` + Range header, `GatedRepoError` from `errors.py`, sha256 etag for LFS files). [VERIFIED via WebSearch + GitHub]
- `faster-whisper` v1.x — `WhisperModel(name, device, compute_type)` API; `large-v3 + int8` VRAM ≈ 2.0-2.5 GB on CUDA per the official SYSTRAN benchmark + the `groxaxo/large-v3-int8-faster-whisper` production fork data. [VERIFIED via WebSearch]
- `llama-cpp-python` v0.2/v0.3 — `Llama(model_path, n_gpu_layers, n_ctx, use_mlock)`; 7B Q4_K_M GGUF ≈ 4.5 GB VRAM + ~0.5 GB CUDA context. [VERIFIED via WebSearch]
- `torch.cuda.mem_get_info(device)` — returns `(free_bytes, total_bytes)`; works on both CUDA and HIP (`+rocm`) builds; on Windows the HIP path requires the TheRock nightly `gfx103X-dgpu` wheel. [VERIFIED via WebSearch + PyTorch docs]
- Pydantic v2 `ConfigDict(strict=True, extra="forbid")` — the strict-input model contract from D-15. [VERIFIED via the existing Phase 1 code in `app/models/settings.py:40`]

### Secondary (MEDIUM confidence)

- TheRock nightly `gfx103X-dgpu` index URL and Python version support matrix (Python 3.10, 3.11, 3.12, 3.13). The project's locked 3.11 is supported. [VERIFIED via TheRock RELEASES.md + ssubedir/RCOm-windows-gfx1030]
- `lemonade-sdk/llamacpp-rocm` prebuilt Windows `gfx103X` binaries (ROCm 7 bundled, no separate SDK install). [VERIFIED via the project's GitHub README + b1280 release]
- `lemonade-sdk/whisper.cpp-rocm` Windows ROCm fork + the upstream PR #3823 (merged May 2026) + the upstream PR #3757 (still open). [VERIFIED via WebSearch]
- AMD's official ROCm 7.2.1 Windows wheel matrix — supports `gfx1100/1101` (RDNA3) and `gfx1200/1201` (RDNA4) only; does NOT support `gfx1030` (RDNA2). [VERIFIED via AMD docs]
- Upstream `ggml-org/llama.cpp` PR #19810 (Feb 2026) — official Windows HIP builds added as `llama-bXXXX-bin-win-hip-radeon-x64.zip`. [VERIFIED via GitHub]

### Tertiary (LOW confidence)

- "Qwen2.5-7B-Instruct Q4_K_M file size ≈ 4.5 GB" — the actual size on HF depends on the GGUF build (bartowski vs official Qwen team). [VERIFIED approx; re-check at registry-build time]
- The exact `n_gpu_layers` value for the desktop llama.cpp HIP path (depends on `gfx1030` VRAM headroom after faster-whisper + pyannote are unloaded). [Re-verify at 02-03 spike time]

## Metadata

**Confidence breakdown:**

- **Standard stack:** HIGH on the library APIs; MEDIUM on the actual wheel paths (TheRock nightly, lemonade-sdk prebuilts) — these are real artifacts with public URLs, but their long-term maintenance is a community-effort signal.
- **Architecture:** HIGH — the detect / manager / VRAM probe split is the well-trodden pattern; the Settings extension follows the existing D-14/D-15 contract.
- **Pitfalls:** HIGH on the per-pitfall mitigation shape (these are well-known failure modes); MEDIUM on the specific Windows-ROCm paths (the 02-03 spike is the verification step).

**Research date:** 2026-06-15
**Valid until:** 2026-09-15 (30 days — stable, but the TheRock nightly URL and `lemonade-sdk` release cadence are the fast-moving parts; a quarterly re-verify is appropriate)
