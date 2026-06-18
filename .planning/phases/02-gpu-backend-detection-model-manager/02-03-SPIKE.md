# ROCm-on-Windows Spike (Phase 02-03)

**Date:** 2026-06-18
**Box:** AMD Radeon RX 6800 (Navi 21 / gfx1030 / RDNA2 family; PCI DEV_73BF), AMD Adrenalin driver 32.0.21043.12001

VERDICT: ROCM_FALLBACK_TO_CPU

The documented TheRock nightly install did not succeed on this box, the existing
torch is the CPU build, and the GPU verification kernel did not run. Per D-07,
Phase 2 code (02-01 detect + 02-02 manager) is already "done" against this
verdict because the CPU fallback chain handles it safely. The spike is the
empirical record of which branch this box took. The GPU and driver ARE present
(§1), so the failure is a stale install command + the wrong Python (§4), not a
hardware limitation — a re-spike with the corrected wheel pin (§5 #5) is
high-value before Phase 3 hardens on CPU.

The RX 6800 is RDNA2 and is NOT CUDA-capable. Stock CUDA builds of torch (`+cu*`)
and any NVIDIA-only tooling will not use this GPU. The only GPU compute paths are
ROCm (the TheRock nightly wheel, which reuses the `device='cuda'` string and the
`torch.cuda` namespace via HIP's CUDA-compatibility layer — that is ROCm/HIP,
not NVIDIA CUDA), DirectML (torch-directml), or Vulkan. CPU is the fallback.

## 1. Target environment

OS (`wmic os get Caption,Version,BuildNumber`):

```
BuildNumber  Caption                   Version
19045        Microsoft Windows 10 Pro  10.0.19045
```

Shell: elevated PowerShell at `C:\Windows\system32>`. NOTE: the project CONTEXT
assumed Windows 11; this box is Windows 10 Pro build 19045.

nvidia-smi (expect "no GPUs were found"):

```
nvidia-smi : The term 'nvidia-smi' is not recognized as the name of a cmdlet,
function, script file, or operable program.
```

nvidia-smi is not installed — a weaker AMD-only signal than the expected
"no GPUs were found" (confirms only that NVIDIA tooling is absent on this box).

AMD GPU + driver (`Get-CimInstance Win32_VideoController | Where-Object Name -like "*AMD*" | Select-Object Name, DriverVersion, PNPDeviceID`):

```
Name               DriverVersion    PNPDeviceID
----               -------------    -----------
AMD Radeon RX 6800 32.0.21043.12001 PCI\VEN_1002&DEV_73BF&SUBSYS_67051EAE&REV_C3\6&818BBAD&0&00000019
```

GPU and driver are present and correct for the gfx1030 target (VEN_1002 = AMD,
DEV_73BF = Navi 21 / 6800 family / RDNA2). The earlier `pnputil | findstr
amdkmdap` returned empty — a false negative (wrong identifier pattern for this
Win10 build), NOT a missing driver; see §4 Pitfall 3.

pip show torch:

```
Name: torch
Version: 2.12.0
Location: C:\Users\dobrez\AppData\Local\Programs\Python\Python312\Lib\site-packages
Required-by: openai-whisper
```

This is the stock CPU PyPI torch (no +rocm / +cu suffix), on the global
Python 3.12 — NOT the project's locked Python 3.11 venv. The kernel error in §2
confirms it is CPU-only.

pip show ctranslate2:

```
Name: ctranslate2
Version: 4.7.2
Location: C:\Users\dobrez\AppData\Local\Programs\Python\Python312\Lib\site-packages
Required-by: faster-whisper
```

## 2. What worked

- `wmic os get Caption,Version,BuildNumber` → succeeded (Win10 Pro, 19045).
- `Get-CimInstance Win32_VideoController …` → succeeded; confirms the AMD
  Radeon RX 6800 + Adrenalin driver 32.0.21043.12001 are present (gfx1030).
- `pip show torch` / `pip show ctranslate2` → succeeded; both report the global
  Python 3.12 install with CPU/stock wheels.
- `python.exe -m pip install --upgrade pip` → succeeded (24.2 → 26.1.2).

The load-bearing ROCm install and the GPU kernel did NOT work:

- `pip install --index-url https://rocm.nightlies.amd.com/v2-staging/gfx103X-dgpu/ torch==2.10.0+rocm7.12`
  → `ERROR: No matching distribution found for torch==2.10.0+rocm7.12`. The index
  lists only dated alpha builds (`2.10.0+rocm7.13.0a20260421`,
  `2.11.0+rocm7.13.0a20260421`, `2.12.0a0+rocm7.13.0a…`, …); a bare
  `2.10.0+rocm7.12` does not exist. Retried after the pip upgrade — same error.
- `python -c "import torch; x = torch.randn(2048,2048,device='cuda'); y = x @ x; torch.cuda.synchronize(); print('ok')"`
  → `AssertionError: Torch not compiled with CUDA enabled` (the CPU torch; on
  RDNA2 this also confirms no ROCm/HIP wheel is active).
- `lemon-clip -m tiny.gguf -p "x" -n 1 -ngl 99` →
  `lemon-clip : The term 'lemon-clip' is not recognized` — not installed / not on PATH.

## 3. Fallback decision

The desktop falls back to CPU for both STT and LLM on this verdict:

- STT: faster-whisper with `device='cpu'`, `compute_type='int8'` (the existing
  CPU torch + ctranslate2 4.7.2 already support this; no install change needed).
- LLM: `llama-cpp-python` with `n_gpu_layers=0` (CPU). `lemon-clip` / a HIP
  llama.cpp build is the second fallback and is not yet available on this box.

Phase 3 follow-ups on this branch: the STT adapter defaults to `device='cpu'`;
the LLM adapter defaults to `n_gpu_layers=0`. Both stay pluggable so a later
successful TheRock re-attempt can flip them to GPU without an adapter rewrite
(02-01's detect function already probes backend at runtime).

## 4. Pitfalls hit

1. **Stale wheel pin (load-bearing).** The documented command pinned
   `torch==2.10.0+rocm7.12`, which does not exist in the
   `v2-staging/gfx103X-dgpu/` index. Only dated alpha builds exist, e.g.
   `2.10.0+rocm7.13.0a20260421` and `2.11.0+rocm7.13.0a20260421`. The spike's
   install failure is a stale-pin failure, NOT proof that ROCm cannot run on
   the RX 6800. A re-spike with the corrected dated-alpha pin is the obvious
   follow-up before Phase 3 commits to CPU.
2. **Wrong Python.** The spike ran against the global Python 3.12, not the
   project's locked Python 3.11 venv. TheRock wheels are Python-version-specific;
   the real app runs in the 3.11 venv, so the re-spike must use that venv.
3. **pnputil false negative — driver IS present.** `pnputil /enum-drivers |
   findstr amdkmdap` returned empty, but `Get-CimInstance Win32_VideoController`
   confirms the AMD Adrenalin driver 32.0.21043.12001 IS installed
   (DEV_73BF / Navi 21). The `amdkmdap` identifier pattern did not match on this
   Windows 10 build; use `Win32_VideoController`, not `pnputil|findstr`, to
   confirm the AMD driver. The driver being present means the only real ROCm
   blockers are Pitfall 1 (stale wheel pin) and Pitfall 2 (wrong Python) — both
   fixable, so the re-spike in §5 #5 is high-value.
4. **nvidia-smi absent** rather than "no GPUs were found" — weaker AMD-only
   signal; treat as informational only.
5. **RDNA2 is not CUDA.** The RX 6800 is RDNA2/gfx1030 and cannot run stock CUDA
   builds. Reaching for a `+cu*` torch wheel or any NVIDIA-only tooling would
   silently fail to use this GPU. The only GPU paths are ROCm (TheRock),
   DirectML, or Vulkan.

## 5. What Phase 3 must do

1. The STT adapter must default to `device='cpu'` on this desktop because the
   spike verdict is `ROCM_FALLBACK_TO_CPU` (the existing torch is CPU-only and
   the documented ROCm install failed).
2. The STT adapter must accept `device: Literal['cuda', 'cpu', 'rocm']` and keep
   the device pluggable so a later successful TheRock install flips it to
   `'cuda'` (the TheRock wheel's HIP CUDA-compatibility layer — ROCm, not NVIDIA
   CUDA) without an adapter rewrite.
3. Phase 3 must NOT hardcode a torch version pin; it must resolve the TheRock
   wheel dynamically (latest dated alpha for the gfx103X-dgpu index) or defer
   the ROCm path entirely until a re-spike with the corrected pin succeeds.
4. The LLM adapter must default to `n_gpu_layers=0` (CPU) on this box until a
   HIP llama.cpp build / `lemon-clip` binary is verified.
5. Phase 3 must schedule a re-spike (corrected dated-alpha pin, Python 3.11
   venv) before treating ROCm as unavailable — the GPU and driver are confirmed
   present (§1), so the current verdict reflects a stale install command and
   the wrong Python, not a hardware limitation.
6. Phase 3 must treat the RX 6800 as RDNA2 / non-CUDA-capable: stock CUDA builds
   of torch (`+cu*`) and any NVIDIA-only tooling will not use this GPU. The only
   GPU compute paths are ROCm (TheRock nightly; note its `device='cuda'` string
   is ROCm's HIP CUDA-compatibility layer, not NVIDIA CUDA), DirectML
   (torch-directml), or Vulkan. Any GPU path other than ROCm/DirectML/Vulkan
   must be rejected up front, not discovered at runtime.