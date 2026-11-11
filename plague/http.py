"""Raw HTTP requests for authenticated API testing.

This is deliberately not the browsing path. It does not carry a browser TLS or
HTTP/2 fingerprint, so a WAF may block it. It exists for the common bug bounty
move: observe an endpoint in the browser, then replay it with different
parameters while reusing the session cookies.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
MAX_BODY_CHARS = 20_000


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
) -> dict[str, Any]:
    merged = {
        "user-agent": DEFAULT_USER_AGENT,
        "accept": "*/*",
    }
    if headers:
        merged.update({str(key).lower(): str(value) for key, value in headers.items()})

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
    elapsed_ms = int((time.monotonic() - started) * 1000)

    raw = response.content
    text = raw[:MAX_BODY_CHARS].decode(
        response.encoding or "utf-8", errors="replace"
    )
    return {
        "ok": response.is_success,
        "status": response.status_code,
        "url": str(response.url),
        "method": method.upper(),
        "headers": {
            str(key).lower(): str(value)
            for key, value in response.headers.items()
        },
        "body": text,
        "truncated": len(raw) > MAX_BODY_CHARS,
        "elapsed_ms": elapsed_ms,
        "redirected": str(response.url) != url,
    }
