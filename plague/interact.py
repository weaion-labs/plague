"""Action parsing and execution on a live browser session.

Actions are the tool-call alternative to generated Playwright scripts. A caller
can address an element by CSS selector or by a snapshot ref, which is the short
``e3`` identifier returned by ``plague.snapshot``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Action

REF_PATTERN = re.compile(r"^e\d+$")

ACTION_TYPES = frozenset(
    {
        "click",
        "fill",
        "press",
        "hover",
        "select",
        "check",
        "uncheck",
        "set_files",
        "wait_for",
        "wait",
        "evaluate",
        "scroll",
        "back",
        "goto",
    }
)


class ActionError(ValueError):
    """A malformed or unsupported action."""


def parse_actions(
    raw: Iterable[Action | dict[str, Any]] | None,
) -> list[Action]:
    """Normalise tool input into ``Action`` objects with validation."""
    if not raw:
        return []
    parsed: list[Action] = []
    for index, item in enumerate(raw):
        if isinstance(item, Action):
            action = item
        elif isinstance(item, dict):
            unknown = set(item) - {"type", "selector", "ref", "value", "timeout_ms"}
            if unknown:
                raise ActionError(
                    f"action {index}: unknown fields {sorted(unknown)}"
                )
            if "type" not in item:
                raise ActionError(f"action {index}: missing 'type'")
            action = Action(
                type=str(item["type"]),
                selector=item.get("selector"),
                ref=item.get("ref"),
                value=(
                    None
                    if item.get("value") is None
                    else str(item["value"])
                ),
                timeout_ms=(
                    None
                    if item.get("timeout_ms") is None
                    else int(item["timeout_ms"])
                ),
            )
        else:
            raise ActionError(
                f"action {index}: expected an object, got {type(item).__name__}"
            )
        kind = action.type.lower()
        if kind not in ACTION_TYPES:
            raise ActionError(
                f"action {index}: unknown type {action.type!r}; "
                f"expected one of {', '.join(sorted(ACTION_TYPES))}"
            )
        if (
            kind in {"wait", "evaluate", "scroll", "goto", "set_files"}
            and action.value is None
        ):
            raise ActionError(f"action {index}: {kind} needs 'value'")
        parsed.append(action)
    return parsed


def selector_for(action: Action) -> str:
    """Resolve a snapshot ref or a CSS selector into one selector."""
    if action.ref:
        ref = action.ref.strip().lstrip("@")
        if not REF_PATTERN.match(ref):
            raise ActionError(
                f"invalid ref {action.ref!r}; expected a value like 'e3'"
            )
        return f'[data-plague-ref="{ref}"]'
    if action.selector:
        return action.selector
    raise ActionError(f"{action.type} action needs a 'ref' or 'selector'")


async def _resolve(session: Any, action: Action) -> tuple[str, int | None]:
    """Return the selector and timeout, failing fast on a stale ref."""
    selector = selector_for(action)
    timeout_ms = action.timeout_ms
    if action.ref:
        if timeout_ms is None:
            timeout_ms = 5_000
        try:
            present = await session.exists(selector)
        except Exception:
            present = True
        if not present:
            raise ActionError(
                f"ref {action.ref} is not on the page; take a fresh snapshot"
            )
    return selector, timeout_ms


async def run_actions(session: Any, actions: Iterable[Action]) -> None:
    """Run parsed actions in order on an open session."""
    for index, action in enumerate(actions):
        kind = action.type.lower()
        try:
            if kind == "click":
                selector, timeout = await _resolve(session, action)
                await session.click(selector, timeout)
            elif kind == "fill":
                selector, timeout = await _resolve(session, action)
                await session.fill(selector, action.value or "", timeout)
            elif kind == "press":
                selector, timeout = await _resolve(session, action)
                await session.press(selector, action.value or "Enter", timeout)
            elif kind == "hover":
                selector, timeout = await _resolve(session, action)
                await session.hover(selector, timeout)
            elif kind == "select":
                if action.value is None:
                    raise ActionError("select action needs 'value'")
                selector, timeout = await _resolve(session, action)
                await session.select_option(selector, action.value, timeout)
            elif kind == "check":
                selector, timeout = await _resolve(session, action)
                await session.check(selector, timeout)
            elif kind == "uncheck":
                selector, timeout = await _resolve(session, action)
                await session.uncheck(selector, timeout)
            elif kind == "set_files":
                selector, timeout = await _resolve(session, action)
                paths = [
                    path.strip()
                    for path in (action.value or "").splitlines()
                    if path.strip()
                ]
                if not paths:
                    raise ActionError("set_files action needs a path")
                await session.set_input_files(
                    selector,
                    paths if len(paths) > 1 else paths[0],
                    timeout,
                )
            elif kind == "wait_for":
                await session.wait_for_selector(
                    selector_for(action), action.timeout_ms
                )
            elif kind == "wait":
                await session.wait_for_timeout(int(action.value or 1000))
            elif kind == "evaluate":
                await session.evaluate(action.value or "")
            elif kind == "scroll":
                offset = int(action.value or 800)
                await session.evaluate(f"window.scrollBy(0, {offset})")
            elif kind == "back":
                await session.back()
            elif kind == "goto":
                if not action.value:
                    raise ActionError("goto action needs a URL in 'value'")
                await session.goto(action.value, timeout_ms=action.timeout_ms)
            else:  # pragma: no cover - parse_actions guards this
                raise ActionError(f"unknown action type: {action.type!r}")
        except ActionError:
            raise
        except Exception as exc:
            raise ActionError(
                f"action {index} ({kind}) failed: {type(exc).__name__}: {exc}"
            ) from exc
