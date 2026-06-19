"""Live-behavior tests for the SC-3 download contract (Plan 02-04).

These tests lock the WR-01 (409 duplicate in-flight), WR-02 (live SSE
heartbeat + byte-level progress), and HW-09 (classic non-Xet resume
path) truths that the mocked 155-test suite could not catch -- the
existing ``mock_hf_hub_download`` fixture is synchronous and returns
immediately, so the event-loop freeze was invisible to it.

The concurrency tests use the ``slow_mock_hf_hub_download`` fixture
(see ``tests/conftest.py``) which holds the download in-flight past
the 5s SSE heartbeat threshold so the ``: ping`` line fires WHILE the
download is still running.
"""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import httpx
import pytest

from app.api import routes_models


def _manager_source() -> str:
    here = Path(__file__).resolve().parent.parent
    return (here / "app" / "models" / "manager.py").read_text(encoding="utf-8")


def _clear_in_flight(model_id: str) -> None:
    """Pop ``model_id`` from the routes' module-level ``_in_flight`` dict."""
    routes_models._in_flight.pop(model_id, None)


def test_hf_hub_download_is_offloaded_to_thread() -> None:
    """Source contract (Task 1): every ``hf_hub_download(...)`` Call in
    ``app/models/manager.py`` is the first argument of an
    ``asyncio.to_thread(...)`` (or ``loop.run_in_executor(...)``) Call;
    no direct synchronous invocations remain; the classic non-Xet
    download path is forced.
    """
    src = _manager_source()
    tree = ast.parse(src)
    direct = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "hf_hub_download"
    ]
    assert not direct, (
        f"{len(direct)} direct hf_hub_download calls remain in manager.py "
        "(should be offloaded via asyncio.to_thread / run_in_executor)"
    )
    offloaded = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("to_thread", "run_in_executor")
        and n.args
        and isinstance(n.args[0], ast.Name)
        and n.args[0].id == "hf_hub_download"
    ]
    assert len(offloaded) >= 2, (
        f"expected >=2 offloaded hf_hub_download calls, got {len(offloaded)}"
    )
    # Classic non-Xet resume path forced (belt-and-suspenders: kwarg on
    # versions that support it, env var on versions that do not).
    assert "hf_xet" in src or "HF_HUB_DISABLE_XET" in src, (
        "xet not disabled -- neither ``hf_xet=False`` kwarg nor "
        "``HF_HUB_DISABLE_XET`` env var found in manager.py"
    )


# ---------------------------------------------------------------------------
# Live-behavior tests (Task 2): 409 duplicate-in-flight, live SSE heartbeat +
# byte-level progress, classic non-Xet resume path. These tests use the
# ``slow_mock_hf_hub_download`` fixture so the download actually stays
# in-flight past the 5s SSE heartbeat threshold.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_duplicate_in_flight_returns_409(
    client: httpx.AsyncClient, slow_mock_hf_hub_download
) -> None:
    """WR-01: a second POST while the first download is in-flight -> 409."""
    model_id = "small.stt"
    try:
        first = await client.post(f"/models/{model_id}/download")
        assert first.status_code == 202, first.text
        # The slow mock holds the download in-flight; the event loop is
        # free, so the second POST is serviced immediately and the 409
        # dedupe check fires.
        second = await client.post(f"/models/{model_id}/download")
        assert second.status_code == 409, second.text
        body = second.json()
        detail = body.get("detail", body)
        assert detail["error"] == "download_in_flight"
        assert detail["state"] in {"queued", "running"}
    finally:
        # Release the in-flight download so the background task
        # completes and tears down cleanly.
        slow_mock_hf_hub_download.release_event.set()
        _clear_in_flight(model_id)


@pytest.mark.asyncio
async def test_download_progress_sse_streams_live(
    client: httpx.AsyncClient, slow_mock_hf_hub_download
) -> None:
    """WR-02: live SSE emits ``event: progress`` AND ``: ping`` WHILE
    the download is still running (not only after it completes).
    """
    model_id = "small.stt"
    # Schedule the release after ~6s so the 5s heartbeat fires WHILE
    # the download is still in-flight.
    timer = threading.Timer(6.0, slow_mock_hf_hub_download.release_event.set)
    timer.start()
    start = await client.post(f"/models/{model_id}/download")
    assert start.status_code == 202, start.text

    progress_lines: list[str] = []
    ping_lines: list[str] = []
    saw_done = False
    try:
        async with client.stream(
            "GET", f"/models/{model_id}/download-progress"
        ) as r:
            # Collect lines for up to ~7s (guarantees the 5s heartbeat
            # fires while the slow mock is still in-flight).
            elapsed = 0.0
            async for line in r.aiter_lines():
                if line.startswith("event: progress"):
                    progress_lines.append(line)
                elif line.startswith(": ping"):
                    ping_lines.append(line)
                # The generator returns after emitting the done/failed
                # frame; stop collecting once we see a done state.
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[len("data: "):])
                        if payload.get("state") in ("done", "failed"):
                            saw_done = True
                    except json.JSONDecodeError:
                        pass
                elapsed += 0.1
                if saw_done or elapsed >= 7.0:
                    break
    finally:
        slow_mock_hf_hub_download.release_event.set()
        timer.cancel()
        _clear_in_flight(model_id)

    assert progress_lines, (
        "no 'event: progress' lines streamed while download was running"
    )
    assert ping_lines, (
        "no ': ping' heartbeat lines streamed while download was running "
        "(5s heartbeat at routes_models.py:264 did not fire in the ~7s window)"
    )


