"""Capture solver hints before the page can use them.

The Turnstile and hCaptcha widgets often receive their sitekey through a
`render(element, options)` call, not through a `data-sitekey` attribute. Hook
the render function as soon as the vendor object appears and record the
sitekey, action, and cdata.
"""

from __future__ import annotations

from typing import Any

CAPTURE_JS = r"""
(() => {
  if (window.__plague_capture_installed) return;
  window.__plague_capture_installed = true;
  window.__plague_sitekeys = window.__plague_sitekeys || {};

  const hook = (name, vendor) => {
    let wrapped = null;
    const attach = () => {
      const api = window[name];
      if (!api || typeof api.render !== "function" || api === wrapped) return;
      const original = api.render;
      api.render = function (element, options) {
        try {
          if (options) {
            if (options.sitekey) window.__plague_sitekeys[vendor] = options.sitekey;
            if (options.action) window.__plague_sitekeys[vendor + "_action"] = options.action;
            if (options.cdata) window.__plague_sitekeys[vendor + "_cdata"] = options.cdata;
          }
        } catch (e) {}
        return original.apply(this, arguments);
      };
      wrapped = api;
    };
    attach();
    const timer = setInterval(attach, 50);
    setTimeout(() => clearInterval(timer), 15000);
  };

  hook("turnstile", "cloudflare_turnstile");
  hook("grecaptcha", "recaptcha");
  hook("hcaptcha", "hcaptcha");
})();
"""


async def install(session: Any) -> None:
    try:
        await session.add_init_script(CAPTURE_JS)
    except Exception:
        return None
