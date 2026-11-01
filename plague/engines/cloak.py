"""CloakBrowser: source-patched stealth Chromium behind the Playwright API."""

from __future__ import annotations

import logging

from ..models import Capability, EngineInfo, Profile
from .base import BaseEngine, EngineError, EngineUnavailable, Session

log = logging.getLogger("plague.engine.cloak")

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


class CloakEngine(BaseEngine):
    info = EngineInfo(
        name="cloak",
        capabilities=CAPABILITIES,
        description="CloakBrowser stealth Chromium with C++ fingerprint patches",
    )

    def availability(self) -> tuple[bool, str]:
        try:
            import cloakbrowser

            try:
                info = cloakbrowser.binary_info()
                installed = bool(info.get("installed"))
                version = info.get("version", "unknown")
                if installed:
                    return True, f"chromium {version}"
                return True, f"chromium {version} (downloads on first launch)"
            except Exception:
                return True, "installed (binary checked at launch)"
        except Exception as exc:
            return False, f"cloakbrowser not installed: {exc}"

    async def open(self, profile: Profile) -> Session:
        try:
            from cloakbrowser import (
                launch_async,
                launch_persistent_context_async,
            )
        except Exception as exc:
            raise EngineUnavailable(f"cloakbrowser not installed: {exc}") from exc

        kwargs: dict = {
            "headless": profile.headless,
            "humanize": profile.humanize,
            "human_preset": profile.human_preset,
            "geoip": profile.geoip,
            "proxy": profile.proxy,
            "locale": profile.locale,
            "license_key": self.config.cloak_license_key,
        }
        if profile.timezone:
            kwargs["timezone"] = profile.timezone
        if profile.user_agent:
            kwargs["user_agent"] = profile.user_agent
        if profile.viewport:
            kwargs["viewport"] = profile.viewport

        try:
            if profile.user_data_dir:
                context = await launch_persistent_context_async(
                    profile.user_data_dir, **kwargs
                )
                page = context.pages[0] if context.pages else await context.new_page()
                return Session(
                    page=page,
                    context=context,
                    browser=None,
                    info=self.info,
                    closers=[context.close],
                )

            browser = await launch_async(**kwargs)
            context_kwargs: dict = {}
            if profile.storage_state:
                context_kwargs["storage_state"] = profile.storage_state
            if profile.extra_headers:
                context_kwargs["extra_http_headers"] = profile.extra_headers
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            return Session(
                page=page,
                context=context,
                browser=browser,
                info=self.info,
                closers=[browser.close],
            )
        except Exception as exc:
            raise EngineError(f"cloak failed to launch: {exc}") from exc
