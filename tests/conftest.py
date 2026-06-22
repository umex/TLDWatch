"""Test fixtures: isolated temp data dir + a wired-up FastAPI app under test.

Each test gets:

- A freshly-created temp directory used as the project root
- A ``data/settings.json`` written with an ABSOLUTE ``data_dir`` value
  so the test does not depend on the process cwd
- The FastAPI lifespan driven manually so the engine, session
  factory, and settings are installed for the test
- An :class:`httpx.AsyncClient` bound to the app via
  :class:`httpx.ASGITransport`
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from app.api.dependencies import configure
from app.main import app
from app.models.diagnostics import BackendProbe, GpuBackend, VRAMState
from app.models.settings import Settings
from app.storage.fs import bootstrap_settings_path


@pytest.fixture
def tmp_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a temp project root with a valid ``data/settings.json``.

    The bootstrap path is overridden to point inside the temp dir via
    :func:`app.storage.fs.bootstrap_settings_path`. We use
    :func:`monkeypatch.setattr` on the module so the change only
    affects this test, and we patch the module attribute used by
    ``app.main.lifespan`` to read it.
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="tan-test-"))
    data_dir = tmp_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write the bootstrap settings file inside the temp project root.
    # The file is the serialisation of the :class:`Settings` Pydantic
    # model; ``data_dir`` is the ABSOLUTE path of the data dir.
    # Phase 2: the model now has a required ``backend`` field (D-08);
    # the fixture writes a Phase 2-shaped file with ``backend=CPU`` and
    # all the new field defaults so the lifespan does NOT re-run the
    # first-boot detect on every test boot.
    settings_path = data_dir / "settings.json"
    settings_path.write_text(
        Settings(
            data_dir=str(data_dir.resolve()),
            backend=GpuBackend.CPU,
            # Phase 4 (04-02): the lifespan auto-starts the single
            # in-process worker when run_worker is True. Tests drive the
            # worker manually (or do not drive it at all -- many tests
            # only need the app boot), so the fixture opts out of the
            # auto-start by writing run_worker=False.
            run_worker=False,
        ).model_dump_json(),
        encoding="utf-8",
    )

    # The lifespan reads bootstrap_settings_path() directly. Patch the
    # module attribute to return our test path.
    from app.storage import fs as fs_module

    monkeypatch.setattr(fs_module, "bootstrap_settings_path", lambda: settings_path)
    # The lifespan also imports the function by name; patch the
    # alias in app.main too.
    from app import main as main_module

    monkeypatch.setattr(main_module, "bootstrap_settings_path", lambda: settings_path)

    try:
        yield tmp_root
    finally:
        # Make sure the lifespan fully tears down before we delete the
        # temp dir, otherwise SQLite may still hold a handle.
        configure(None, None)  # type: ignore[arg-type]
        # Best-effort cleanup; on Windows antivirus may briefly hold
        # the files, so we ignore errors and let the OS clean up.
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


@pytest_asyncio.fixture
async def app_under_test(tmp_data_dir: Path) -> AsyncIterator[object]:
    """Drive the FastAPI lifespan manually for the test app."""
    # Use the ASGI lifespan protocol via httpx's client below; we
    # also need to call the lifespan body directly so ``configure``
    # is invoked. The cleanest way is to drive the lifespan context
    # manager manually here.
    from contextlib import asynccontextmanager

    # Import the lifespan from app.main and run it as a context
    # manager around the test. The app instance is the module-level
    # ``app`` - re-using it is fine because each test gets a fresh
    # engine + session factory and ``configure`` resets state.
    @asynccontextmanager
    async def _lifespan_context():
        # Run the real lifespan body by stepping into the generator.
        agen = app.router.lifespan_context(app)
        await agen.__aenter__()
        try:
            yield
        finally:
            await agen.__aexit__(None, None, None)

    async with _lifespan_context():
        yield app


@pytest_asyncio.fixture
async def client(app_under_test: object) -> AsyncIterator[httpx.AsyncClient]:
    """An :class:`httpx.AsyncClient` bound to the test app via ASGI."""
    transport = httpx.ASGITransport(app=app_under_test)
    # Use ``http://localhost`` as the base URL so the request Host
    # header is on the TrustedHostMiddleware allow-list.
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        yield ac


# --- Phase 2 mock fixtures (Plan 02-01 Task 3) ---------------------------
#
# Each fixture patches a module-level seam via ``monkeypatch.setattr``
# so the mock is auto-undone at end-of-test. Tests override the
# ``return_value`` / ``side_effect`` per-case.


@pytest.fixture
def mock_backend_detect(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch ``app.models.backend.detect`` + ``burn_test`` with AsyncMocks.

    Default: ``detect`` returns ``GpuBackend.CPU``; ``burn_test`` returns
    a CPU-shaped :class:`BackendProbe` (``burn_test_ms=None``,
    ``vram_total_mb=None``, ``device_name="CPU"``). Tests override the
    ``return_value`` per-case, e.g.
    ``mock_backend_detect.detect.return_value = GpuBackend.CUDA``.

    Returns a :class:`types.SimpleNamespace` with ``detect`` and
    ``burn_test`` attributes pointing at the AsyncMocks so tests can
    also assert call counts (``mock_backend_detect.detect.assert_not_called()``).
    """
    from app.models import backend as backend_module

    detect_mock = AsyncMock(return_value=GpuBackend.CPU)
    burn_mock = AsyncMock(
        return_value=BackendProbe(
            backend=GpuBackend.CPU,
            device_name="CPU",
            burn_test_ms=None,
            vram_total_mb=None,
            notes="no GPU detected; running in CPU mode",
        )
    )
    monkeypatch.setattr(backend_module, "detect", detect_mock)
    monkeypatch.setattr(backend_module, "burn_test", burn_mock)
    return SimpleNamespace(detect=detect_mock, burn_test=burn_mock)