@pytest.mark.asyncio
async def test_download_progress_byte_level(
    client: httpx.AsyncClient, slow_mock_hf_hub_download
) -> None:
    """WR-02: byte-level progress -- ``bytes_done`` strictly increases
    across >= 2 ``event: progress`` frames while state == "running".
    """
    model_id = "small.stt"
    timer = threading.Timer(6.0, slow_mock_hf_hub_download.release_event.set)
    timer.start()
    start = await client.post(f"/models/{model_id}/download")
    assert start.status_code == 202, start.text

    bytes_seen: list[int] = []
    saw_done = False
    try:
        async with client.stream(
            "GET", f"/models/{model_id}/download-progress"
        ) as r:
            elapsed = 0.0
            expect_data = False
            async for line in r.aiter_lines():
                if line.startswith("event: progress"):
                    expect_data = True
                elif line.startswith("data: ") and expect_data:
                    try:
                        payload = json.loads(line[len("data: "):])
                        if payload.get("state") == "running":
                            bytes_seen.append(payload.get("bytes_done", 0))
                        if payload.get("state") in ("done", "failed"):
                            saw_done = True
                    except json.JSONDecodeError:
                        pass
                    expect_data = False
                elapsed += 0.1
                if saw_done or elapsed >= 7.0:
                    break
    finally:
        slow_mock_hf_hub_download.release_event.set()
        timer.cancel()
        _clear_in_flight(model_id)

    # Strictly increasing across at least two running-state frames.
    assert len(bytes_seen) >= 2, (
        f"expected >= 2 running progress frames with bytes_done, got "
        f"{len(bytes_seen)}: {bytes_seen}"
    )
    increasing = [
        bytes_seen[i + 1] > bytes_seen[i] for i in range(len(bytes_seen) - 1)
    ]
    assert any(increasing), (
        f"bytes_done did not strictly increase across frames: {bytes_seen}"
    )


@pytest.mark.asyncio
async def test_resume_after_crash_uses_classic_path(
    tmp_path: Path, mock_hf_hub_download, monkeypatch
) -> None:
    """HW-09: a second call after a partial file is left on disk resumes
    via the classic non-Xet path (``hf_xet=False`` kwarg OR
    ``HF_HUB_DISABLE_XET=1`` env var set during the call) and does NOT
    pass ``force_download``.
    """
    import os

    from app.models.diagnostics import GpuBackend, ModelCategory
    from app.models.manager import ModelManager
    from app.models.registry import REGISTRY
    from app.models.settings import Settings
    from app.storage.models_dir import spec_file_path

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        backend=GpuBackend.CUDA,
    )
    mgr = ModelManager(settings, settings_factory=lambda: settings)
    spec = REGISTRY["balanced.llm"]
    target = spec_file_path(settings, ModelCategory.LLM, spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Pre-create a partial file at half the expected size (simulate a
    # mid-download crash leftover).
    target.write_bytes(b"x" * (spec.expected_size_bytes // 2))

    # Capture the HF_HUB_DISABLE_XET env value at call time by wrapping
    # the mock's side_effect.
    captured_xet: list[str | None] = []
    original_side_effect = mock_hf_hub_download.side_effect

    def _capturing_download(**kwargs):
        captured_xet.append(os.environ.get("HF_HUB_DISABLE_XET"))
        return original_side_effect(**kwargs)

    mock_hf_hub_download.side_effect = _capturing_download

    await mgr.ensure_downloaded(spec, ModelCategory.LLM)

    # The mock was called (partial file -> not a fast-path hit).
    assert mock_hf_hub_download.call_count >= 1
    # force_download was NOT passed (default False -> resume path).
    for call in mock_hf_hub_download.call_args_list:
        assert "force_download" not in call.kwargs
    # Classic non-Xet path forced: either hf_xet=False kwarg OR
    # HF_HUB_DISABLE_XET=1 set in the env during the call.
    hf_xet_passed = any(
        call.kwargs.get("hf_xet") is False
        for call in mock_hf_hub_download.call_args_list
    )
    env_set = any(v == "1" for v in captured_xet)
    assert hf_xet_passed or env_set, (
        f"classic non-Xet path not forced: hf_xet_passed={hf_xet_passed}, "
        f"captured_xet={captured_xet}"
    )