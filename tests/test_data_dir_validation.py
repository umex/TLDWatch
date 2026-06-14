"""Tests for ``PATCH /settings`` data_dir path validation (Plan 01-04 T8).

The :class:`app.models.settings.UpdateSettingsRequest` Pydantic model
rejects:

- ``None`` (the field is ``str``, not ``str | None``)
- empty string
- relative paths (the path must be absolute)
- existing file paths (a valid data_dir is an existing directory
  OR a creatable path; an existing regular file is rejected)

Each rejection case is asserted at the API boundary with a 422.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp

import httpx
import pytest


@pytest.mark.asyncio
async def test_data_dir_null_returns_422(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": None})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_data_dir_empty_returns_422(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": ""})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_data_dir_relative_returns_422(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/settings", json={"data_dir": "relative/path"})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_data_dir_file_path_returns_422(client: httpx.AsyncClient) -> None:
    """An existing regular file is rejected as a data_dir."""
    f = Path(mkdtemp()) / "f.txt"
    f.write_text("x", encoding="utf-8")
    resp = await client.patch("/settings", json={"data_dir": str(f)})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_data_dir_existing_directory_is_accepted(
    client: httpx.AsyncClient,
) -> None:
    """An existing directory is a valid data_dir."""
    d = Path(mkdtemp())
    resp = await client.patch("/settings", json={"data_dir": str(d)})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_data_dir_absolute_creatable_path_is_accepted(
    client: httpx.AsyncClient,
) -> None:
    """An absolute path whose parent exists is accepted (data_dir can
    be a creatable path; we do not require it to exist already)."""
    d = Path(mkdtemp()) / "new-subdir"
    resp = await client.patch("/settings", json={"data_dir": str(d)})
    assert resp.status_code == 200, resp.text
