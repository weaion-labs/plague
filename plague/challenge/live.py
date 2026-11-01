"""Live solver hints from the rendered page.

Some sites inject the widget after load, so scanning the initial HTML is not
enough. The capture script records sitekey/action/cdata from render calls; this
module also falls back to the widget DOM and its iframe.
"""

from __future__ import annotations

from typing import Any

HINTS_JS = r"""
(vendor) => {
  const store = window.__plague_sitekeys || {};
  const result = {
    sitekey: store[vendor] || null,
    action: store[vendor + "_action"] || null,
    cdata: store[vendor + "_cdata"] || null,
  };

  const selectors = {
    recaptcha: [".g-recaptcha[data-sitekey]", '[data-sitekey][class*="g-recaptcha"]'],
    hcaptcha: [".h-captcha[data-sitekey]", '[data-sitekey][class*="h-captcha"]'],
    cloudflare_turnstile: [".cf-turnstile[data-sitekey]", '[data-sitekey][class*="cf-turnstile"]'],
  };
  if (!result.sitekey) {
    for (const selector of (selectors[vendor] || [])) {
      const element = document.querySelector(selector);
      if (element) {
        result.sitekey = element.getAttribute("data-sitekey");
        break;
      }
    }
  }

  if (!result.sitekey) {
    for (const frame of Array.from(document.querySelectorAll("iframe"))) {
      const src = frame.src || "";
      let match = null;
      if (vendor === "recaptcha" && src.includes("hcaptcha")) {
        // hCaptcha iframes carry recaptchacompat=true; do not treat them as
        // reCAPTCHA just because the substring is present.
      } else if (vendor === "recaptcha" && (src.includes("google.com/recaptcha") || src.includes("recaptcha/api2") || src.includes("recaptcha/enterprise"))) {
        match = src.match(/[?&]k=([^&]+)/);
      } else if (vendor === "hcaptcha" && src.includes("hcaptcha")) {
        match = src.match(/[?&]sitekey=([^&]+)/);
      } else if (vendor === "cloudflare_turnstile" && src.includes("challenges.cloudflare.com")) {
        match = src.match(/[?&](?:k|sitekey)=([^&]+)/);
      }
      if (match) {
        result.sitekey = decodeURIComponent(match[1]);
        break;
      }
    }
  }

  return result;
}
"""


async def extract_hints(page: Any, vendor: str) -> dict[str, str | None]:
    try:
        value = await page.evaluate(HINTS_JS, vendor)
    except Exception:
        return {"sitekey": None, "action": None, "cdata": None}
    if not isinstance(value, dict):
        return {"sitekey": None, "action": None, "cdata": None}
    return {
        "sitekey": str(value["sitekey"]) if value.get("sitekey") else None,
        "action": str(value["action"]) if value.get("action") else None,
        "cdata": str(value["cdata"]) if value.get("cdata") else None,
    }


async def extract_sitekey(page: Any, vendor: str) -> str | None:
    return (await extract_hints(page, vendor))["sitekey"]
