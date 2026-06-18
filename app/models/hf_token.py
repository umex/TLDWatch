"""HF token validation shim (D-05, Pitfall 3).

``validate_token`` does a HEAD call to HuggingFace Hub to verify the
token works AND that the gated ``pyannote/speaker-diarization-3.1``
repo's terms have been accepted. It returns a typed
:class:`HfTokenResult` from a four-state table:

- ``skipped`` (200): no token configured, OR HF Hub unreachable
  (network error never blocks the app — Pitfall 3, D-05).
- ``ok`` (200): the token authenticated; ``user`` carries the HF
  username from the ``x-repo-author`` response header.
- ``rejected`` (401): the token is invalid.
- ``rejected`` (403): the token is valid but the gated repo's terms
  have not been accepted; ``fix`` carries the URL the user must visit.

This is the pyannote SHIM: NO real diarization-library import
(CONTEXT domain boundary — Phase 7 ships the real import). Only
``huggingface_hub`` is imported, and only inside the function body,
so a CPU-only test environment does not crash on import.

The module-level ``_hf_hub_url`` thin alias exists so tests can
``monkeypatch.setattr("app.models.hf_token._hf_hub_url", ...)`` without
touching the real ``huggingface_hub`` package.
"""

from __future__ import annotations

import logging

from app.models.diagnostics import HfTokenResult

_log = logging.getLogger(__name__)

# The gated pyannote repo that the test-token endpoint probes. The
# user must accept its terms on the HF website before the token can
# download it; the 403 path surfaces the URL in ``HfTokenResult.fix``.
_DEFAULT_REPO_ID = "pyannote/speaker-diarization-3.1"
_FIX_URL_TEMPLATE = "visit https://huggingface.co/{repo_id}"


def _hf_hub_url(repo_id: str, filename: str) -> str:
    """Thin alias to ``huggingface_hub.hf_hub_url``.

    Declared at module scope so tests can ``monkeypatch.setattr`` this
    attribute without importing the real ``huggingface_hub`` package.
    The lazy import inside the function body keeps the test
    environment import-clean.
    """
    from huggingface_hub import hf_hub_url  # type: ignore[import-not-found]

    return hf_hub_url(repo_id, filename)


async def _head(url: str, headers: dict) -> tuple[int, dict]:
    """Module-level seam for the HF Hub HEAD call.

    Returns ``(status_code, response_headers)`` so the four-state
    mapping in :func:`validate_token` can read both. Declared at
    module scope so tests can ``monkeypatch.setattr`` it with a fake
    that returns a canned status code (or raises ``httpx.HTTPError``
    to simulate a network error) WITHOUT touching the real
    ``httpx`` package.

    The real implementation lazy-imports ``httpx`` inside the function
    body so a CPU-only test environment does not need httpx installed
    for unrelated imports.
    """
    import httpx  # type: ignore[import-not-found]

    async with httpx.AsyncClient() as client:
        resp = await client.head(
            url,
            headers=headers,
            timeout=5.0,
            follow_redirects=True,
        )
        return resp.status_code, dict(resp.headers)


async def validate_token(
    token: str | None, repo_id: str = _DEFAULT_REPO_ID
) -> HfTokenResult:
    """Validate ``token`` against HF Hub; return a typed :class:`HfTokenResult`.

    Contract: NEVER raise, ALWAYS return a typed result (Pitfall 3).
    A missing token, a network error, or a torch/HF import failure all
    return ``HfTokenResult(status="skipped", ...)`` so the route layer
    can return 200 without try/excepting the call.

    The HEAD call carries ``Authorization: Bearer <token>`` and a 5s
    timeout. The token is NEVER logged.
    """
    if token is None or token == "":
        return HfTokenResult(status="skipped", reason="no token configured")

    try:
        import httpx  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:
        _log.warning("validate_token: httpx import failed: %s", exc)
        return HfTokenResult(status="skipped", reason="HF Hub unreachable")

    # Probe a known file inside the gated repo; the HEAD returns 200
    # only if the token is valid AND the gated terms have been
    # accepted. We pick ``config.yaml`` because every HF model repo
    # has one; any 4xx is mapped to the four-state table.
    filename = "config.yaml"
    try:
        url = _hf_hub_url(repo_id, filename)
    except Exception as exc:
        _log.warning("validate_token: hf_hub_url failed: %s", exc)
        return HfTokenResult(status="skipped", reason="HF Hub unreachable")

    try:
        status_code, headers = await _head(
            url, {"Authorization": f"Bearer {token}"}
        )
    except Exception as exc:
        # ``_head`` raises ``httpx.HTTPError`` (or a subclass) on any
        # transport failure; we also catch any other exception so the
        # helper never raises (Pitfall 3 — the app does not refuse to
        # start on a flaky network).
        _log.info("validate_token: HF Hub unreachable: %s", exc)
        return HfTokenResult(status="skipped", reason="HF Hub unreachable")

    if status_code == 200:
        user = headers.get("x-repo-author")
        return HfTokenResult(status="ok", user=user)
    if status_code == 401:
        return HfTokenResult(status="rejected", reason="token invalid")
    if status_code == 403:
        return HfTokenResult(
            status="rejected",
            reason="model terms not accepted",
            fix=_FIX_URL_TEMPLATE.format(repo_id=repo_id),
        )
    # Any other code (5xx, etc.) — treat as unreachable so the app
    # does not refuse to start (Pitfall 3).
    _log.info("validate_token: unexpected status %s; treating as skipped", status_code)
    return HfTokenResult(
        status="skipped", reason=f"HF Hub returned {status_code}"
    )


__all__ = ["validate_token"]