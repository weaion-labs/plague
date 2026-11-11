"""Raw HTTP requests for authenticated API testing.

This is deliberately not the browsing path. It exists for the common bug bounty
move: observe an endpoint in the browser, then replay it with different
parameters while reusing the session cookies.

Two clients are supported:

- ``curl_cffi`` with browser impersonation, which matches a real Chrome TLS and
  HTTP/2 fingerprint. This is the default when the package is installed.
- ``httpx`` as a plain fallback. It is honest about being a Python client.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

import httpx

try:  # optional, but strongly preferred for protected targets
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

    HAS_CURL_CFFI = True
except Exception:  # pragma: no cover - depends on the install
    CurlAsyncSession = None  # type: ignore[assignment]
    HAS_CURL_CFFI = False

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
MAX_BODY_CHARS = 20_000


def _decode(raw: bytes, encoding: str | None) -> str:
    return raw[:MAX_BODY_CHARS].decode(encoding or "utf-8", errors="replace")


def _response_dict(
    *,
    response: Any,
    method: str,
    url: str,
    started: float,
    client: str,
    impersonate: str | None,
) -> dict[str, Any]:
    status = int(response.status_code)
    raw = response.content
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "url": str(response.url),
        "method": method.upper(),
        "headers": {
            str(key).lower(): str(value)
            for key, value in response.headers.items()
        },
        "body": _decode(raw, getattr(response, "encoding", None)),
        "truncated": len(raw) > MAX_BODY_CHARS,
        "elapsed_ms": elapsed_ms,
        "redirected": str(response.url) != url,
        "client": client,
        "impersonate": impersonate,
    }


def _merged_headers(
    headers: Mapping[str, str] | None,
    *,
    impersonate: str | None,
) -> dict[str, str]:
    merged = {"accept": "*/*"}
    if not impersonate:
        merged["user-agent"] = DEFAULT_USER_AGENT
    if headers:
        merged.update(
            {str(key).lower(): str(value) for key, value in headers.items()}
        )
    return merged


async def _via_curl_cffi(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None,
    body: str | None,
    json_body: Any,
    cookies: Mapping[str, str] | None,
    timeout_ms: int,
    follow_redirects: bool,
    impersonate: str,
) -> dict[str, Any]:
    assert CurlAsyncSession is not None
    merged = _merged_headers(headers, impersonate=impersonate)
    started = time.monotonic()
    async with CurlAsyncSession(
        impersonate=impersonate,
        timeout=max(0.1, timeout_ms / 1000),
    ) as client:
        response = await client.request(
            method.upper(),
            url,
            headers=merged,
            data=body,
            json=json_body,
            cookies=dict(cookies or {}),
            allow_redirects=follow_redirects,
        )
    return _response_dict(
        response=response,
        method=method,
        url=url,
        started=started,
        client="curl_cffi",
        impersonate=impersonate,
    )


async def _via_httpx(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None,
    body: str | None,
    json_body: Any,
    cookies: Mapping[str, str] | None,
    timeout_ms: int,
    follow_redirects: bool,
) -> dict[str, Any]:
    merged = _merged_headers(headers, impersonate=None)
    payload = body.encode("utf-8") if isinstance(body, str) else body
    started = time.monotonic()
    async with httpx.AsyncClient(
        follow_redirects=follow_redirects,
        timeout=max(0.1, timeout_ms / 1000),
        cookies=dict(cookies or {}),
    ) as client:
        response = await client.request(
            method.upper(),
            url,
            headers=merged,
            content=payload,
            json=json_body,
        )
    return _response_dict(
        response=response,
        method=method,
        url=url,
        started=started,
        client="httpx",
        impersonate=None,
    )


async def request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: str | None = None,
    json_body: Any = None,
    cookies: Mapping[str, str] | None = None,
    timeout_ms: int = 30_000,
    follow_redirects: bool = False,
    impersonate: str | None = "chrome",
) -> dict[str, Any]:
    """Send one request and return a normalized result.

    Set ``impersonate="none"`` to force the plain httpx client. When
    ``curl_cffi`` is installed and an impersonation profile is requested, the
    request carries a real browser TLS and HTTP/2 fingerprint.
    """
    wanted = (impersonate or "").strip().lower()
    if body is not None and json_body is not None:
        raise ValueError("use body or json_body, not both")
    use_curl = HAS_CURL_CFFI and wanted not in {"", "none", "off", "httpx"}
    if use_curl:
        return await _via_curl_cffi(
            method,
            url,
            headers=headers,
            body=body,
            json_body=json_body,
            cookies=cookies,
            timeout_ms=timeout_ms,
            follow_redirects=follow_redirects,
            impersonate=wanted,
        )
    return await _via_httpx(
        method,
        url,
        headers=headers,
        body=body,
        json_body=json_body,
        cookies=cookies,
        timeout_ms=timeout_ms,
        follow_redirects=follow_redirects,
    )
