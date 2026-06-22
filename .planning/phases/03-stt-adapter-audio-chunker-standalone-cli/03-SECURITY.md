---
phase: 03
slug: stt-adapter-audio-chunker-standalone-cli
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-22
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
>
> Source threat models: `03-01-PLAN.md`, `03-02-PLAN.md`, `03-03-PLAN.md`
> `<threat_model>` blocks. All three SUMMARYs reported `## Threat Flags: None`
> (no new security-relevant surface introduced beyond what the plans declared).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| user CLI args → adapter.transcribe | untrusted positional `<file>` path + `--language`/`--preset`/`--device`/`--compute-type` flag values cross here | filesystem path + short option strings (local single-user) |
| user argv → CLI argparse | untrusted positional `<file>` + flag values parsed by argparse with `choices=` enumeration | argv strings |
| `<file>` / `--out` filesystem paths | local single-user filesystem; CLI reads input, writes output JSON | file paths (trusted local input per PROJECT.md single-user) |
| on-disk audio file → PyAV/FFmpeg decoder | user-supplied local file decoded by bundled FFmpeg into a numpy array; chunker slices the array | binary audio container (trusted local) |
| per-chunk transcribe → CTranslate2 OOM | OOM `RuntimeError` crosses back into the chunker's split-both-halves recursive retry | runtime exception |
| pip install (laptop CUDA runtime libs) | `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12` were `[ASSUMED]` in the RESEARCH audit — gated on the SC-5 human checkpoint | pip packages from pypi.nvidia.com |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-03-01 | Tampering | `<file>`/`--out` path args (adapter-side) | accept | Local single-user CLI (PROJECT.md); path validation lives in the CLI (03-03, see T-03-02 CLI). The adapter receives a resolved `model_path` and a numpy array/path from the chunker — no untrusted path handling in the adapter. | closed |
| T-03-02 (PyAV) | Tampering | malicious audio → PyAV/FFmpeg parser | accept | PyAV bundles a fixed FFmpeg build in the wheel (D-01); `decode_audio` wraps `av.error.InvalidDataError` and skips invalid frames. Input is user-supplied local files (trusted single-user). | closed |
| T-03-02 (CLI) | Tampering | `<file>` / `--out` CLI path args | mitigate | V5 input validation in `app/cli/transcribe.py:172-190`: `Path(args.file).resolve()` + `exists()` → exit 2 with clear stderr on missing file; `--out` parent-dir `exists()` check → exit 2; argparse `choices=` validate `--preset` (l.124), `--device` incl. `auto` (l.131), `--compute-type` (l.142). Pinned by `tests/test_cli_transcribe.py::test_missing_file_errors`. | closed |
| T-03-03 | Tampering | malicious audio → PyAV parser during chunker `decode_audio` | accept | Same surface as T-03-02 (PyAV): bundled FFmpeg + `InvalidDataError` wrap; trusted local input. The chunker adds no new attack surface — it slices a numpy array. | closed |
| T-03-04 | Denial of Service | OOM split loop never terminates | mitigate | `FLOOR_SECONDS = 60` hard floor (`chunker.py:69,223`) — below the floor the final attempt is allowed to raise (no catch, no further split); split-both-halves recursion halves `chunk_s` each OOM, depth bounded by `log2(WINDOW/FLOOR) ≈ 4`. Non-OOM `RuntimeError`s re-raise immediately (`chunker.py:230-231`, Pitfall 5) so a non-OOM error cannot masquerade as OOM and loop forever. Pinned by `tests/test_chunker.py::test_oom_halve_covers_full_audio` + `test_oom_non_oom_runtime_error_reraises`. | closed |
| T-03-05 | Information Disclosure | transcript stdout summary / raw error to stderr | accept | One-line stdout summary (language, segment count, out path) and any raw `RuntimeError` message are the user's own transcript metadata / their own error on their own machine — no disclosure boundary. Preserving raw errors (Codex MEDIUM) aids debugging without crossing a trust boundary. | closed |
| T-03-06 | Tampering | laptop pip install `nvidia-cublas-cu12` + `nvidia-cuda-runtime-cu12` | mitigate | SC-5 checkpoint gate (blocking-human verify) runs `ctranslate2.get_supported_compute_types('cuda',0)` BEFORE any install decision. **Closed by human UAT 2026-06-22:** the probe returned `{'int8_float16','bfloat16','int8_float32','float32','float16','int8_bfloat16','int8'}` — `int8` + `int8_float16` present, so the CUDA runtime libs were already findable and **NO pip install occurred**. Open Q1 closed with no `pyproject.toml` change (the packages were never added). | closed |
| T-03-07 | Denial of Service | adapter VRAM not released on CLI error | mitigate | `finally`-block `adapter.unload()` in `app/cli/transcribe.py:241-246` runs even when `transcribe_file` or `atomic_write_json` raises — VRAM is returned to the allocator rather than leaking across failed runs. Pinned by `tests/test_cli_transcribe.py::test_adapter_unload_on_error`. | closed |
| T-03-SC | Tampering | pip supply chain (`faster-whisper==1.2.1` + `ctranslate2==4.7.2`) | mitigate | Both flagged OK in `03-RESEARCH.md` Package Legitimacy Audit (SYSTRAN/OpenNMT flagship repos, millions/wk downloads); pinned exactly in `pyproject.toml:34-35`; verified installed + importing on BOTH machines (CPU desktop run + CUDA laptop UAT 2026-06-22). `nvidia-*-cu12` deferred to T-03-06 (resolved — no install). | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-01 | Adapter receives already-resolved values; no untrusted path handling in the adapter. Path validation is the CLI's job (T-03-02 CLI, mitigated). | Claude (gsd-security) + user | 2026-06-22 |
| AR-03-02 | T-03-02 (PyAV), T-03-03 | Malicious-audio-as-parser-exploit accepted: PyAV bundles a fixed FFmpeg build; `decode_audio` wraps `InvalidDataError`; input is user-supplied local files on a single-user machine (PROJECT.md). No network delivery of audio. | Claude (gsd-security) + user | 2026-06-22 |
| AR-03-03 | T-03-05 | stdout transcript summary + raw stderr error are the user's own data on their own machine — no trust-boundary disclosure. Raw-error preservation is an intentional debugging aid (Codex MEDIUM). | Claude (gsd-security) + user | 2026-06-22 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-22 | 9 | 9 | 0 | Claude (gsd-secure-phase) + human UAT (T-03-06) |

**Method:** Short-circuit path — `register_authored_at_plan_time: true` (all 3 PLANs had parseable `<threat_model>` blocks) and `threats_open: 0` (every threat had an accept/mitigate disposition; all SUMMARYs reported `Threat Flags: None`). Mitigation evidence cross-checked against `03-VERIFICATION.md` (11/11), `03-REVIEW.md`, and the live source (`app/cli/transcribe.py`, `app/models/stt/chunker.py`). T-03-06 closed by the human SC-5 laptop CUDA UAT performed 2026-06-22 (`03-UAT.md`).

**Non-blocking follow-ups (do not affect threats_open):** the `03-REVIEW.md` failure-path quality defects — CR-01 narrow `except RuntimeError` (typed `ModelManagerError`/`OSError` escape as tracebacks) and WR-02 `--device rocm` with no CT2 codepath — are tracked for a future hardening pass. Neither opens a STRIDE threat on the default non-gated `Systran/faster-whisper-large-v3` single-user CLI path.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-22