---
phase: 3
slug: stt-adapter-audio-chunker-standalone-cli
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-19
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8 + pytest-asyncio (asyncio_mode=auto) + pytest-mock |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths=["tests"]) |
| **Quick run command** | `pytest tests/test_stt_*.py tests/test_chunker.py tests/test_cli_transcribe.py -x` |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~15 seconds (mocked adapter — no GPU, no model download) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_stt_*.py tests/test_chunker.py tests/test_cli_transcribe.py -x`
- **After every plan wave:** Run `pytest` (full suite — ~188 existing tests + new)
- **Before `/gsd-verify-work`:** Full suite must be green; the SC-5 "runs on both machines" half is a `checkpoint:human-verify` (real CUDA laptop + real CPU desktop), not automatable in CI.
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | TRANS-01 | — | N/A | unit | `pytest tests/test_stt_adapter.py::test_segment_mapping -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | INGEST-06 | — | N/A | unit | `pytest tests/test_stt_adapter.py::test_language_autodetect_recorded -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | D-08 | — | fail loud on silent float16 fallback | unit | `pytest tests/test_stt_adapter.py::test_int8_verification_fails_loud -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | SC-4 | T-03-01 | forbidden-import boundary holds | unit | `pytest tests/test_stt_boundary.py::test_import_boundary -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | INGEST-05 | — | N/A | unit | `pytest tests/test_chunker.py::test_short_audio_single_call -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | INGEST-05 | — | N/A | unit | `pytest tests/test_chunker.py::test_oom_halve_and_retry -x` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 1 | INGEST-05 | — | N/A | unit | `pytest tests/test_chunker.py::test_stitch_offset_and_overlap_trim -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 1 | INGEST-06 | T-03-02 | path validation on `<file>`/`--out` | unit + CLI smoke | `pytest tests/test_cli_transcribe.py::test_language_force_skips_detect -x` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 1 | D-04 | — | N/A | unit | `pytest tests/test_cli_transcribe.py::test_default_compute_type_per_device -x` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 1 | SC-5 | — | N/A | unit | `pytest tests/test_cli_transcribe.py::test_device_resolution_from_settings -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_stt_adapter.py` — mock `faster_whisper.WhisperModel` (mirror the `mock_hf_hub_download` pattern: patch the lazy import seam); covers INGEST-06, TRANS-01, D-08
- [ ] `tests/test_chunker.py` — a `FakeAdapter` implementing `STTAdapter` Protocol that yields deterministic segments / raises `RuntimeError("...out of memory...")` on demand; covers INGEST-05 (no real audio, no real GPU)
- [ ] `tests/test_cli_transcribe.py` — argparse + `monkeypatch` `current().backend` + `device_for`; covers SC-5, D-04
- [ ] `tests/test_stt_boundary.py` — grep the `app/` tree for forbidden imports (SC-4)
- [ ] `tests/conftest.py` additions: a `mock_stt_adapter` fixture (a `MagicMock` implementing the Protocol) + a `fake_audio_array` fixture (a small numpy array) — no framework install needed (pytest already present)
- [ ] `tests/_stt_fake.py` — a shared `FakeAdapter` implementing the Protocol with deterministic segment generation + OOM-on-demand (shared by chunker + CLI tests)

*No framework install needed — pytest + pytest-asyncio + pytest-mock already in `dev` deps.*

**Test-seam guidance (the key to testing without a GPU / model download):**
- Mock `faster_whisper.WhisperModel` at the lazy import point inside `adapter.py` (mirror the `mock_hf_hub_download` conftest pattern — patch the attribute on the real `faster_whisper` module after forcing its import, OR patch `sys.modules['faster_whisper']` with a `MagicMock` BEFORE the adapter imports it).
- The chunker + CLI tests use a `FakeAdapter` that implements the `STTAdapter` Protocol directly — they never touch faster-whisper. This is exactly why the Protocol exists (D-06): the chunker/CLI are testable without the package.
- The int8-verification test mocks the `model.model.compute_type` property to return `float32` and asserts a `RuntimeError` is raised.
- The boundary-check test runs the actual `grep -rE` command and asserts the only matching file is `app/models/stt/adapter.py`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI runs end-to-end on the laptop (CUDA) and produces transcript.json | SC-5 (laptop half) | requires the real RTX 2000 Ada GPU + CUDA runtime libs (Open Q1); not automatable on the dev desktop | On the laptop: `pip install -e .`; run `ctranslate2.get_supported_compute_types('cuda',0)` and confirm `int8`/`int8_float16` appear; then `transcribe <small-audio-file> --out out.json` and confirm a transcript.json with segments + language is written. This is the `checkpoint:human-verify` task from RESEARCH.md Open Q1. |
| CLI runs end-to-end on the desktop (CPU fallback) | SC-5 (desktop half) | requires the desktop machine; CPU path is automatable in unit tests but the full real-model run is manual | On the desktop: `transcribe <small-audio-file> --out out.json`; confirm it completes on CPU fallback without code changes. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending