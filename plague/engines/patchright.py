"""Patchright: a patched Playwright with runtime stealth, no license.

Patchright is a drop-in Playwright replacement with CDP and runtime patches. It
does not ship a custom Chromium binary, so it is weaker than Cloak against deep
fingerprinting, but it needs no account, no seat, and no license server. It is
the no-login stealth-lite tier between stock Chrome and Cloak.
"""

from __future__ import annotations

import importlib.util
import logging

from ..models import Capability, EngineInfo, Profile
from .base import BaseEngine, EngineError, EngineUnavailable, Session, playwright_proxy

log = logging.getLogger("plague.engine.patchright")

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


class PatchrightEngine(BaseEngine):
    info = EngineInfo(
        name="patchright",
        capabilities=CAPABILITIES,
        description="Patched Playwright Chromium with runtime stealth, no license",
    )

    def availability(self) -> tuple[bool, str]:
        if importlib.util.find_spec("patchright") is None:
            return False, "patchright not installed (pip install patchright)"
        return True, "installed"

    async def open(self, profile: Profile) -> Session:
        try:
            from patchright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - depends on the install
            raise EngineUnavailable(
                f"patchright not installed: {exc}"
            ) from exc

        pw = await async_playwright().start()
        try:
            launch_kwargs: dict = {
                "headless": profile.headless,
                "args": ["--disable-dev-shm-usage"],
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
                page = (
                    context.pages[0]
                    if context.pages
                    else await context.new_page()
                )
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
            raise EngineError(f"patchright failed to launch: {exc}") from exc
