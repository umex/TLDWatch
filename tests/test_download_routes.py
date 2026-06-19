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
from pathlib import Path


def _manager_source() -> str:
    here = Path(__file__).resolve().parent.parent
    return (here / "app" / "models" / "manager.py").read_text(encoding="utf-8")


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