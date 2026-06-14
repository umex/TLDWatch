"""Tests for the Windows-retry helper and the atomic write helper."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from app.storage.atomic import atomic_write_bytes
from app.storage.retry import retry_windows


def test_retry_succeeds_after_two_permission_errors() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(errno.EACCES, "locked")
        return "ok"

    result = retry_windows(flaky, attempts=3)
    assert result == "ok"
    assert len(calls) == 3


def test_retry_gives_up_after_attempts() -> None:
    calls: list[int] = []

    def always_fails() -> None:
        calls.append(1)
        raise PermissionError(errno.EACCES, "locked")

    with pytest.raises(PermissionError):
        retry_windows(always_fails, attempts=2)
    assert len(calls) == 2


def test_retry_handles_oserror() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise OSError(errno.EBUSY, "busy")
        return "ok"

    result = retry_windows(flaky, attempts=3)
    assert result == "ok"
    assert len(calls) == 2


def test_retry_propagates_non_retriable() -> None:
    calls: list[int] = []

    def raises_value_error() -> None:
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        retry_windows(raises_value_error, attempts=3)
    assert len(calls) == 1


def test_atomic_write_bytes_uses_retry_on_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The atomic write helper retries ``os.replace`` so transient Windows
    file locks do not crash the request handler."""
    target = tmp_path / "manifest.json"
    real_replace = os.replace
    calls: list[int] = []

    def flaky_replace(src: str, dst: str) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(errno.EACCES, "locked")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    import asyncio

    asyncio.run(atomic_write_bytes(target, b"hello world"))

    assert target.exists()
    assert target.read_bytes() == b"hello world"
    assert len(calls) >= 3
