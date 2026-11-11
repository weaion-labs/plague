"""Compact, ref-based page snapshots for agent tool calls.

A snapshot returns the interactive elements of the current page with short
refs like ``e1``. The ref is stored on the element as a ``data-plague-ref``
attribute, so a later ``click`` or ``fill`` can address it without guessing at
CSS. Refs are only valid until the page navigates or the DOM changes, which is
why ``act`` recommends a fresh snapshot after each step that mutates the page.

The walk intentionally does not filter on layout visibility. Lightpanda has no
layout engine, so ``offsetParent`` and ``getClientRects`` are not reliable
there, and an empty snapshot would be worse than a slightly noisy one.
"""

from __future__ import annotations

from typing import Any

MAX_ELEMENTS = 250


def _snapshot_js(limit: int) -> str:
    return r"""
(() => {
  const limit = __LIMIT__;
  const selector = [
    "a[href]",
    "button",
    "input:not([type=hidden])",
    "textarea",
    "select",
    "summary",
    "[contenteditable=true]",
    "[role=button]",
    "[role=link]",
    "[role=checkbox]",
    "[role=radio]",
    "[role=switch]",
    "[role=tab]",
    "[role=textbox]",
    "[role=combobox]"
  ].join(",");

  document.querySelectorAll("[data-plague-ref]").forEach((el) => {
    el.removeAttribute("data-plague-ref");
  });

  const clean = (value) =>
    (value || "").replace(/\s+/g, " ").trim().slice(0, 160);

  const roleOf = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button" || tag === "summary") return "button";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "submit" || type === "button" || type === "reset") return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    return "element";
  };

  const nameOf = (el, role) => {
    const direct = clean(
      el.getAttribute("aria-label") ||
        el.getAttribute("title") ||
        el.getAttribute("placeholder") ||
        el.getAttribute("alt")
    );
    if (direct) return direct;
    const text = clean(el.textContent);
    if (text) return text;
    const value = clean(el.value);
    if (value) return value;
    const name = clean(el.getAttribute("name"));
    if (name) return name;
    return role;
  };

  const nodes = Array.from(document.querySelectorAll(selector));
  const seen = new Set();
  const elements = [];
  let truncated = false;

  for (const el of nodes) {
    if (seen.has(el)) continue;
    seen.add(el);
    if (elements.length >= limit) {
      truncated = true;
      break;
    }
    const role = roleOf(el);
    const ref = "e" + (elements.length + 1);
    el.setAttribute("data-plague-ref", ref);
    const item = {
      ref: ref,
      role: role,
      name: nameOf(el, role),
      tag: el.tagName.toLowerCase()
    };
    const href = el.getAttribute("href");
    if (href) item.href = String(el.href || href).slice(0, 300);
    const type = el.getAttribute("type");
    if (type) item.type = type;
    if ("checked" in el) item.checked = !!el.checked;
    if (el.disabled) item.disabled = true;
    if (el.value && (role === "textbox" || role === "combobox")) {
      item.value = clean(el.value);
    }
    elements.push(item);
  }

  return {
    url: location.href,
    title: document.title || "",
    count: elements.length,
    truncated: truncated,
    elements: elements
  };
})()
""".replace("__LIMIT__", str(int(limit)))


async def collect(session: Any, *, limit: int = MAX_ELEMENTS) -> dict[str, Any]:
    """Return the ref snapshot for the session's current page."""
    limit = max(1, min(int(limit), MAX_ELEMENTS))
    value = await session.evaluate(_snapshot_js(limit))
    if not isinstance(value, dict):
        return {
            "url": getattr(session.page, "url", ""),
            "title": await session.title(),
            "count": 0,
            "truncated": False,
            "elements": [],
        }
    elements = value.get("elements")
    if not isinstance(elements, list):
        elements = []
    return {
        "url": str(value.get("url") or getattr(session.page, "url", "")),
        "title": str(value.get("title") or ""),
        "count": len(elements),
        "truncated": bool(value.get("truncated")),
        "elements": elements,
    }
