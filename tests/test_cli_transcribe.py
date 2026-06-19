"""Wave 0 CLI test stubs for ``app.cli.transcribe`` (Phase 03 Plan 03, RED).

These fourteen tests pin the standalone ``transcribe`` CLI contract before
the module exists. They cover:

- SC-5 device resolution from persisted ``settings.backend`` via
  :func:`app.models.backend.device_for` when ``--device auto`` (the
  default): ``test_device_resolution_from_settings_cuda`` /
  ``test_device_resolution_from_settings_cpu``.
- Codex HIGH: ``--device auto`` is a VALID argparse choice (regression
  guard): ``test_device_auto_is_valid_choice``.
- D-04 default ``compute_type`` per device (``int8_float16`` on CUDA,
  ``int8`` on CPU) + ``--compute-type`` override:
  ``test_default_compute_type_per_device`` / ``test_compute_type_override``.
- D-07 / INGEST-06: ``--language`` forces + skips detect, omitted
  auto-detects: ``test_language_force_skips_detect``.
- TRANS-01 / Phase 1 D-04 atomic writes: default ``--out`` is
  ``<input>.transcript.json`` (Codex MEDIUM accepted interpretation of
  SC-1) and ``atomic_write_json`` is called once with the resolved path +
  ``transcript.model_dump()``: ``test_default_out_path`` /
  ``test_atomic_write_called``.
- D-03 one-line stdout summary: ``test_stdout_summary``.
- V5 path validation / T-03-02: missing ``<file>`` exits non-zero with a
  clear stderr message (writability is NOT pre-checked -- Codex MEDIUM):
  ``test_missing_file_errors``.
- SC-4: the CLI never imports ``faster_whisper`` / ``ctranslate2``:
  ``test_cli_does_not_import_faster_whisper``.
- W2 (PATTERNS CLI settings-bootstrap gap): ``_bootstrap_settings()``
  calls ``load_settings_from_disk`` + ``configure`` BEFORE ``current()``
  returns (behavioral guard, not source-textual ordering):
  ``test_bootstrap_settings_runs_before_current``.
- Codex HIGH model-manager bootstrap: ``configure_manager`` runs BEFORE
  ``get_manager()`` when the manager is unconfigured (standalone CLI, no
  FastAPI lifespan): ``test_cli_configures_model_manager_when_unconfigured``.
- Codex suggestion + MEDIUM: ``adapter.unload()`` runs in a ``finally``
  block (VRAM cleanup on error) AND the raw ``RuntimeError`` message is
  preserved to stderr (not masked as a generic failure):
  ``test_adapter_unload_on_error``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# RED: the module under test does not exist yet -- this import fails until
# Task 2 creates ``app/cli/transcribe.py``.
from app.cli.transcribe import main  # noqa: E402  (RED until Task 2)

from app.models.diagnostics import GpuBackend, InferenceEngine
from app.models.transcript import Transcript, TranscriptSegment


# --- helpers ---------------------------------------------------------------


def _make_transcript(language: str = "en", job_id: str = "test") -> Transcript:
    """Build a minimal Transcript for the mocked ``transcribe_file``."""
    return Transcript(
        schema_version=1,
        job_id=job_id,
        language=language,
        segments=[TranscriptSegment(start_s=0.0, end_s=1.0, text="hi")],
    )


def _transcribe_factory():
    """Return a ``transcribe_file`` mock that mirrors the real chunker's job_id wiring.

    The real ``transcribe_file`` builds ``Transcript(job_id=job_id, ...)`` from
    the kwarg it receives. The plain ``MagicMock(return_value=...)`` ignores
    the kwarg, so tests that assert the persisted ``job_id`` (e.g.
    ``test_atomic_write_called``) would see the mock's hardcoded value. This
    factory returns a mock whose side effect reads the ``job_id`` kwarg and
    builds the Transcript from it, matching the real behavior.
    """

    def _impl(adapter, audio_path, *, language=None, job_id="cli"):
        return _make_transcript(job_id=job_id, language=language or "en")

    return MagicMock(side_effect=_impl)


def _make_settings(backend: GpuBackend = GpuBackend.CPU) -> object:
    """Build a minimal ``Settings`` for the given backend."""
    from app.models.settings import Settings

    return Settings(data_dir="/tmp/cli-test", backend=backend)


def _patch_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: object | None = None,
    transcribe_return: Transcript | None = None,
    transcribe_side_effect: BaseException | None = None,
):
    """Patch the bootstrap + manager + adapter + IO seams for the happy path.

    Returns a namespace of the installed mocks so each test can assert on
    the specific seam it cares about (FasterWhisperAdapter kwargs,
    atomic_write_json payload, etc.).
    """
    if settings is None:
        settings = _make_settings(GpuBackend.CPU)

    # Bootstrap seams (load_settings_from_disk + configure run BEFORE current).
    monkeypatch.setattr(
        "app.cli.transcribe.load_settings_from_disk", lambda *a, **k: (settings, None)
    )
    monkeypatch.setattr("app.cli.transcribe.configure", lambda s: None)
    monkeypatch.setattr("app.cli.transcribe.current", lambda: settings)

    # Manager seams: a MagicMock manager whose ensure_downloaded is async
    # and returns a sentinel model path (no real HF download).
    manager = MagicMock()
    manager.ensure_downloaded = AsyncMock(return_value=Path("/tmp/model.bin"))
    monkeypatch.setattr("app.cli.transcribe.get_manager", lambda: manager)
    monkeypatch.setattr("app.cli.transcribe.configure_manager", lambda m: None)
    monkeypatch.setattr("app.cli.transcribe.ModelManager", MagicMock(return_value=manager))

    # Adapter seam: FasterWhisperAdapter is mocked so no real model loads.
    adapter = MagicMock()
    adapter.load = MagicMock()
    adapter.unload = MagicMock()
    fw_mock = MagicMock(return_value=adapter)
    monkeypatch.setattr("app.cli.transcribe.FasterWhisperAdapter", fw_mock)

    # transcribe_file seam.
    if transcribe_side_effect is not None:
        transcribe_mock = MagicMock(side_effect=transcribe_side_effect)
    elif transcribe_return is not None:
        transcribe_mock = MagicMock(return_value=transcribe_return)
    else:
        # Default: mirror the real chunker's job_id wiring so assertions on
        # the persisted payload (job_id, language) reflect the CLI's kwargs.
        transcribe_mock = _transcribe_factory()
    monkeypatch.setattr("app.cli.transcribe.transcribe_file", transcribe_mock)

    # atomic_write_json seam (async; capture path + payload).
    atomic_mock = AsyncMock()
    monkeypatch.setattr("app.cli.transcribe.atomic_write_json", atomic_mock)

    return SimpleNamespaceLite(
        settings=settings,
        manager=manager,
        adapter=adapter,
        fw_mock=fw_mock,
        transcribe_mock=transcribe_mock,
        atomic_mock=atomic_mock,
    )


class SimpleNamespaceLite:
    """Tiny attribute-bag returned by :func:`_patch_happy_path`."""

    def __init__(self, **kw) -> None:  # type: ignore[no-untyped-def]
        self.__dict__.update(kw)


# --- SC-5 device resolution ------------------------------------------------


def test_device_resolution_from_settings_cuda(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SC-5: --device auto resolves to 'cuda' when settings.backend == CUDA."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CUDA))

    rc = main([str(audio), "--device", "auto"])

    assert rc == 0
    # The device flows into the FasterWhisperAdapter constructor (SC-5).
    assert mocks.fw_mock.call_args.kwargs["device"] == "cuda"


def test_device_resolution_from_settings_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SC-5: --device auto resolves to 'cpu' when settings.backend == CPU."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))

    rc = main([str(audio), "--device", "auto"])

    assert rc == 0
    assert mocks.fw_mock.call_args.kwargs["device"] == "cpu"


def test_device_auto_is_valid_choice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex HIGH: ``--device auto`` is accepted by argparse (no SystemExit(2))."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CUDA))

    # argparse rejecting 'auto' would raise SystemExit(2). If main returns
    # 0, 'auto' was a valid choice.
    rc = main([str(audio), "--device", "auto"])
    assert rc == 0


# --- D-04 default compute_type + override ---------------------------------


@pytest.mark.parametrize(
    "backend,device,expected_compute",
    [
        (GpuBackend.CUDA, "cuda", "int8_float16"),
        (GpuBackend.CPU, "cpu", "int8"),
    ],
)
def test_default_compute_type_per_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backend: GpuBackend,
    device: str,
    expected_compute: str,
) -> None:
    """D-04: default compute_type is int8_float16 on CUDA, int8 on CPU."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(backend))

    rc = main([str(audio), "--device", device])

    assert rc == 0
    assert mocks.fw_mock.call_args.kwargs["compute_type"] == expected_compute


