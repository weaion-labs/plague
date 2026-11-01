"""Token injection for the vendors that accept a solved response token.

This is best-effort by design. Every site wires its callbacks differently, so
we fill the standard hidden fields, fire the usual events, and call the
well-known reCAPTCHA callback registry when it is reachable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("plague.challenge.inject")

FIELDS: dict[str, tuple[str, ...]] = {
    "recaptcha": ("g-recaptcha-response",),
    "hcaptcha": ("h-captcha-response", "g-recaptcha-response"),
    "cloudflare_turnstile": ("cf-turnstile-response",),
    "aws_waf": (),
}

_INJECT_JS = r"""
(args) => {
  const fields = args.fields || [];
  let touched = 0;
  for (const name of fields) {
    let el = document.querySelector(
      `textarea[name="${name}"], input[name="${name}"], #${name}`
    );
    if (!el) {
      el = document.createElement("textarea");
      el.name = name;
      el.id = name;
      el.style.display = "none";
      (document.body || document.documentElement).appendChild(el);
    }
    el.value = args.token;
    if (el.tagName === "TEXTAREA") el.textContent = args.token;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    touched += 1;
  }

  let called = 0;
  try {
    const clients = (window.___grecaptcha_cfg || {}).clients || {};
    for (const key of Object.keys(clients)) {
      const client = clients[key] || {};
      for (const inner of Object.keys(client)) {
        const cb = client[inner] && client[inner].callback;
        if (typeof cb === "function") {
          cb(args.token);
          called += 1;
        }
      }
    }
  } catch (e) {}

  try {
    const cfg = window.hcaptcha && window.hcaptcha._config;
    if (cfg && typeof cfg.callback === "function") {
      cfg.callback(args.token);
      called += 1;
    }
  } catch (e) {}

  return { touched, called };
}
"""


async def inject_token(page: Any, vendor: str, token: str) -> bool:
    fields = list(FIELDS.get(vendor, ()))
    if not fields:
        return False
    try:
        result = await page.evaluate(
            _INJECT_JS, {"fields": fields, "token": token}
        )
    except Exception as exc:
        log.debug("token injection failed: %s", exc)
        return False
    if not isinstance(result, dict):
        return False
    return bool(result.get("touched") or result.get("called"))


async def wait_for_token(
    page: Any, vendor: str, timeout_ms: int = 300_000, interval_ms: int = 500
) -> str | None:
    """Wait until a human (or the page's own JS) fills a response field."""
    fields = list(FIELDS.get(vendor, ()))
    if not fields:
        return None
    expression = """
    (fields) => {
      for (const name of fields) {
        const el = document.querySelector(
          `textarea[name="${name}"], input[name="${name}"], #${name}`
        );
        if (el && el.value && el.value.trim().length > 0) return el.value;
      }
      return null;
    }
    """
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        try:
            value = await page.evaluate(expression, fields)
        except Exception:
            value = None
        if value:
            return str(value)
        await asyncio.sleep(interval_ms / 1000)
    return None
