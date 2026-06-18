"""HF token validation: four-state table + network-error fallback (D-05, Pitfall 3).

The ``mock_hf_hub_url`` fixture patches ``app.models.hf_token._head``
(the HTTP seam) with an AsyncMock and ``_hf_hub_url`` with a
deterministic lambda. Tests override ``return_value`` / ``side_effect``
per-case.

The four states:

- ``skipped`` (200): no token, OR HF Hub unreachable (network error
  never blocks the app -- Pitfall 3).
- ``ok`` (200): token valid + gated terms accepted; ``user`` set.
- ``rejected`` (401): token invalid.
- ``rejected`` (403): token valid but gated terms not accepted; ``fix`` URL set.

The route maps ``rejected`` to 401 / 403; ``skipped`` and ``ok`` are 200.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.mark.asyncio
async def test_hf_token_no_token_returns_skipped(
    client: httpx.AsyncClient,
) -> None:
    """No token configured -> 200 skipped (Pitfall 3: token absence
    does NOT block the app)."""
    resp = await client.post("/diagnostics/test-hf-token")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "no token configured"


@pytest.mark.asyncio
async def test_hf_token_valid_returns_ok(
    client: httpx.AsyncClient, mock_hf_hub_url: AsyncMock
) -> None:
    """Valid token + gated terms accepted -> 200 ok with the HF username."""
    mock_hf_hub_url.return_value = (200, {"x-repo-author": "alice"})
    patch = await client.patch("/settings", json={"hf_token": "hf_valid"})
    assert patch.status_code == 200, patch.text

    resp = await client.post("/diagnostics/test-hf-token")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["user"] == "alice"


@pytest.mark.asyncio
async def test_hf_token_invalid_returns_401_rejected(
    client: httpx.AsyncClient, mock_hf_hub_url: AsyncMock
) -> None:
    """Invalid token -> 401 rejected (default mock returns 401)."""
    patch = await client.patch("/settings", json={"hf_token": "hf_invalid"})
    assert patch.status_code == 200, patch.text

    resp = await client.post("/diagnostics/test-hf-token")
    assert resp.status_code == 401, resp.text
    detail = resp.json().get("detail", resp.json())
    assert detail["status"] == "rejected"
    assert detail["reason"] == "token invalid"


@pytest.mark.asyncio
async def test_hf_token_gated_terms_not_accepted_returns_403(
    client: httpx.AsyncClient, mock_hf_hub_url: AsyncMock
) -> None:
    """Valid token but gated terms not accepted -> 403 with fix URL."""
    mock_hf_hub_url.return_value = (403, {})
    patch = await client.patch(
        "/settings", json={"hf_token": "hf_valid_but_gated"}
    )
    assert patch.status_code == 200, patch.text

    resp = await client.post("/diagnostics/test-hf-token")
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail", resp.json())
    assert detail["status"] == "rejected"
    assert detail["reason"] == "model terms not accepted"
    assert (
        detail["fix"]
        == "visit https://huggingface.co/pyannote/speaker-diarization-3.1"
    )


@pytest.mark.asyncio
async def test_hf_token_network_error_returns_skipped(
    client: httpx.AsyncClient, mock_hf_hub_url: AsyncMock
) -> None:
    """Pitfall 3: a network error returns 200 skipped (the app does
    NOT refuse to start on a flaky network)."""
    mock_hf_hub_url.side_effect = httpx.ConnectError("network down")
    patch = await client.patch("/settings", json={"hf_token": "hf_valid"})
    assert patch.status_code == 200, patch.text

    resp = await client.post("/diagnostics/test-hf-token")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "HF Hub unreachable"