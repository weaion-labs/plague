"""Stock Chromium / Google Chrome through Playwright."""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from ..models import Capability, EngineInfo, Profile
from .base import BaseEngine, EngineError, Session, playwright_proxy

log = logging.getLogger("plague.engine.chrome")

CAPABILITIES = frozenset(
    {
        Capability.VISUAL,
        Capability.PDF,
        Capability.VIDEO,
        Capability.TRACING,
        Capability.EXTENSIONS,
        Capability.DOWNLOADS,
        Capability.ROUTES,
        Capability.STORAGE_STATE,
        Capability.COOKIES,
        Capability.INIT_SCRIPT,
    }
)


class ChromeEngine(BaseEngine):
    info = EngineInfo(
        name="chrome",
        capabilities=CAPABILITIES,
        description="Full Playwright Chromium or installed Google Chrome",
    )

    def availability(self) -> tuple[bool, str]:
        if self.config.chrome_executable:
            return True, self.config.chrome_executable
        try:
            import playwright  # noqa: F401

            return True, "playwright bundled chromium"
        except Exception as exc:
            return False, f"playwright unavailable: {exc}"

    async def open(self, profile: Profile) -> Session:
        pw = await async_playwright().start()
        try:
            launch_kwargs: dict = {
                "headless": profile.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            }
            if profile.proxy:
                launch_kwargs["proxy"] = playwright_proxy(profile.proxy)
            if self.config.chrome_channel:
                launch_kwargs["channel"] = self.config.chrome_channel
            elif self.config.chrome_executable:
                launch_kwargs["executable_path"] = self.config.chrome_executable

            context_kwargs: dict = {"locale": profile.locale}
            if profile.timezone:
                context_kwargs["timezone_id"] = profile.timezone
            if profile.user_agent:
                context_kwargs["user_agent"] = profile.user_agent
            if profile.viewport:
                context_kwargs["viewport"] = profile.viewport
            if profile.extra_headers:
                context_kwargs["extra_http_headers"] = profile.extra_headers
            if profile.storage_state:
                context_kwargs["storage_state"] = profile.storage_state

            if profile.user_data_dir:
                context = await pw.chromium.launch_persistent_context(
                    profile.user_data_dir, **launch_kwargs, **context_kwargs
                )
                browser = None
                page = context.pages[0] if context.pages else await context.new_page()
                return Session(
                    page=page,
                    context=context,
                    browser=browser,
                    info=self.info,
                    closers=[pw.stop, context.close],
                )

            browser = await pw.chromium.launch(**launch_kwargs)
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            return Session(
                page=page,
                context=context,
                browser=browser,
                info=self.info,
                closers=[pw.stop, browser.close],
            )
        except Exception as exc:
            try:
                await pw.stop()
            except Exception:
                pass
            raise EngineError(f"chrome failed to launch: {exc}") from exc
