"""Best-effort interactions with challenge widgets.

Only Cloudflare's Turnstile exposes a plain checkbox in a cross-origin frame
that can be clicked from the parent page. Everything else either needs a token
or a fingerprint that passes the risk score.
"""

from __future__ import annotations

import logging

log = logging.getLogger("plague.challenge.actions")


async def click_turnstile(page, timeout_ms: int = 2500) -> bool:
    """Click the Turnstile checkbox inside its iframe, if one is present."""
    try:
        frames = page.frames
    except Exception:
        return False

    for frame in frames:
        try:
            url = frame.url or ""
        except Exception:
            continue
        if "challenges.cloudflare.com" not in url:
            continue
        for selector in (
            'input[type="checkbox"]',
            "label",
            "#challenge-stage",
        ):
            try:
                element = await frame.query_selector(selector)
                if element is None:
                    continue
                await element.click(timeout=timeout_ms)
                log.info("clicked turnstile widget via %s", selector)
                return True
            except Exception as exc:
                log.debug("turnstile click failed on %s: %s", selector, exc)
    return False
