"""Headed browser handoff over CDP.

The router stays cheap and headless. When a page needs a human (login, 2FA,
payment, a risk-score wall) it launches a real headed Chrome with a dedicated
profile and a debugging port, or attaches to a Chrome that is already running.
Either the same MCP server can keep driving it through ``act``, or an external
harness such as Playwright MCP can attach with ``--cdp-endpoint``.

On Linux the launch picks Wayland when the session provides it, and falls back
to X11. Use ``attach_to`` to drive a browser on another machine over an SSH
tunnel, a cloud browser, or a Chrome the user started themselves.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from .config import Config, find_chrome
from .engines.base import Session
from .models import Capability, EngineInfo
from .observe import Observer

HANDOFF_INFO = EngineInfo(
    name="handoff",
    capabilities=frozenset(
        {
            Capability.VISUAL,
            Capability.COOKIES,
            Capability.STORAGE_STATE,
            Capability.DOWNLOADS,
            Capability.PDF,
        }
    ),
    description="headed Chrome driven over CDP",
)


class HandoffError(RuntimeError):
    """The headed browser could not be started or reached."""


@dataclass
class HandoffState:
    process: asyncio.subprocess.Process | None
    port: int
    profile_dir: str
    url: str | None = None
    proxy_note: str | None = None
    attached: bool = False
    cdp_override: str | None = None
    display: str | None = None
    ozone: str | None = None

    @property
    def cdp_url(self) -> str:
        return self.cdp_override or f"http://127.0.0.1:{self.port}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_cdp_url(url: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    target = url.rstrip("/") + "/json/version"
    # A CDP probe must not inherit http_proxy from the environment.
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(target, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _wait_for_cdp(port: int, timeout_s: float) -> bool:
    return _wait_for_cdp_url(f"http://127.0.0.1:{port}", timeout_s)


def _display_mode() -> str | None:
    """Return the available display kind on Linux, or None when headless.

    macOS and Windows always have a window server when a desktop session is
    active, so they return "native" and skip the environment check.
    """
    if not sys.platform.startswith("linux"):
        return "native"
    has_x11 = bool(os.environ.get("DISPLAY"))
    has_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if has_x11 and has_wayland:
        return "both"
    if has_wayland:
        return "wayland"
    if has_x11:
        return "x11"
    return None


def _ozone_args(preference: str | None, mode: str | None) -> list[str]:
    """Translate a display preference into Chrome ozone flags."""
    choice = (preference or "auto").strip().lower()
    if choice == "x11":
        return ["--ozone-platform=x11"]
    if choice == "wayland":
        return ["--ozone-platform=wayland"]
    if mode == "wayland":
        # Chrome still defaults to X11 in some builds even with no DISPLAY, so
        # be explicit when only Wayland is available.
        return ["--ozone-platform=wayland"]
    if mode in {"both", "x11"}:
        return ["--ozone-platform-hint=auto"]
    return []


def _normalize_cdp(cdp_url: str) -> str:
    url = (cdp_url or "").strip()
    if not url:
        raise HandoffError("attach_to needs a CDP URL or host:port")
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


def _port_from_url(url: str) -> int:
    try:
        return int(urlsplit(url).port or 0)
    except Exception:
        return 0


def _proxy_arg(proxy: str | None) -> tuple[str | None, str | None]:
    """Return (chrome flag, note). Chrome cannot take proxy credentials here."""
    if not proxy:
        return None, None
    parsed = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    if not parsed.hostname:
        return None, "ignored invalid proxy URL"
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    if parsed.username or parsed.password:
        return (
            f"--proxy-server={server}",
            "proxy credentials are not passed to a headed Chrome; use a "
            "port-forwarded local proxy instead",
        )
    return f"--proxy-server={server}", None


class HandoffManager:
    """Owns at most one headed browser process or CDP attachment."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state: HandoffState | None = None
        self.active_page: int = 0
        self.observer = Observer()

    @property
    def running(self) -> bool:
        if self.state is None:
            return False
        if self.state.attached:
            return True
        return (
            self.state.process is not None
            and self.state.process.returncode is None
        )

    async def start(
        self,
        *,
        url: str | None = None,
        port: int | None = None,
        profile_dir: str | None = None,
        proxy: str | None = None,
        timeout_s: float = 20.0,
        ozone: str | None = None,
    ) -> dict[str, Any]:
        if self.running:
            await self.stop()

        chrome = self.config.chrome_executable or find_chrome()
        if not chrome:
            raise HandoffError(
                "no Chrome or Chromium binary found; set "
                "PLAGUE_CHROME_EXECUTABLE"
            )

        mode = _display_mode()
        if mode is None:
            raise HandoffError(
                "no graphical display available; pass attach_to to drive an "
                "already-running Chrome, or run the server under Xvfb"
            )

        chosen_port = port or self.config.handoff_port or _free_port()
        chosen_profile = str(
            Path(profile_dir or self.config.handoff_profile_dir).expanduser()
        )
        Path(chosen_profile).mkdir(parents=True, exist_ok=True)

        proxy_flag, proxy_note = _proxy_arg(proxy or self.config.proxy)
        ozone_flags = _ozone_args(
            ozone or self.config.handoff_ozone, mode
        )
        args = [
            chrome,
            f"--remote-debugging-port={chosen_port}",
            f"--user-data-dir={chosen_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            *ozone_flags,
        ]
        if proxy_flag:
            args.append(proxy_flag)
        args.append(url or "about:blank")

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        ok = await asyncio.to_thread(_wait_for_cdp, chosen_port, timeout_s)
        if not ok:
            await self._kill(process)
            raise HandoffError(
                "Chrome started but never exposed a CDP endpoint on "
                f"port {chosen_port}; it may have exited immediately"
            )

        self.observer.clear()
        self.active_page = 0
        self.state = HandoffState(
            process=process,
            port=chosen_port,
            profile_dir=chosen_profile,
            url=url,
            proxy_note=proxy_note,
            display=mode,
            ozone=" ".join(ozone_flags) or None,
        )
        return self.describe()

    async def attach(
        self, cdp_url: str, *, timeout_s: float = 10.0
    ) -> dict[str, Any]:
        """Attach to an existing Chrome instead of launching one."""
        if self.running:
            await self.stop()
        target = _normalize_cdp(cdp_url)
        if target.startswith("http"):
            ok = await asyncio.to_thread(
                _wait_for_cdp_url, target, timeout_s
            )
            if not ok:
                raise HandoffError(
                    f"no CDP endpoint answered at {target}/json/version"
                )
        self.observer.clear()
        self.active_page = 0
        self.state = HandoffState(
            process=None,
            port=_port_from_url(target),
            profile_dir="",
            attached=True,
            cdp_override=target,
        )
        return self.describe()

    def describe(self) -> dict[str, Any]:
        if not self.state:
            return {"running": False}
        data: dict[str, Any] = {
            "running": self.running,
            "attached": self.state.attached,
            "cdp_url": self.state.cdp_url,
            "port": self.state.port,
            "url": self.state.url,
            "display": self.state.display,
            "ozone": self.state.ozone,
            "proxy_note": self.state.proxy_note,
            "attach_hint": (
                "Playwright MCP: --cdp-endpoint=" + self.state.cdp_url
            ),
        }
        if self.state.process is not None:
            data["pid"] = self.state.process.pid
            data["profile_dir"] = self.state.profile_dir
        return data

    async def stop(self) -> bool:
        state = self.state
        self.state = None
        if not state:
            return False
        if state.attached:
            return True
        if state.process is not None:
            await self._kill(state.process)
        return True

    @staticmethod
    async def _kill(process: asyncio.subprocess.Process | None) -> None:
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Session]:
        """Attach to the headed browser for the duration of a tool call."""
        if not self.running or not self.state:
            raise HandoffError("no handoff browser is running; call handoff first")
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser = None
        try:
            browser = await playwright.chromium.connect_over_cdp(
                self.state.cdp_url
            )
            contexts = browser.contexts
            context = contexts[0] if contexts else await browser.new_context()
            pages = context.pages
            if pages:
                index = min(max(self.active_page, 0), len(pages) - 1)
                page = pages[index]
            else:
                page = await context.new_page()
                self.active_page = 0
            for open_page in context.pages:
                self.observer.attach(open_page)
            yield Session(
                page=page,
                context=context,
                browser=browser,
                info=HANDOFF_INFO,
                closers=[],
            )
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            await playwright.stop()

    async def seed(
        self,
        cookies: list[dict[str, Any]] | None,
        url: str | None,
    ) -> dict[str, Any]:
        """Copy cookies from a live engine session into the headed profile."""
        seeded = 0
        if not cookies and not url:
            return {"seeded": 0}
        async with self.session() as session:
            if cookies:
                clean = []
                for cookie in cookies:
                    item = {
                        key: cookie[key]
                        for key in (
                            "name",
                            "value",
                            "domain",
                            "path",
                            "expires",
                            "httpOnly",
                            "secure",
                            "sameSite",
                        )
                        if key in cookie
                    }
                    if item.get("name") and item.get("value") is not None:
                        clean.append(item)
                if clean:
                    try:
                        await session.context.add_cookies(clean)
                        seeded = len(clean)
                    except Exception:
                        seeded = 0
            if url:
                try:
                    await session.goto(url, wait_until="domcontentloaded")
                except Exception:
                    pass
        return {"seeded": seeded}
