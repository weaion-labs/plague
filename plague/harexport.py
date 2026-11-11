"""Export the observed request log as HAR or as ready-to-run curl commands.

Both formats contain live cookies and authorization headers. Files are written
owner-only under the Plague cache directory, and should still be treated as
evidence that may contain secrets.
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .observe import Observer

MAX_HAR_BODY = 20_000


def _selected(
    observer: Observer,
    *,
    filter: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    needle = (filter or "").lower()
    items = [
        item
        for item in observer.requests
        if not needle or needle in str(item.get("url", "")).lower()
    ]
    return items[-max(1, limit) :]


def _headers_list(headers: dict[str, Any] | None) -> list[dict[str, str]]:
    return [
        {"name": str(key), "value": str(value)}
        for key, value in (headers or {}).items()
    ]


def _query(url: str) -> list[dict[str, str]]:
    try:
        values = parse_qs(urlsplit(url).query, keep_blank_values=True)
    except Exception:
        return []
    return [
        {"name": str(name), "value": str(value)}
        for name, items in values.items()
        for value in items
    ]


def _request_cookies(headers: dict[str, Any] | None) -> list[dict[str, str]]:
    raw = ""
    for key, value in (headers or {}).items():
        if str(key).lower() == "cookie":
            raw = str(value)
            break
    cookies = []
    for part in raw.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": value.strip()})
    return cookies


def _http_version(url: str) -> str:
    return "HTTP/2" if url.startswith("https://") else "HTTP/1.1"


def _elapsed_ms(item: dict[str, Any]) -> float:
    timing = item.get("timing") or {}
    try:
        start = float(timing.get("startTime") or 0)
        end = float(timing.get("responseEnd") or 0)
    except Exception:
        return 0.0
    if start > 0 and end > start:
        return round(end - start, 1)
    return 0.0


def _textish(mime: str) -> bool:
    return (
        mime.startswith("text/")
        or "json" in mime
        or "xml" in mime
        or "javascript" in mime
    )


async def build_har(
    observer: Observer,
    *,
    filter: str | None = None,
    limit: int = 200,
    include_bodies: bool = True,
) -> dict[str, Any]:
    entries = []
    for item in _selected(observer, filter=filter, limit=limit):
        url = str(item.get("url", ""))
        started = item.get("started")
        if started:
            started_at = datetime.fromtimestamp(
                float(started), tz=timezone.utc
            ).isoformat()
        else:
            started_at = datetime.now(tz=timezone.utc).isoformat()
        elapsed = _elapsed_ms(item)
        mime = str(item.get("mime") or "")
        body = ""
        if include_bodies:
            response = item.get("_response")
            if response is not None and _textish(mime):
                try:
                    body = str(await response.text())[:MAX_HAR_BODY]
                except Exception:
                    body = ""
        post_data = item.get("post_data")
        request_headers = item.get("request_headers") or {}
        post_mime = "application/x-www-form-urlencoded"
        for name, value in request_headers.items():
            if str(name).lower() == "content-type":
                post_mime = str(value)
                break
        request = {
            "method": str(item.get("method", "GET")),
            "url": url,
            "httpVersion": _http_version(url),
            "headers": _headers_list(request_headers),
            "queryString": _query(url),
            "cookies": _request_cookies(request_headers),
            "headersSize": -1,
            "bodySize": len(post_data or ""),
        }
        if post_data:
            request["postData"] = {
                "mimeType": post_mime,
                "text": str(post_data),
            }
        response = {
            "status": int(item.get("status") or 0),
            "statusText": str(item.get("status_text") or ""),
            "httpVersion": _http_version(url),
            "headers": _headers_list(item.get("response_headers")),
            "cookies": [],
            "content": {
                "size": len(body),
                "mimeType": mime or "application/octet-stream",
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": len(body),
        }
        if body:
            response["content"]["text"] = body
        entries.append(
            {
                "startedDateTime": started_at,
                "time": elapsed,
                "request": request,
                "response": response,
                "cache": {},
                "timings": {
                    "blocked": -1,
                    "dns": -1,
                    "connect": -1,
                    "send": 0,
                    "wait": elapsed,
                    "receive": 0,
                    "ssl": -1,
                },
                "_resourceType": str(item.get("resource_type") or ""),
            }
        )
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "plague", "version": __version__},
            "entries": entries,
        }
    }


def curl_commands(
    observer: Observer,
    *,
    filter: str | None = None,
    limit: int = 200,
) -> list[str]:
    commands = []
    for item in _selected(observer, filter=filter, limit=limit):
        parts = [
            "curl",
            "--compressed",
            "-X",
            str(item.get("method", "GET")).upper(),
            shlex.quote(str(item.get("url", ""))),
        ]
        for name, value in (item.get("request_headers") or {}).items():
            if str(name).lower() in {"host", "content-length", "connection"}:
                continue
            parts.extend(["-H", shlex.quote(f"{name}: {value}")])
        post_data = item.get("post_data")
        if post_data:
            parts.extend(["--data-raw", shlex.quote(str(post_data))])
        commands.append(" \\\n  ".join(parts))
    return commands


def write_export(path: str | Path, text: str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except Exception:
        pass
    return target