def test_compute_type_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-04: --compute-type wins over the per-device default."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CUDA))

    rc = main([str(audio), "--device", "cuda", "--compute-type", "int8_float32"])

    assert rc == 0
    assert mocks.fw_mock.call_args.kwargs["compute_type"] == "int8_float32"


# --- D-07 / INGEST-06 --language force vs auto-detect ----------------------


def test_language_force_skips_detect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-07: --language en is forwarded; omitted forwards language=None."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))

    rc = main([str(audio), "--language", "en"])
    assert rc == 0
    assert mocks.transcribe_mock.call_args.kwargs["language"] == "en"

    # Reset and run with no --language -> language=None (auto-detect path).
    mocks.transcribe_mock.reset_mock()
    rc = main([str(audio)])
    assert rc == 0
    assert mocks.transcribe_mock.call_args.kwargs["language"] is None


# --- TRANS-01 / D-04 atomic writes + default --out -------------------------


def test_default_out_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SC-1 accepted interpretation (Codex MEDIUM): default out is <stem>.transcript.json."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))

    rc = main([str(audio)])

    assert rc == 0
    out_path = mocks.atomic_mock.call_args.args[0]
    assert out_path == tmp_path / "audio.transcript.json"


def test_atomic_write_called(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TRANS-01: atomic_write_json is called once with the resolved path + model_dump()."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    mocks = _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))

    rc = main([str(audio), "--out", str(tmp_path / "out.json")])

    assert rc == 0
    mocks.atomic_mock.assert_awaited_once()
    out_path, payload = mocks.atomic_mock.call_args.args
    assert out_path == (tmp_path / "out.json")
    # The payload is the Transcript's model_dump() (dict with schema_version,
    # job_id, language, segments).
    assert payload["schema_version"] == 1
    assert payload["job_id"] == "audio"
    assert len(payload["segments"]) == 1


def test_stdout_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """D-03: main prints a one-line summary with language=, segments=, and the out path."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))

    rc = main([str(audio), "--out", str(tmp_path / "out.json")])
    assert rc == 0

    captured = capsys.readouterr()
    assert "language=" in captured.out
    assert "segments=" in captured.out
    assert "out.json" in captured.out


# --- V5 path validation (T-03-02) ------------------------------------------


def test_missing_file_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """V5: a missing input file exits non-zero with a clear stderr message.

    Writability of ``--out``'s parent is NOT asserted (Codex MEDIUM:
    cross-platform-unreliable; atomic_write_json reports write failures).
    """
    _patch_happy_path(monkeypatch, settings=_make_settings(GpuBackend.CPU))
    missing = tmp_path / "nonexistent.wav"

    rc = main([str(missing)])

    assert rc != 0
    err = capsys.readouterr().err.lower()
    assert "not found" in err or "does not exist" in err


# --- SC-4 no faster_whisper / ctranslate2 import ---------------------------


def test_cli_does_not_import_faster_whisper() -> None:
    """SC-4: app.cli.transcribe has no top-level faster_whisper/ctranslate2 import."""
    import app.cli.transcribe as m

    src = inspect.getsource(m)
    assert "import faster_whisper" not in src
    assert "import ctranslate2" not in src
    assert "from faster_whisper" not in src
    assert "faster_whisper" not in dir(m)


# --- W2 PATTERNS bootstrap ordering ----------------------------------------


def test_bootstrap_settings_runs_before_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W2: _bootstrap_settings() fires load_settings_from_disk + configure BEFORE current()."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    settings = _make_settings(GpuBackend.CPU)

    calls: list[str] = []

    def record(name):
        def _fn(*a, **k):  # type: ignore[no-untyped-def]
            calls.append(name)
            if name == "load_settings_from_disk":
                return (settings, None)
            if name == "current":
                return settings
            return None

        return _fn

    monkeypatch.setattr(
        "app.cli.transcribe.load_settings_from_disk", record("load_settings_from_disk")
    )
    monkeypatch.setattr("app.cli.transcribe.configure", record("configure"))
    monkeypatch.setattr("app.cli.transcribe.current", record("current"))

    # Manager + adapter + IO seams (not under test here).
    manager = MagicMock()
    manager.ensure_downloaded = AsyncMock(return_value=Path("/tmp/model.bin"))
    monkeypatch.setattr("app.cli.transcribe.get_manager", lambda: manager)
    monkeypatch.setattr("app.cli.transcribe.configure_manager", lambda m: None)
    monkeypatch.setattr("app.cli.transcribe.ModelManager", MagicMock(return_value=manager))
    monkeypatch.setattr(
        "app.cli.transcribe.FasterWhisperAdapter",
        MagicMock(return_value=MagicMock(load=MagicMock(), unload=MagicMock())),
    )
    monkeypatch.setattr(
        "app.cli.transcribe.transcribe_file", MagicMock(return_value=_make_transcript())
    )
    monkeypatch.setattr("app.cli.transcribe.atomic_write_json", AsyncMock())

    rc = main([str(audio)])
    assert rc == 0

    # The behavioral guard: load_settings_from_disk + configure fire
    # BEFORE current() returns. The device-resolution tests (which patch
    # current directly) do NOT cover this ordering.
    ld_idx = calls.index("load_settings_from_disk")
    cfg_idx = calls.index("configure")
    cur_idx = calls.index("current")
    assert ld_idx < cfg_idx < cur_idx, f"expected load<configure<current, got {calls!r}"


# --- Codex HIGH model-manager bootstrap ordering ---------------------------


def test_cli_configures_model_manager_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex HIGH: configure_manager runs before get_manager() when unconfigured."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    settings = _make_settings(GpuBackend.CPU)

    # Bootstrap seams.
    monkeypatch.setattr(
        "app.cli.transcribe.load_settings_from_disk", lambda *a, **k: (settings, None)
    )
    monkeypatch.setattr("app.cli.transcribe.configure", lambda s: None)
    monkeypatch.setattr("app.cli.transcribe.current", lambda: settings)

    # Manager seams: first get_manager() raises (unconfigured), second
    # returns a MagicMock manager (after configure_manager).
    manager = MagicMock()
    manager.ensure_downloaded = AsyncMock(return_value=Path("/tmp/model.bin"))
    call_log: list[str] = []

    def fake_get_manager():
        call_log.append("get_manager")
        if len(call_log) == 1:
            raise RuntimeError("model manager not configured (lifespan not installed)")
        return manager

    configure_manager_calls: list[object] = []

    def fake_configure_manager(m):
        configure_manager_calls.append(m)
        call_log.append("configure_manager")

    monkeypatch.setattr("app.cli.transcribe.get_manager", fake_get_manager)
    monkeypatch.setattr("app.cli.transcribe.configure_manager", fake_configure_manager)
    monkeypatch.setattr("app.cli.transcribe.ModelManager", MagicMock(return_value=manager))

    # Adapter + IO seams.
    monkeypatch.setattr(
        "app.cli.transcribe.FasterWhisperAdapter",
        MagicMock(return_value=MagicMock(load=MagicMock(), unload=MagicMock())),
    )
    monkeypatch.setattr(
        "app.cli.transcribe.transcribe_file", MagicMock(return_value=_make_transcript())
    )
    monkeypatch.setattr("app.cli.transcribe.atomic_write_json", AsyncMock())

    rc = main([str(audio)])
    assert rc == 0

    # configure_manager was called BEFORE the successful get_manager() call.
    cm_idx = call_log.index("configure_manager")
    # The second get_manager call is the successful one; find it after cm_idx.
    later_gets = [i for i, c in enumerate(call_log) if c == "get_manager" and i > cm_idx]
    assert later_gets, (
        f"expected a get_manager() call AFTER configure_manager, got {call_log!r}"
    )
    assert len(configure_manager_calls) == 1


# --- Codex suggestion + MEDIUM: unload on error + raw message preserved ---


def test_adapter_unload_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Codex: adapter.unload() runs in a finally block; the raw error reaches stderr."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")

    adapter = MagicMock()
    adapter.load = MagicMock()
    adapter.unload = MagicMock()
    monkeypatch.setattr(
        "app.cli.transcribe.FasterWhisperAdapter", MagicMock(return_value=adapter)
    )

    # Bootstrap + manager seams.
    settings = _make_settings(GpuBackend.CPU)
    monkeypatch.setattr(
        "app.cli.transcribe.load_settings_from_disk", lambda *a, **k: (settings, None)
    )
    monkeypatch.setattr("app.cli.transcribe.configure", lambda s: None)
    monkeypatch.setattr("app.cli.transcribe.current", lambda: settings)
    manager = MagicMock()
    manager.ensure_downloaded = AsyncMock(return_value=Path("/tmp/model.bin"))
    monkeypatch.setattr("app.cli.transcribe.get_manager", lambda: manager)
    monkeypatch.setattr("app.cli.transcribe.configure_manager", lambda m: None)
    monkeypatch.setattr("app.cli.transcribe.ModelManager", MagicMock(return_value=manager))

    # transcribe_file raises a RuntimeError with a distinctive raw message.
    monkeypatch.setattr(
        "app.cli.transcribe.transcribe_file",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr("app.cli.transcribe.atomic_write_json", AsyncMock())

    rc = main([str(audio)])

    # The CLI returns non-zero on RuntimeError (no traceback crash).
    assert rc != 0
    # unload() ran in the finally block (Codex suggestion: VRAM cleanup on error).
    assert adapter.unload.called, "adapter.unload() must run in a finally block"
    # The raw RuntimeError message is preserved to stderr (Codex MEDIUM).
    err = capsys.readouterr().err
    assert "boom" in err