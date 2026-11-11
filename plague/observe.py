"""Bounded observation of a live page: requests, console, and errors.

Recon work needs the network surface more than it needs the rendered text. The
recorder is attached to warm sessions and to a headed handoff while a tool call
drives it. Everything is bounded so a long-lived MCP server cannot grow without
limit.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque


class Observer:
    def __init__(
        self,
        *,
        max_requests: int = 500,
        max_console: int = 200,
    ) -> None:
        self.requests: Deque[dict[str, Any]] = deque(maxlen=max_requests)
        self.console: Deque[dict[str, Any]] = deque(maxlen=max_console)
        self.errors: Deque[dict[str, Any]] = deque(maxlen=100)
        self._pending: dict[int, dict[str, Any]] = {}
        self._pages: set[int] = set()
        self._contexts: set[int] = set()

    def attach(self, page: Any) -> None:
        key = id(page)
        if key in self._pages:
            return
        self._pages.add(key)
        try:
            page.on("request", self._on_request)
            page.on("response", self._on_response)
            page.on("requestfailed", self._on_failed)
            page.on("console", self._on_console)
            page.on("pageerror", self._on_error)
        except Exception:
            self._pages.discard(key)

    def attach_context(self, context: Any) -> None:
        """Observe pages opened later by the same context, such as popups."""
        key = id(context)
        if key in self._contexts:
            return
        self._contexts.add(key)
        try:
            context.on("page", self.attach)
        except Exception:
            self._contexts.discard(key)

    # ----------------------------------------------------------- event hooks

    def _on_request(self, request: Any) -> None:
        try:
            headers = {
                str(key): str(value)
                for key, value in (
                    getattr(request, "headers", None) or {}
                ).items()
            }
        except Exception:
            headers = {}
        try:
            post_data = getattr(request, "post_data", None)
        except Exception:
            post_data = None
        try:
            entry = {
                "method": str(request.method),
                "url": str(request.url),
                "resource_type": str(getattr(request, "resource_type", "")),
                "status": None,
                "ok": None,
                "request_headers": headers,
                "post_data": str(post_data)[:4_000] if post_data else None,
                "started": time.time(),
            }
        except Exception:
            return
        self._pending[id(request)] = entry
        self.requests.append(entry)

    def _on_response(self, response: Any) -> None:
        try:
            entry = self._pending.pop(id(response.request), None)
        except Exception:
            entry = None
        if entry is None:
            return
        try:
            entry["status"] = int(response.status)
            entry["ok"] = bool(response.ok)
            entry["status_text"] = str(
                getattr(response, "status_text", "") or ""
            )
            content_type = ""
            try:
                content_type = (
                    response.headers.get("content-type", "")
                    if response.headers
                    else ""
                )
            except Exception:
                content_type = ""
            entry["mime"] = str(content_type).split(";")[0].strip()
            try:
                entry["response_headers"] = {
                    str(key): str(value)
                    for key, value in (response.headers or {}).items()
                }
            except Exception:
                entry["response_headers"] = {}
            try:
                entry["timing"] = dict(response.request.timing or {})
            except Exception:
                entry["timing"] = {}
            entry["_response"] = response
        except Exception:
            pass

    def _on_failed(self, request: Any) -> None:
        entry = self._pending.pop(id(request), None)
        if entry is None:
            return
        try:
            entry["error"] = str(request.failure or "request failed")
        except Exception:
            entry["error"] = "request failed"

    def _on_console(self, message: Any) -> None:
        try:
            self.console.append(
                {
                    "type": str(message.type),
                    "text": str(message.text)[:500],
                }
            )
        except Exception:
            return

    def _on_error(self, error: Any) -> None:
        self.errors.append(
            {"type": "pageerror", "text": str(error)[:500]}
        )

    # -------------------------------------------------------------- readers

    async def network(
        self,
        *,
        filter: str | None = None,
        limit: int = 100,
        include_body: bool = False,
        include_headers: bool = False,
        max_body_chars: int = 2_000,
    ) -> list[dict[str, Any]]:
        needle = (filter or "").lower()
        items = [
            item
            for item in self.requests
            if not needle or needle in str(item.get("url", "")).lower()
        ][-max(1, limit) :]
        rows: list[dict[str, Any]] = []
        for item in items:
            row = {
                key: item.get(key)
                for key in (
                    "method",
                    "url",
                    "resource_type",
                    "status",
                    "ok",
                    "mime",
                    "error",
                )
                if key in item
            }
            if include_headers:
                row["request_headers"] = item.get("request_headers") or {}
                row["response_headers"] = item.get("response_headers") or {}
                row["post_data"] = item.get("post_data")
            response = item.get("_response")
            mime = str(row.get("mime") or "")
            textish = (
                mime.startswith("text/")
                or "json" in mime
                or "xml" in mime
                or "javascript" in mime
            )
            if include_body and response is not None and textish:
                try:
                    body = await response.text()
                    row["body"] = str(body)[:max_body_chars]
                except Exception:
                    row["body_error"] = "response body unavailable"
            rows.append(row)
        return rows

    def logs(
        self,
        *,
        filter: str | None = None,
        level: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        needle = (filter or "").lower()
        items = [
            {**item, "source": "console"} for item in self.console
        ] + [{**item, "source": "page"} for item in self.errors]
        if level:
            items = [
                item
                for item in items
                if str(item.get("type", "")).lower() == level.lower()
            ]
        if needle:
            items = [
                item
                for item in items
                if needle in str(item.get("text", "")).lower()
            ]
        return items[-max(1, limit) :]

    def clear(self) -> None:
        self.requests.clear()
        self.console.clear()
        self.errors.clear()
        self._pending.clear()