@pytest.fixture
def mock_hf_hub_url(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch ``app.models.hf_token._head`` + ``_hf_hub_url``.

    Default: ``_head`` returns ``(401, {})`` (token invalid). Tests
    override the ``return_value`` per-case, e.g.
    ``mock_hf_hub_url.return_value = (200, {"x-repo-author": "alice"})``,
    or set ``side_effect = httpx.ConnectError(...)`` to simulate a
    network error (Pitfall 3).

    Returns the ``_head`` AsyncMock so tests can configure it
    directly. ``_hf_hub_url`` is replaced with a deterministic lambda
    so the test does not need ``huggingface_hub`` installed.
    """
    from app.models import hf_token as hf_module

    head_mock = AsyncMock(return_value=(401, {}))
    monkeypatch.setattr(hf_module, "_head", head_mock)
    monkeypatch.setattr(
        hf_module,
        "_hf_hub_url",
        lambda repo_id, filename: (
            f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        ),
    )
    return head_mock


@pytest.fixture
def mock_probe_vram(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``probe_vram`` for both the diagnostics route and the manager.

    Default: a generous CUDA :class:`VRAMState` (``total_mb=8192``,
    ``available_mb=8192``, ``used_mb=0``) whose ``loaded`` list is
    built from the real ``manager_state`` passed in (so
    ``GET /diagnostics/vram`` reflects the live ``loaded_meta`` even
    with the mock). Tests override ``side_effect`` per-case (e.g. a
    tight state for the ``VramBudgetExceeded`` test that does NOT
    inspect the loaded list).

    Patches BOTH the route module's bound reference
    (``app.api.routes_diagnostics.probe_vram``) AND the manager
    module's bound reference (``app.models.manager.probe_vram``) so
    the mock is seen by both ``GET /diagnostics/vram`` and
    ``POST /models/{id}/load``.
    """
    from app.api import routes_diagnostics as routes_module
    from app.models import manager as manager_module
    from app.models.vram import _loaded_list

    def _default(backend, manager_state):
        return VRAMState(
            backend=GpuBackend.CUDA,
            total_mb=8192,
            available_mb=8192,
            used_mb=0,
            loaded=_loaded_list(manager_state),
        )

    mock = MagicMock(side_effect=_default)
    monkeypatch.setattr(routes_module, "probe_vram", mock)
    monkeypatch.setattr(manager_module, "probe_vram", mock)
    return mock


@pytest.fixture
def mock_hf_hub_download(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the manager's lazy ``hf_hub_download`` seam with a MagicMock.

    The manager lazy-imports ``huggingface_hub.hf_hub_download`` inside
    ``ensure_downloaded``. This fixture ensures ``huggingface_hub`` is
    imported (it is a real dependency per pyproject) and patches the
    ``hf_hub_download`` attribute on the real module so the manager's
    ``from huggingface_hub import hf_hub_download`` resolves to the
    mock. The default writes ``b"x" * spec.expected_size_bytes`` bytes
    to ``<local_dir>/<filename>`` (so the size + SHA fast-paths see a
    complete file). Tests override ``side_effect`` per-case (e.g.
    raise ``GatedRepoError``).
    """
    import huggingface_hub  # type: ignore[import-not-found]
    from app.models.registry import REGISTRY

    def _default_download(*, repo_id, filename, revision, local_dir, token):
        from pathlib import Path

        out_path = Path(local_dir) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        for spec in REGISTRY.values():
            # Match the filename derivation in ``spec_file_path``:
            # ``spec.file or f"{repo_id.replace('/', '--')}.bin"``.
            expected_fn = spec.file or f"{spec.repo_id.replace('/', '--')}.bin"
            if spec.repo_id == repo_id and expected_fn == filename:
                size = spec.expected_size_bytes or 0
                break
        with out_path.open("wb") as fh:
            fh.write(b"x" * size)
        return str(out_path)

    mock = MagicMock(side_effect=_default_download)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", mock)
    return mock


@pytest.fixture
def mock_hf_snapshot_download(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the manager's lazy ``snapshot_download`` seam with a MagicMock.

    Mirrors ``mock_hf_hub_download`` but for the ``spec.file is None``
    snapshot-repo path. The default side_effect creates the
    ``local_dir`` directory + a fake ``config.json`` (so the populated-
    snapshot fast-path / return-dir logic is exercised) and returns the
    directory path. Tests override ``side_effect`` / ``return_value``
    per-case.

    Returns the ``MagicMock`` installed on
    ``huggingface_hub.snapshot_download``.
    """
    import huggingface_hub  # type: ignore[import-not-found]

    def _default_snapshot(*, repo_id, revision, local_dir, token, **_kwargs):
        from pathlib import Path

        out_dir = Path(local_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Fake a populated multi-file snapshot (config.json is the
        # fast-path sentinel the manager checks).
        (out_dir / "config.json").write_text("{}", encoding="utf-8")
        (out_dir / "model.bin").write_bytes(b"x" * 16)
        return str(out_dir)

    mock = MagicMock(side_effect=_default_snapshot)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", mock)
    return mock


@pytest.fixture
def slow_mock_hf_hub_download(
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """A SLOW in-flight mock for ``huggingface_hub.hf_hub_download``.

    Unlike ``mock_hf_hub_download`` (synchronous, returns immediately),
    this fixture's side_effect is a plain ``def`` that STAYS IN-FLIGHT
    until a ``threading.Event`` (``release_event``) is set. While
    in-flight it writes byte increments to ``<filename>.incomplete``
    every ~0.5s so the SSE generator's bytes-change throttle emits real
    ``event: progress`` frames with strictly increasing ``bytes_done``,
    and so the 5s ``: ping`` heartbeat (``routes_models.py:264``) fires
    WHILE the download is still running. Once released, the side_effect
    finalizes the file at the full ``expected_size_bytes`` and renames
    ``.incomplete`` to the final filename.

    The side_effect is a plain ``def`` (NOT ``async def``) because
    ``asyncio.to_thread`` runs it in a worker thread -- blocking with
    ``time.sleep`` and ``release_event.wait`` is correct there.

    Returns a :class:`types.SimpleNamespace` with:
    - ``release_event``: a ``threading.Event`` the test sets (or
      schedules via ``threading.Timer``) to release the download.
    - ``mock``: the ``MagicMock`` installed on
      ``huggingface_hub.hf_hub_download``.

    On teardown the fixture sets ``release_event`` so a forgotten
    release cannot hang the worker thread across tests.
    """
    import threading
    import time

    import huggingface_hub  # type: ignore[import-not-found]
    from app.models.registry import REGISTRY

    release_event = threading.Event()

    def _slow_download(*, repo_id, filename, revision, local_dir, token, **_kwargs):
        from pathlib import Path

        out_path = Path(local_dir) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        inc_path = out_path.with_name(out_path.name + ".incomplete")
        # Resolve the expected size from the registry (same lookup as
        # the synchronous mock_hf_hub_download fixture). Match the
        # filename derivation in ``spec_file_path``.
        size = 0
        for spec in REGISTRY.values():
            expected_fn = spec.file or f"{spec.repo_id.replace('/', '--')}.bin"
            if spec.repo_id == repo_id and expected_fn == filename:
                size = spec.expected_size_bytes or 0
                break
        # Write byte increments every ~0.5s across the in-flight window
        # so ``event: progress`` frames keep flowing while the 5s
        # heartbeat accumulates. ~20 increments covers the full size.
        chunk = max(size // 20, 1)
        written = 0
        # Truncate any stale .incomplete so the byte count is clean.
        inc_path.write_bytes(b"")
        while not release_event.is_set():
            if written < size:
                with inc_path.open("ab") as fh:
                    fh.write(b"x" * min(chunk, size - written))
                written += min(chunk, size - written)
            time.sleep(0.5)
        # Released -- finalize the file at the full expected size and
        # rename .incomplete to the final filename.
        if written < size:
            with inc_path.open("ab") as fh:
                fh.write(b"x" * (size - written))
            written = size
        inc_path.replace(out_path)
        return str(out_path)

    mock = MagicMock(side_effect=_slow_download)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", mock)
    try:
        yield SimpleNamespace(release_event=release_event, mock=mock)
    finally:
        # Never let a forgotten release hang the worker thread across
        # tests.
        release_event.set()


@pytest_asyncio.fixture
async def configured_model_manager(
    tmp_data_dir: Path,
    mock_probe_vram: MagicMock,
) -> AsyncIterator[object]:
    """Build a ``ModelManager`` from the test settings and configure it.

    Cleans up via ``configure_manager(None)`` (which also resets the
    vram ``ManagerState`` singleton). The mock_probe_vram fixture is
    pulled in so the manager's ``load`` sees the generous default
    state.
    """
    from app.models import manager as manager_module
    from app.models.manager import ModelManager, configure_manager
    from app.settings import service as settings_service

    settings = settings_service.current()
    mgr = ModelManager(settings)
    configure_manager(mgr)
    try:
        yield mgr
    finally:
        configure_manager(None)


# --- Phase 3 STT adapter fixtures ------------------------------------------
#
# ``mock_stt_adapter`` mirrors the Phase 2 ``mock_hf_hub_download`` pattern
# (real-module-import + ``monkeypatch.setattr`` on the lazy import seam).
# ``faster_whisper`` is a real dependency (pinned in pyproject Phase 3) so
# the real import at fixture-setup time succeeds. The fixture patches:
#   - ``faster_whisper.WhisperModel`` -> a MagicMock class whose instances
#     expose ``.model.compute_type`` (read by D-08 int8 verification) and
#     whose ``transcribe`` / ``detect_language`` return deterministic
#     SimpleNamespaces.
#   - ``faster_whisper.audio.decode_audio`` -> a stub returning
#     ``fake_audio_array()`` so 03-02's decode_audio unit test can assert
#     ``FasterWhisperAdapter.decode_audio(path)`` returns the stubbed array
#     without hitting PyAV / FFmpeg.
#
# Cross-plan fixture ownership: ``mock_stt_adapter`` is DEFINED here in
# 03-01 and EXTENDED (not redefined) by 03-02; 03-02 must not duplicate the
# fixture.
@pytest.fixture
def mock_stt_adapter(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the adapter's lazy ``faster_whisper`` import seam.

    Returns a ``MagicMock`` whose ``.compute_type`` attribute is the
    value the mock WhisperModel's inner ``.model.compute_type`` returns.
    Tests override ``mock_stt_adapter.compute_type`` to simulate the
    silent-fallback (``"float32"``) or the accepted substitution
    (``"int8_float16"``) path. The default is ``"int8_float16"`` so a
    plain ``load()`` with ``requested="int8_float16"`` succeeds without
    per-test setup.
    """
    import faster_whisper  # type: ignore[import-not-found]
    import faster_whisper.audio as _fw_audio  # type: ignore[import-not-found]
    import ctranslate2  # type: ignore[import-not-found]

    # Patch ``ctranslate2.get_supported_compute_types`` so ``load()`` does
    # not hit a real CUDA driver probe on this machine (the real call
    # raises ``RuntimeError: CUDA driver version is insufficient`` on a
    # machine without a matching CUDA runtime).
    _ct2_table = {
        "cuda": {"int8", "int8_float16", "float16"},
        "cpu": {"int8", "int8_float32", "float32"},
    }

    def _get_supported(device, device_index=0, **_kwargs):
        return _ct2_table.get(device, {"int8", "int8_float16"})

    monkeypatch.setattr(ctranslate2, "get_supported_compute_types", _get_supported)

    class _InnerModel:
        def __init__(self, compute_type: str) -> None:
            self.compute_type = compute_type

    class _WhisperModel:
        def __init__(self, model_path, device="cuda", compute_type="int8_float16", **_kwargs) -> None:
            self.model = _InnerModel(compute_type)
            # Allow per-test override of the reported compute_type
            # (tests mutate mock_stt_adapter.compute_type BEFORE load()).
            self.model.compute_type = mock.compute_type

        def transcribe(self, audio, language=None, vad_filter=True, condition_on_previous_text=True, *, progress_cb=None, cancel_flag=None, **_kwargs):
            seg = SimpleNamespace(start=1.0, end=3.0, text="hi", avg_logprob=-0.1)
            info = SimpleNamespace(language="en", language_probability=0.99, duration=30.0)
            return iter([seg]), info

        def detect_language(self, audio, vad_filter=True, **_kwargs):
            return ("en", 0.99, {})

    mock = MagicMock(spec=_WhisperModel)
    mock.compute_type = "int8_float16"
    # Use a real class instance so attribute access (``self.model``)
    # works naturally and so tests can mutate ``mock.compute_type`` and
    # have the next __init__ pick it up.
    real_class = _WhisperModel

    def _factory(model_path, device="cuda", compute_type="int8_float16", **kwargs):
        return real_class(model_path, device=device, compute_type=compute_type, **kwargs)

    # Expose the per-test override knob on the factory itself.
    _factory.compute_type = "int8_float16"

    class _PatchedWhisperModel:
        def __new__(cls, *args, **kwargs):
            inst = real_class(*args, **kwargs)
            # Honor the latest per-test override set on the mock.
            inst.model.compute_type = getattr(mock, "compute_type", "int8_float16")
            return inst

    monkeypatch.setattr(faster_whisper, "WhisperModel", _PatchedWhisperModel)

    # Patch the decode_audio seam so 03-02's unit test sees a stubbed
    # array without hitting PyAV / FFmpeg.
    def _fake_decode_audio(path, *args, **kwargs):
        import numpy as np  # type: ignore[import-not-found]
        return np.zeros(16000 * 30, dtype="float32")

    monkeypatch.setattr(_fw_audio, "decode_audio", _fake_decode_audio)
    return mock


@pytest.fixture
def fake_audio_array() -> "object":
    """A 30 s silence 16 kHz float32 numpy array (the decode_audio shape)."""
    import numpy as np  # type: ignore[import-not-found]
    return np.zeros(16000 * 30, dtype="float32")


# --- Phase 4 plan 04-02 fixtures -------------------------------------------
#
# ``fake_stt`` reuses the 04-01 FakeAdapter (which already honors
# ``progress_cb`` / ``cancel_flag`` per Fix 8) so the 04-02 queue / cancel /
# watchdog tests can drive a multi-chunk transcription deterministically
# without touching a real STT model. ``run_worker_off`` is a sanity alias that
# asserts the test settings opt out of the lifespan auto-start (the
# ``tmp_data_dir`` fixture already writes ``run_worker=False`` -- 04-01 added
# that -- so this fixture only documents the invariant for tests that rely on
# driving the worker manually).
#
# The existing ``client`` fixture (above) already does NOT auto-start the
# worker: the lifespan only starts one when ``settings.run_worker`` is True,
# and ``tmp_data_dir`` writes ``run_worker=False``. So 04-02 reuses the
# existing async ``client`` fixture unchanged (no duplicate non-auto-start
# TestClient is added).


@pytest.fixture
def fake_stt() -> "object":
    """Return a :class:`tests._stt_fake.FakeAdapter` configured for N fake chunks.

    The default returns a single fast-path segment per ``transcribe`` call
    (matches the orchestrator tests' contract). Tests that need a
    multi-chunk fake override ``segments_per_chunk`` on the returned instance
    or construct their own :class:`FakeAdapter` directly -- this fixture is
    the cheap default for the simple ``run_worker`` drain tests.
    """
    from tests._stt_fake import FakeAdapter

    return FakeAdapter()


@pytest.fixture
def run_worker_off(tmp_data_dir: Path) -> Path:
    """Sanity alias asserting the test settings opt out of worker auto-start.

    The ``tmp_data_dir`` fixture already writes ``run_worker=False`` (04-01
    added that so the 04-02 lifespan does not auto-start the worker). This
    fixture re-yields ``tmp_data_dir`` after asserting the invariant so a
    test that drives the worker manually can declare the dependency by name
    and fail loudly if a future fixture change re-enables auto-start.
    """
    from app.settings import service as settings_service

    settings = settings_service.current()
    assert settings.run_worker is False, (
        "run_worker_off: test settings must opt out of lifespan auto-start"
    )
    return tmp_data_dir


@pytest.fixture
def mock_ct2_supported_compute_types(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``ctranslate2.get_supported_compute_types`` for the int8 tests.

    Returns the mock; tests can assert on call args. Defaults:
    ``cuda`` -> {``"int8"``, ``"int8_float16"``, ``"float16"``},
    ``cpu`` -> {``"int8"``, ``"int8_float32"``, ``"float32"``}.
    """
    import ctranslate2  # type: ignore[import-not-found]

    _table = {
        "cuda": {"int8", "int8_float16", "float16"},
        "cpu": {"int8", "int8_float32", "float32"},
    }

    def _get(device, device_index=0, **_kwargs):
        return _table.get(device, {"int8", "int8_float16"})

    mock = MagicMock(side_effect=_get)
    monkeypatch.setattr(ctranslate2, "get_supported_compute_types", mock)
    return mock
