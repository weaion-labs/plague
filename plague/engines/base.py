"""Engine and session abstractions shared by all browser backends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlsplit

from ..models import Capability, EngineInfo, Profile
from ..text import html_to_text

log = logging.getLogger("plague.engine")


class EngineError(RuntimeError):
    pass


class EngineUnavailable(EngineError):
    """The engine cannot start on this machine (missing binary, key, library)."""


class CapabilityError(EngineError):
    """The engine cannot satisfy a requested capability."""


@dataclass
class Nav:
    url: str
    status: int | None
    headers: dict[str, str]


def playwright_proxy(url: str | None) -> dict[str, str] | None:
    """Turn a proxy URL into Playwright's proxy dict."""
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError(f"invalid proxy URL: {url!r}")
    server = f"{parts.scheme}://{parts.hostname}"
    if parts.port:
        server += f":{parts.port}"
    result = {"server": server}
    if parts.username:
        result["username"] = unquote(parts.username)
    if parts.password:
        result["password"] = unquote(parts.password)
    return result


class Session:
    """A thin, engine-neutral wrapper around one Playwright page."""

    def __init__(
        self,
        *,
        page: Any,
        context: Any,
        browser: Any,
        info: EngineInfo,
        closers: list[Callable[[], Awaitable[None]]] | None = None,
    ) -> None:
        self.page = page
        self.context = context
        self.browser = browser
        self.info = info
        self._closers = closers or []
        self._closed = False

    def supports(self, capability: Capability) -> bool:
        return self.info.supports(capability)

    def _require(self, capability: Capability) -> None:
        if not self.supports(capability):
            raise CapabilityError(
                f"engine {self.info.name!r} does not support {capability.value}"
            )

    async def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
    ) -> Nav:
        response = await self.page.goto(
            url, wait_until=wait_until, timeout=timeout_ms
        )
        status = response.status if response is not None else None
        headers: dict[str, str] = {}
        if response is not None:
            try:
                headers = {
                    str(k).lower(): str(v) for k, v in (response.headers or {}).items()
                }
            except Exception:
                headers = {}
        return Nav(url=self.page.url, status=status, headers=headers)

    async def title(self) -> str:
        try:
            return await self.page.title()
        except Exception:
            return ""

    async def content(self) -> str:
        return await self.page.content()

    async def text(self) -> str:
        try:
            body = await self.page.inner_text("body")
            if body and body.strip():
                return body.strip()
        except Exception:
            pass
        return html_to_text(await self.content())

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    async def click(self, selector: str, timeout_ms: int | None = None) -> None:
        await self.page.click(selector, timeout=timeout_ms)

    async def fill(
        self, selector: str, value: str, timeout_ms: int | None = None
    ) -> None:
        await self.page.fill(selector, value, timeout=timeout_ms)

    async def press(
        self, selector: str, key: str, timeout_ms: int | None = None
    ) -> None:
        await self.page.press(selector, key, timeout=timeout_ms)

    async def hover(self, selector: str, timeout_ms: int | None = None) -> None:
        await self.page.hover(selector, timeout=timeout_ms)

    async def select_option(
        self, selector: str, value: str, timeout_ms: int | None = None
    ) -> None:
        await self.page.select_option(selector, value, timeout=timeout_ms)

    async def check(self, selector: str, timeout_ms: int | None = None) -> None:
        await self.page.check(selector, timeout=timeout_ms)

    async def uncheck(self, selector: str, timeout_ms: int | None = None) -> None:
        await self.page.uncheck(selector, timeout=timeout_ms)

    async def back(self) -> Nav:
        response = await self.page.go_back()
        status = response.status if response is not None else None
        headers: dict[str, str] = {}
        if response is not None:
            try:
                headers = {
                    str(k).lower(): str(v)
                    for k, v in (response.headers or {}).items()
                }
            except Exception:
                headers = {}
        return Nav(url=self.page.url, status=status, headers=headers)

    async def wait_for_selector(
        self, selector: str, timeout_ms: int | None = None
    ) -> None:
        await self.page.wait_for_selector(selector, timeout=timeout_ms)

    async def exists(self, selector: str) -> bool:
        try:
            return await self.page.query_selector(selector) is not None
        except Exception:
            return False

    async def wait_for_timeout(self, ms: int) -> None:
        await self.page.wait_for_timeout(ms)

    async def add_init_script(self, script: str) -> None:
        self._require(Capability.INIT_SCRIPT)
        await self.page.add_init_script(script)

    async def screenshot(self, path: str, full_page: bool = True) -> str:
        self._require(Capability.VISUAL)
        await self.page.screenshot(path=path, full_page=full_page)
        return path

    async def set_input_files(
        self,
        selector: str,
        files: str | list[str],
        timeout_ms: int | None = None,
    ) -> None:
        await self.page.set_input_files(selector, files, timeout=timeout_ms)

    def pages(self) -> list[Any]:
        return list(self.context.pages)

    async def use_page(self, index: int) -> Any:
        pages = self.context.pages
        if index < 0 or index >= len(pages):
            raise IndexError(f"no page at index {index}")
        self.page = pages[index]
        try:
            await self.page.bring_to_front()
        except Exception:
            pass
        return self.page

    async def new_page(self, url: str | None = None) -> Any:
        page = await self.context.new_page()
        self.page = page
        if url:
            await page.goto(url)
        return page

    async def close_page(self, index: int | None = None) -> None:
        pages = self.context.pages
        if not pages:
            return
        if index is None:
            index = pages.index(self.page) if self.page in pages else 0
        if index < 0 or index >= len(pages):
            raise IndexError(f"no page at index {index}")
        if len(pages) == 1:
            raise ValueError("cannot close the last open page")
        target = pages[index]
        await target.close()
        remaining = self.context.pages
        if remaining:
            self.page = remaining[min(index, len(remaining) - 1)]

    async def cookies(self, urls: list[str] | None = None) -> list[dict[str, Any]]:
        return await self.context.cookies(urls)

    async def storage_state(self, path: str | None = None) -> dict[str, Any] | None:
        self._require(Capability.STORAGE_STATE)
        return await self.context.storage_state(path=path)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for closer in reversed(self._closers):
            try:
                await closer()
            except Exception as exc:  # cleanup must never mask the real error
                log.debug("cleanup step failed: %s", exc)


class BaseEngine(ABC):
    info: EngineInfo

    def __init__(self, config) -> None:
        self.config = config

    @abstractmethod
    async def open(self, profile: Profile) -> Session:
        """Start the engine and return a ready session."""

    def availability(self) -> tuple[bool, str]:
        """Cheap check used by `plague doctor`."""
        return True, "ready"

    def describe(self) -> dict[str, Any]:
        available, reason = self.availability()
        return {
            "name": self.info.name,
            "description": self.info.description,
            "available": available,
            "reason": reason,
            "capabilities": sorted(c.value for c in self.info.capabilities),
        }
