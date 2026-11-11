"""Project-local MCP server for Plague.

Run with:

    python -m plague.mcp_server

It speaks MCP over stdio. The server is intentionally not installed as a
console script; OpenCode starts it from `.opencode/opencode.json` with the
project root as its working directory.

The server keeps one warm fast-tier browser across tool calls, so a browsing
loop costs a navigation instead of a process start. A headed handoff browser
can be launched on demand and driven either through ``act`` or by an external
harness attached to its CDP endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

# The MCP SDK's settings model emits this on Python 3.14 before the server
# starts. It is harmless and would otherwise pollute the stdio stderr log.
warnings.filterwarnings(
    "ignore",
    message="Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP

from . import Config, Plague, PlagueError, Tier
from .challenge import detect as detect_challenge
from .config import project_cache_dir
from .engines import Session
from .fingerprint import collect as collect_fingerprint
from .handoff import HandoffError, HandoffManager, _display_mode
from .harexport import (
    build_har as build_har_export,
    curl_commands,
    write_export,
)
from .http import HAS_CURL_CFFI
from .http import request as http_request
from .interact import ActionError, parse_actions, run_actions
from .models import Attempt, Capability, Profile
from .observe import Observer
from .recipes import (
    RecipeError,
    delete as delete_recipe,
    listing as list_recipes,
    load as load_recipe,
    save as save_recipe,
    to_dicts as recipe_dicts,
)
from .serialize import (
    challenge_dict,
    error_dict,
    probe_dict,
    result_dict,
)
from .snapshot import collect as collect_snapshot
from .storage import (
    StorageError,
    delete as delete_state,
    listing as list_states,
    load as load_state,
    save as save_state,
)

ROOT = Path(__file__).resolve().parents[1]
PATCHED_BINARY = ROOT / ".plague" / "lightpanda-src" / "zig-out" / "bin" / "lightpanda"
log = logging.getLogger("plague.mcp")

# Prefer the locally built Chrome-persona binary unless the caller chose one.
if PATCHED_BINARY.is_file() and not os.environ.get("PLAGUE_LIGHTPANDA_BIN"):
    os.environ["PLAGUE_LIGHTPANDA_BIN"] = str(PATCHED_BINARY)

INSTRUCTIONS = """
Plague is a tiered browser router: Lightpanda first for speed, CloakBrowser when
a wall appears, stock Chrome as the reference. It keeps one warm fast session,
so consecutive reads do not pay a process start.

Reading and acting:
- `fetch` retrieves a page. `tier=auto` uses the warm fast session and escalates
  to Cloak on a wall. Pass `actions` to click or fill before extraction.
- `snapshot` lists interactive elements with short refs such as `e3`.
- `act` runs click/fill/press/select/check/scroll/back/goto actions on the warm
  session or on the headed handoff browser. Prefer refs over CSS selectors.
- `handoff` launches a headed Chrome, or attaches to an existing CDP endpoint,
  and returns a CDP URL. Use it for logins, 2FA, payments, and risk-score walls
  that a human must clear. `release` closes or detaches.
- `recipe_save` stores a working action list and `recipe_run` replays it, so a
  repeated flow does not need regenerated scripts.

Policy:
- `PLAGUE_ALLOWED_DOMAINS` restricts every navigation when set.
- `PLAGUE_SOLVE_DOMAINS` restricts where the token solver may run.
- Without solver keys, token walls are detected and classified but no token is
  purchased. Risk-score walls are never solved; they need a better identity, a
  human, or a residential IP.

Recon and sessions:
- `network` and `console` read the request log and page logs of the warm page.
- `network_export` writes the observed requests as HAR or curl commands.
- `api_request` replays a raw HTTP request with the warm session cookies. It
  uses browser impersonation by default, so it carries a Chrome TLS fingerprint.
- `screenshot` needs a rendering tier: stealth, chrome, or handoff.
- `tabs`, `tab_open`, `tab_switch`, and `tab_close` manage pages on Chrome or
  Cloak. Lightpanda cannot open extra tabs.
- `storage_save` and `storage_load` move cookies and localStorage between runs.
- After an explicit stealth or chrome fetch, that host stays pinned to the
  heavy tier for PLAGUE_HOST_TIER_TTL seconds, so `auto` keeps the session.
""".strip()


def _config(
    *,
    timeout_ms: int | None = None,
    solve_widgets: bool = False,
    headed: bool = False,
    proxy: str | None = None,
) -> Config:
    config = Config.from_env()
    if timeout_ms is not None:
        config.timeout_ms = timeout_ms
    if solve_widgets:
        config.solve_present = True
    if headed:
        config.headless = False
    if proxy:
        config.proxy = proxy
    return config


def _trim(data: dict[str, Any], max_text_chars: int) -> dict[str, Any]:
    text = data.get("text")
    if isinstance(text, str) and len(text) > max_text_chars:
        data["text"] = text[:max_text_chars] + "...[truncated]"
    return data


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


@dataclass
class _Warm:
    session: Session
    last_used: float
    in_use: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    observer: Observer = field(default_factory=Observer)


class _Runtime:
    """Owns the long-lived Plague instance, warm sessions, and handoff."""

    def __init__(self) -> None:
        self._plague: Plague | None = None
        self._sessions: dict[str, _Warm] = {}
        self._lock = asyncio.Lock()
        self.handoff: HandoffManager | None = None
        self.host_tiers: dict[str, tuple[str, float]] = {}
        self.overrides: dict[str, Profile] = {}
        self.last_tier: str = "fast"

    def plague(self) -> Plague:
        if self._plague is None:
            self._plague = Plague(Config.from_env())
        return self._plague

    def config(self) -> Config:
        return self.plague().config

    def handoff_manager(self) -> HandoffManager:
        if self.handoff is None:
            self.handoff = HandoffManager(self.config())
        return self.handoff

    def check_url(self, url: str) -> None:
        self.plague().check_url(url)

    async def sweep(self) -> None:
        ttl = self.config().mcp_idle_s
        now = time.monotonic()
        for key, entry in list(self._sessions.items()):
            if entry.in_use:
                continue
            if now - entry.last_used > ttl:
                await self._drop(key)

    async def _drop(self, key: str) -> None:
        entry = self._sessions.pop(key, None)
        if entry is not None:
            try:
                await entry.session.close()
            except Exception:
                pass
        for host, (tier, _) in list(self.host_tiers.items()):
            if tier == key:
                self.host_tiers.pop(host, None)

    async def drop(self, key: str) -> None:
        async with self._lock:
            await self._drop(key)

    async def _close_heavies(self, keep: str) -> None:
        for key in ("stealth", "chrome"):
            if key != keep and key in self._sessions:
                await self._drop(key)

    @asynccontextmanager
    async def using(self, tier: Tier | str) -> AsyncIterator[Session]:
        key = _tier_key(tier)
        async with self._lock:
            entry = self._sessions.get(key)
            now = time.monotonic()
            if entry is not None and now - entry.last_used > self.config().mcp_idle_s:
                await self._drop(key)
                entry = None
            if entry is None:
                if key != "fast":
                    await self._close_heavies(key)
                profile = self.overrides.get(key)
                try:
                    session = await self.plague().open_session(key, profile)
                except PlagueError:
                    if key != "fast":
                        raise
                    session = await self.plague().open_session(
                        Tier.AUTO, profile
                    )
                entry = _Warm(session=session, last_used=now)
                self._sessions[key] = entry
            entry.observer.attach(entry.session.page)
            entry.in_use = True
            entry.last_used = now
            self.last_tier = key
        await entry.lock.acquire()
        try:
            yield entry.session
        finally:
            entry.lock.release()
            entry.in_use = False
            entry.last_used = time.monotonic()

    def describe(self) -> dict[str, Any]:
        return {
            key: {
                "engine": entry.session.info.name,
                "idle_s": round(time.monotonic() - entry.last_used, 1),
                "in_use": entry.in_use,
            }
            for key, entry in self._sessions.items()
        }

    def tier_key(self, tier: Tier | str) -> str:
        if str(tier) == "auto" or tier is Tier.AUTO:
            return self.last_tier
        return _tier_key(tier)

    def pins(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            host: {
                "tier": tier,
                "expires_in_s": round(max(0.0, expires - now), 1),
            }
            for host, (tier, expires) in self.host_tiers.items()
            if expires > now
        }

    def pinned_tier(self, url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return None
        entry = self.host_tiers.get(host)
        if entry is None:
            return None
        tier, expires = entry
        if time.monotonic() > expires:
            self.host_tiers.pop(host, None)
            return None
        return tier

    def pin(self, url: str, tier: str) -> None:
        if tier not in {"stealth", "chrome"}:
            return
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return
        self.host_tiers[host] = (
            tier,
            time.monotonic() + self.config().host_tier_ttl_s,
        )

    async def set_profile(self, key: str, profile: Profile) -> None:
        async with self._lock:
            await self._drop(key)
            self.overrides[key] = profile

    async def close_sessions(self) -> None:
        for key in list(self._sessions):
            await self._drop(key)
        self.overrides.clear()
        self.host_tiers.clear()

    async def close_all(self) -> None:
        await self.close_sessions()
        if self.handoff is not None:
            try:
                await self.handoff.stop()
            except Exception:
                pass
        if self._plague is not None:
            try:
                await self._plague.close()
            except Exception:
                pass
            self._plague = None


def _tier_key(tier: Tier | str) -> str:
    value = Tier(tier)
    return "fast" if value is Tier.AUTO else value.value


RUNTIME = _Runtime()


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    try:
        yield {}
    finally:
        await RUNTIME.close_all()


mcp = FastMCP(
    "plague",
    instructions=INSTRUCTIONS,
    log_level="WARNING",
    lifespan=_lifespan,
)


@mcp.tool()
async def doctor() -> dict[str, Any]:
    """Show engine availability, solver, warm sessions, and handoff state."""
    plague = RUNTIME.plague()
    return {
        "engines": plague.describe_engines(),
        "solver": {
            "active": plague.solver.name if plague.solver else None,
            "error": plague.solver_error,
        },
        "policy": {
            "allowed_domains": plague.config.allowed_domains,
            "solve_domains": plague.config.solve_domains,
        },
        "warm_sessions": RUNTIME.describe(),
        "host_tiers": RUNTIME.pins(),
        "handoff": (
            RUNTIME.handoff.describe()
            if RUNTIME.handoff
            else {"running": False}
        ),
        "idle_s": plague.config.mcp_idle_s,
        "keep_stealth_warm": plague.config.mcp_keep_stealth,
        "http_client": "curl_cffi" if HAS_CURL_CFFI else "httpx",
        "display": _display_mode(),
        "handoff_ozone": plague.config.handoff_ozone,
        "patched_lightpanda": str(PATCHED_BINARY)
        if PATCHED_BINARY.is_file()
        else None,
        "lightpanda_bin": os.environ.get("PLAGUE_LIGHTPANDA_BIN"),
    }


async def _escalate(
    plague: Plague,
    url: str,
    warm_result,
    *,
    timeout_ms: int,
    actions: list | None,
):
    """Re-run a blocked fast-tier page on Cloak.

    Auto escalation is read-only by default: the Cloak session is closed after
    the fetch so it does not hold a paid concurrency seat. Set
    PLAGUE_MCP_KEEP_STEALTH=1 to keep it warm for follow-up `act` calls.
    """
    if RUNTIME.config().mcp_keep_stealth:
        try:
            async with RUNTIME.using("stealth") as session:
                cold = await plague.fetch_on(
                    session,
                    url,
                    timeout_ms=timeout_ms,
                    actions=actions,
                )
        except Exception:
            await RUNTIME.drop("stealth")
            raise
    else:
        cold = await plague.fetch(
            url,
            tier=Tier.STEALTH,
            timeout_ms=timeout_ms,
            actions=actions,
        )
    warm_attempt = (
        warm_result.attempts[0]
        if warm_result.attempts
        else _warm_attempt(warm_result)
    )
    cold.attempts.insert(0, warm_attempt)
    cold.elapsed_ms = warm_attempt.elapsed_ms + cold.elapsed_ms
    return cold


def _warm_attempt(result):
    return Attempt(
        engine=result.engine or "router",
        ok=False,
        elapsed_ms=result.elapsed_ms,
        status=result.status,
        challenge=result.challenge.label if result.challenge else None,
    )


def _needs_escalation(result) -> bool:
    if result.challenge and result.challenge.blocking:
        return True
    if result.status is None:
        return True
    return any(
        attempt.error and "shell" in attempt.error
        for attempt in result.attempts
    )


@mcp.tool()
async def fetch(
    url: str,
    tier: str = "auto",
    timeout_ms: int = 30_000,
    screenshot: str | None = None,
    solve_widgets: bool = False,
    headed: bool = False,
    proxy: str | None = None,
    include_html: bool = False,
    max_text_chars: int = 4_000,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch one URL through the tier router and return a structured result.

    Args:
        url: Page to fetch.
        tier: auto, fast, stealth, or chrome.
        timeout_ms: Navigation timeout in milliseconds.
        screenshot: Optional path for a full-page PNG. Forces a visual engine.
        solve_widgets: Also solve token widgets on pages that are not blocked.
        headed: Show the browser window. Bypasses the warm session.
        proxy: Proxy URL for this call. Bypasses the warm session.
        include_html: Include the full HTML in the result.
        max_text_chars: Truncate the extracted text to this many characters.
        actions: Optional click/fill/press actions to run before extraction.
    """
    await RUNTIME.sweep()
    if tier == "handoff":
        return _error(
            "fetch does not drive the handoff browser; use act tier=handoff "
            "or fetch the URL on a normal tier"
        )
    try:
        parsed = parse_actions(actions)
    except ActionError as exc:
        return _error(str(exc))
    try:
        RUNTIME.check_url(url)
    except PlagueError as exc:
        return _error(str(exc))

    if screenshot:
        Path(screenshot).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )

    plague = RUNTIME.plague()
    screenshot_path = str(Path(screenshot).expanduser()) if screenshot else None
    tier_value = Tier(tier)

    # Visual, headed, or explicitly proxied calls cannot reuse a warm session.
    if screenshot or headed or proxy:
        config = _config(
            timeout_ms=timeout_ms,
            solve_widgets=solve_widgets,
            headed=headed,
            proxy=proxy,
        )
        cold = Plague(config)
        try:
            result = await cold.fetch(
                url,
                tier=tier,
                timeout_ms=timeout_ms,
                screenshot=screenshot_path,
                actions=parsed or None,
                headed=True if headed else None,
                proxy=proxy,
            )
        except PlagueError as exc:
            return error_dict(exc)
        finally:
            await cold.close()
        if tier_value in (Tier.STEALTH, Tier.CHROME) and result.ok:
            RUNTIME.pin(url, tier_value.value)
        data = result_dict(result, include_html=include_html)
        data["warm"] = False
        return _trim(data, max_text_chars)

    old_solve_present = plague.config.solve_present
    if solve_widgets:
        plague.config.solve_present = True
    warm_tier = tier_value
    if tier_value is Tier.AUTO:
        pinned = RUNTIME.pinned_tier(url)
        if pinned:
            warm_tier = Tier(pinned)
    try:
        try:
            async with RUNTIME.using(warm_tier) as session:
                result = await plague.fetch_on(
                    session,
                    url,
                    timeout_ms=timeout_ms,
                    actions=parsed or None,
                )
        except Exception:
            # A dead warm session is not fatal. Drop it and retry cold once.
            log.warning("warm session failed; retrying cold", exc_info=True)
            await RUNTIME.drop(_tier_key(warm_tier))
            result = await plague.fetch(
                url,
                tier=tier,
                timeout_ms=timeout_ms,
                actions=parsed or None,
            )
            data = result_dict(result, include_html=include_html)
            data["warm"] = False
            return _trim(data, max_text_chars)

        if (
            tier_value is Tier.AUTO
            and warm_tier is Tier.FAST
            and _needs_escalation(result)
        ):
            try:
                result = await _escalate(
                    plague,
                    url,
                    result,
                    timeout_ms=timeout_ms,
                    actions=parsed or None,
                )
            except Exception as exc:
                result.attempts.append(
                    Attempt(
                        engine="stealth",
                        ok=False,
                        elapsed_ms=0,
                        error=(
                            "escalation failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
    except PlagueError as exc:
        return error_dict(exc)
    finally:
        plague.config.solve_present = old_solve_present

    if tier_value in (Tier.STEALTH, Tier.CHROME) and result.ok:
        RUNTIME.pin(url, tier_value.value)
    if RUNTIME.config().mcp_keep_stealth and result.ok and result.engine == "cloak":
        RUNTIME.pin(url, "stealth")

    data = result_dict(result, include_html=include_html)
    data["warm"] = True
    data["tier"] = _tier_key(warm_tier)
    data["pinned"] = tier_value is Tier.AUTO and warm_tier is not Tier.FAST
    data["escalated"] = len(result.attempts) > 1
    return _trim(data, max_text_chars)


@mcp.tool()
async def act(
    actions: list[dict[str, Any]],
    tier: str = "auto",
    include_html: bool = False,
    max_text_chars: int = 4_000,
    snapshot: bool = False,
) -> dict[str, Any]:
    """Run actions on the current page and return its state.

    Actions address elements by snapshot ref (``{"type": "click", "ref": "e3"}``)
    or by CSS selector. Supported types: click, fill, press, hover, select,
    check, uncheck, set_files, wait_for, wait, evaluate, scroll, back, goto.

    Use ``tier="handoff"`` to drive the headed browser started by ``handoff``.
    Use ``tier="stealth"`` or ``tier="chrome"`` for a warm rendering session.

    ``goto`` actions are checked against PLAGUE_ALLOWED_DOMAINS. ``evaluate``
    runs arbitrary page JavaScript and is an explicit escape hatch.
    """
    await RUNTIME.sweep()
    try:
        parsed = parse_actions(actions)
    except ActionError as exc:
        return _error(str(exc))
    if not parsed:
        return _error("no actions supplied")
    for action in parsed:
        if action.type.lower() == "goto" and action.value:
            try:
                RUNTIME.check_url(action.value)
            except PlagueError as exc:
                return _error(str(exc))

    if tier != "handoff":
        key = RUNTIME.tier_key(tier)
        if key not in RUNTIME._sessions and not any(
            action.type.lower() == "goto" for action in parsed
        ):
            return _error(
                "no warm session yet; call fetch first or use a goto action"
            )

    started = time.monotonic()
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        try:
            async with manager.session() as session:
                return await _act_on(
                    session,
                    parsed,
                    include_html=include_html,
                    max_text_chars=max_text_chars,
                    snapshot=snapshot,
                    started=started,
                )
        except HandoffError as exc:
            return _error(str(exc))
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")

    try:
        async with RUNTIME.using(key) as session:
            return await _act_on(
                session,
                parsed,
                include_html=include_html,
                max_text_chars=max_text_chars,
                snapshot=snapshot,
                started=started,
            )
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")


async def _act_on(
    session: Session,
    actions: list,
    *,
    include_html: bool,
    max_text_chars: int,
    snapshot: bool,
    started: float,
) -> dict[str, Any]:
    current = str(getattr(session.page, "url", ""))
    if current in {"", "about:blank"} and not any(
        action.type.lower() == "goto" for action in actions
    ):
        return _error(
            "the session has no page yet; call fetch first or use a goto action"
        )
    await run_actions(session, actions)
    html = await session.content()

    challenge = detect_challenge(
        status=None,
        url=str(getattr(session.page, "url", "")),
        headers={},
        html=html,
    )
    data: dict[str, Any] = {
        "ok": True,
        "engine": session.info.name,
        "url": str(getattr(session.page, "url", "")),
        "title": await session.title(),
        "text": await session.text(),
        "challenge": challenge_dict(challenge),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    if challenge and challenge.blocking:
        data["hint"] = (
            "the page is blocked; use fetch with tier=stealth, configure a "
            "solver, or call handoff for a human step"
        )
    if include_html:
        data["html"] = html
    if snapshot:
        try:
            data["snapshot"] = await collect_snapshot(session)
        except Exception as exc:
            data["snapshot_error"] = f"{type(exc).__name__}: {exc}"
    return _trim(data, max_text_chars)


@mcp.tool()
async def snapshot(tier: str = "auto", limit: int = 250) -> dict[str, Any]:
    """List interactive page elements as compact refs for `act`."""
    await RUNTIME.sweep()
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        try:
            async with manager.session() as session:
                data = await collect_snapshot(session, limit=limit)
                data["engine"] = session.info.name
                return data
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")

    key = RUNTIME.tier_key(tier)
    if key not in RUNTIME._sessions:
        return _error("no warm session yet; call fetch first")

    try:
        async with RUNTIME.using(key) as session:
            data = await collect_snapshot(session, limit=limit)
            data["engine"] = session.info.name
            return data
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")


@mcp.tool()
async def network(
    tier: str = "auto",
    filter: str | None = None,
    limit: int = 100,
    include_body: bool = False,
    include_headers: bool = False,
    max_body_chars: int = 2_000,
    clear: bool = False,
) -> dict[str, Any]:
    """List requests seen by the current warm or handoff page.

    Entries carry method, URL, resource type, and response status when one
    arrived. Set include_body=true to attach a text body for JSON, HTML, XML, or
    JavaScript responses. This is the recon view: XHR endpoints and API paths.
    """
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return {"entries": [], "note": "no handoff browser is running"}
        entries = await manager.observer.network(
            filter=filter,
            limit=limit,
            include_body=include_body,
            include_headers=include_headers,
            max_body_chars=max_body_chars,
        )
        if clear:
            manager.observer.clear()
        return {"entries": entries, "engine": "handoff", "count": len(entries)}

    entry = RUNTIME._sessions.get(RUNTIME.tier_key(tier))
    if entry is None:
        return {"entries": [], "note": "no warm session; fetch a page first"}
    entries = await entry.observer.network(
        filter=filter,
        limit=limit,
        include_body=include_body,
        max_body_chars=max_body_chars,
    )
    if clear:
        entry.observer.clear()
    return {
        "entries": entries,
        "engine": entry.session.info.name,
        "count": len(entries),
    }


def _observer_for(tier: str):
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        return manager.observer if manager.running else None
    entry = RUNTIME._sessions.get(RUNTIME.tier_key(tier))
    return entry.observer if entry else None


@mcp.tool()
async def network_export(
    format: str = "har",
    path: str | None = None,
    filter: str | None = None,
    include_bodies: bool = True,
    limit: int = 200,
    tier: str = "auto",
) -> dict[str, Any]:
    """Export the request log as HAR or as curl commands.

    HAR is the evidence format for reports and DevTools. curl is the fast path
    for replaying a request by hand. Both contain live cookies and headers, so
    exports are written owner-only and should stay private.
    """
    observer = _observer_for(tier)
    if observer is None:
        return {"ok": False, "error": "no warm session or handoff browser"}
    fmt = format.strip().lower()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    export_dir = project_cache_dir() / "exports"
    warning = "export contains live cookies and headers; keep it private"

    if fmt == "har":
        data = await build_har_export(
            observer,
            filter=filter,
            limit=limit,
            include_bodies=include_bodies,
        )
        text = json.dumps(data, indent=2) + "\n"
        target = (
            Path(path).expanduser()
            if path
            else export_dir / f"har-{stamp}.json"
        )
        write_export(target, text)
        return {
            "ok": True,
            "format": "har",
            "path": str(target),
            "entries": len(data["log"]["entries"]),
            "warning": warning,
        }

    if fmt == "curl":
        commands = curl_commands(observer, filter=filter, limit=limit)
        target = None
        if path:
            target = write_export(
                path, "\n\n".join(commands) + "\n"
            )
        return {
            "ok": True,
            "format": "curl",
            "commands": commands,
            "count": len(commands),
            "path": str(target) if target else None,
            "warning": warning,
        }

    return _error("format must be 'har' or 'curl'")


@mcp.tool()
async def console(
    tier: str = "auto",
    filter: str | None = None,
    level: str | None = None,
    limit: int = 100,
    clear: bool = False,
) -> dict[str, Any]:
    """List console messages and uncaught page errors."""
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return {"entries": [], "note": "no handoff browser is running"}
        entries = manager.observer.logs(
            filter=filter, level=level, limit=limit
        )
        if clear:
            manager.observer.clear()
        return {"entries": entries, "engine": "handoff", "count": len(entries)}

    entry = RUNTIME._sessions.get(RUNTIME.tier_key(tier))
    if entry is None:
        return {"entries": [], "note": "no warm session; fetch a page first"}
    entries = entry.observer.logs(
        filter=filter, level=level, limit=limit
    )
    if clear:
        entry.observer.clear()
    return {
        "entries": entries,
        "engine": entry.session.info.name,
        "count": len(entries),
    }


async def _capture(
    session: Session,
    path: str | None,
    full_page: bool,
) -> dict[str, Any]:
    if not session.supports(Capability.VISUAL):
        return _error(
            f"engine {session.info.name!r} has no rendering; use "
            "tier=stealth or tier=chrome for a screenshot"
        )
    if path is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = str(Path(RUNTIME.config().screenshot_dir) / f"{stamp}.png")
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    await session.screenshot(str(target), full_page=full_page)
    return {
        "ok": True,
        "path": str(target),
        "url": str(getattr(session.page, "url", "")),
        "title": await session.title(),
        "engine": session.info.name,
    }


async def _session_cookies(url: str) -> list[dict[str, Any]]:
    for key in ("stealth", "chrome", "fast"):
        entry = RUNTIME._sessions.get(key)
        if entry is None:
            continue
        try:
            rows = await entry.session.cookies([url])
        except Exception:
            continue
        if rows:
            return list(rows)
    return []


@mcp.tool()
async def api_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    use_cookies: bool = True,
    follow_redirects: bool = False,
    timeout_ms: int = 30_000,
    impersonate: str | None = "chrome",
) -> dict[str, Any]:
    """Send a raw HTTP request, reusing cookies from the warm browser session.

    This is for authenticated API testing after the browser has established the
    session. By default it uses curl_cffi with a Chrome TLS and HTTP/2
    fingerprint, so it survives more WAF checks than a plain Python client. Set
    impersonate="none" to force the plain httpx path. It does not use the
    browser's exact build, so a strict target can still tell the difference.
    """
    try:
        RUNTIME.check_url(url)
    except PlagueError as exc:
        return _error(str(exc))
    cookies = await _session_cookies(url) if use_cookies else []
    merged = dict(headers or {})
    if cookies and not any(key.lower() == "cookie" for key in merged):
        merged["cookie"] = "; ".join(
            f"{cookie['name']}={cookie['value']}"
            for cookie in cookies
            if cookie.get("name") and cookie.get("value") is not None
        )
    try:
        data = await http_request(
            method,
            url,
            headers=merged,
            body=body,
            json_body=json_body,
            timeout_ms=timeout_ms,
            follow_redirects=follow_redirects,
            impersonate=impersonate,
        )
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")
    data["cookies_used"] = len(cookies)
    if follow_redirects:
        try:
            RUNTIME.check_url(data["url"])
        except PlagueError:
            data["policy_warning"] = (
                "redirect left PLAGUE_ALLOWED_DOMAINS"
            )
    return data


@mcp.tool()
async def screenshot(
    path: str | None = None,
    tier: str = "auto",
    full_page: bool = True,
) -> dict[str, Any]:
    """Capture the current page. Requires a rendering engine.

    Use tier="stealth", tier="chrome", or tier="handoff". The fast tier has no
    layout engine, so it cannot render.
    """
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        async with manager.session() as session:
            return await _capture(session, path, full_page)

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return _error("no warm session; fetch the page first")
    async with RUNTIME.using(key) as session:
        return await _capture(session, path, full_page)


async def _page_rows(session: Session) -> list[dict[str, Any]]:
    rows = []
    for index, page in enumerate(session.pages()):
        try:
            title = await page.title()
        except Exception:
            title = ""
        rows.append(
            {
                "index": index,
                "url": str(page.url),
                "title": title,
                "active": page is session.page,
            }
        )
    return rows


@mcp.tool()
async def tabs(tier: str = "auto") -> dict[str, Any]:
    """List open pages in the current warm or handoff browser."""
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return {"pages": [], "note": "no handoff browser is running"}
        async with manager.session() as session:
            return {"pages": await _page_rows(session), "engine": "handoff"}

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return {"pages": [], "note": "no warm session; fetch a page first"}
    async with RUNTIME.using(key) as session:
        return {
            "pages": await _page_rows(session),
            "engine": session.info.name,
        }


@mcp.tool()
async def tab_open(url: str | None = None, tier: str = "auto") -> dict[str, Any]:
    """Open a new page and make it active. Chrome and Cloak only."""
    if url:
        try:
            RUNTIME.check_url(url)
        except PlagueError as exc:
            return _error(str(exc))

    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        async with manager.session() as session:
            try:
                page = await session.new_page(url)
            except Exception as exc:
                return _error(f"{type(exc).__name__}: {exc}")
            manager.active_page = len(session.pages()) - 1
            manager.observer.attach(page)
            return {
                "ok": True,
                "index": manager.active_page,
                "url": str(page.url),
                "engine": "handoff",
            }

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return _error("no warm session; fetch a page first")
    async with RUNTIME.using(key) as session:
        try:
            page = await session.new_page(url)
        except Exception as exc:
            return _error(
                f"{session.info.name} cannot open a new tab: {exc}"
            )
        entry.observer.attach(page)
        return {
            "ok": True,
            "index": len(session.pages()) - 1,
            "url": str(page.url),
            "engine": session.info.name,
        }


@mcp.tool()
async def tab_switch(index: int, tier: str = "auto") -> dict[str, Any]:
    """Switch the active page by index."""
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        async with manager.session() as session:
            try:
                page = await session.use_page(index)
            except Exception as exc:
                return _error(str(exc))
            manager.active_page = index
            return {
                "ok": True,
                "index": index,
                "url": str(page.url),
                "engine": "handoff",
            }

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return _error("no warm session; fetch a page first")
    async with RUNTIME.using(key) as session:
        try:
            page = await session.use_page(index)
        except Exception as exc:
            return _error(str(exc))
        entry.observer.attach(page)
        return {
            "ok": True,
            "index": index,
            "url": str(page.url),
            "engine": session.info.name,
        }


@mcp.tool()
async def tab_close(
    index: int | None = None, tier: str = "auto"
) -> dict[str, Any]:
    """Close a page by index, defaulting to the active one."""
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        async with manager.session() as session:
            try:
                await session.close_page(index)
            except Exception as exc:
                return _error(str(exc))
            pages = session.pages()
            manager.active_page = min(
                manager.active_page, max(len(pages) - 1, 0)
            )
            return {"ok": True, "pages": await _page_rows(session)}

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return _error("no warm session; fetch a page first")
    async with RUNTIME.using(key) as session:
        try:
            await session.close_page(index)
        except Exception as exc:
            return _error(str(exc))
        entry.observer.attach(session.page)
        return {"ok": True, "pages": await _page_rows(session)}


@mcp.tool()
async def storage_save(name: str, tier: str = "auto") -> dict[str, Any]:
    """Save cookies and localStorage from the current session under a name.

    The file contains live session cookies. It is written owner-only under the
    Plague cache directory and should be treated as a secret.
    """
    if tier == "handoff":
        manager = RUNTIME.handoff_manager()
        if not manager.running:
            return _error("no handoff browser is running; call handoff first")
        async with manager.session() as session:
            if not session.supports(Capability.STORAGE_STATE):
                return _error("the handoff browser cannot export storage state")
            try:
                state = await session.storage_state()
            except Exception as exc:
                return _error(f"{type(exc).__name__}: {exc}")
        try:
            return save_state(name, state or {})
        except StorageError as exc:
            return _error(str(exc))

    key = RUNTIME.tier_key(tier)
    entry = RUNTIME._sessions.get(key)
    if entry is None:
        return _error("no warm session; fetch a page first")
    async with RUNTIME.using(key) as session:
        if not session.supports(Capability.STORAGE_STATE):
            return _error(
                f"engine {session.info.name!r} cannot export storage state"
            )
        try:
            state = await session.storage_state()
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")
    try:
        return save_state(name, state or {})
    except StorageError as exc:
        return _error(str(exc))


@mcp.tool()
async def storage_load(
    name: str,
    tier: str = "auto",
    url: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Reopen a tier with a saved storage state, optionally navigating."""
    if tier == "handoff":
        return _error(
            "storage_load does not apply to handoff; its profile persists on disk"
        )
    try:
        state = load_state(name)
    except StorageError as exc:
        return _error(str(exc))
    if url:
        try:
            RUNTIME.check_url(url)
        except PlagueError as exc:
            return _error(str(exc))

    key = RUNTIME.tier_key(tier)
    profile = RUNTIME.config().profile()
    profile.user_data_dir = None
    profile.storage_state = state
    await RUNTIME.set_profile(key, profile)

    if not url:
        try:
            async with RUNTIME.using(key) as session:
                return {
                    "ok": True,
                    "storage": name,
                    "tier": key,
                    "engine": session.info.name,
                    "url": str(getattr(session.page, "url", "")),
                }
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")

    try:
        async with RUNTIME.using(key) as session:
            result = await RUNTIME.plague().fetch_on(
                session, url, timeout_ms=timeout_ms
            )
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")
    if key in {"stealth", "chrome"} and result.ok:
        RUNTIME.pin(url, key)
    data = result_dict(result)
    data["storage"] = name
    return data


@mcp.tool()
async def storage_list() -> dict[str, Any]:
    """List saved storage states."""
    return {"states": list_states()}


@mcp.tool()
async def storage_delete(name: str) -> dict[str, Any]:
    """Delete a saved storage state."""
    try:
        deleted = delete_state(name)
    except StorageError as exc:
        return _error(str(exc))
    return {"deleted": deleted, "name": name}


@mcp.tool()
async def handoff(
    url: str | None = None,
    port: int = 0,
    profile_dir: str | None = None,
    proxy: str | None = None,
    seed: bool = True,
    timeout_s: float = 20.0,
    attach_to: str | None = None,
    ozone: str | None = None,
) -> dict[str, Any]:
    """Launch a headed Chrome, or attach to one, and return its CDP URL.

    Use this for logins, 2FA, payments, and risk-score walls. The launched
    browser is not the daily profile. When `seed` is true, cookies from the
    current warm session are copied in before the page opens, so an
    already-cleared session carries over. `release` closes a launched browser
    and detaches from an attached one.

    Set `attach_to` to a CDP URL or host:port to drive a Chrome you started
    yourself, a browser on another machine over an SSH tunnel, or a cloud
    browser. On Linux the launch picks Wayland when available; `ozone` can force
    "wayland" or "x11".
    """
    await RUNTIME.sweep()
    if url:
        try:
            RUNTIME.check_url(url)
        except PlagueError as exc:
            return _error(str(exc))

    cookies: list[dict[str, Any]] = []
    if seed:
        for key in ("stealth", "chrome", "fast"):
            entry = RUNTIME._sessions.get(key)
            if entry is None:
                continue
            try:
                cookies = await entry.session.cookies()
                break
            except Exception:
                continue

    manager = RUNTIME.handoff_manager()
    try:
        if attach_to:
            data = await manager.attach(attach_to, timeout_s=timeout_s)
        else:
            data = await manager.start(
                url=None if seed else url,
                port=port or None,
                profile_dir=profile_dir,
                proxy=proxy,
                timeout_s=timeout_s,
                ozone=ozone,
            )
    except HandoffError as exc:
        return _error(str(exc))

    if attach_to:
        if cookies or url:
            try:
                data.update(await manager.seed(cookies, url))
            except Exception as exc:
                data["seed_error"] = f"{type(exc).__name__}: {exc}"
    elif seed and (cookies or url):
        try:
            data.update(await manager.seed(cookies, url))
        except Exception as exc:
            data["seed_error"] = f"{type(exc).__name__}: {exc}"
    return data


@mcp.tool()
async def release(all_sessions: bool = False) -> dict[str, Any]:
    """Close a launched handoff browser, or detach from an attached one.

    Set all_sessions=true to also close the warm sessions and clear host pins.
    """
    stopped = False
    if RUNTIME.handoff is not None:
        try:
            stopped = await RUNTIME.handoff.stop()
        except Exception:
            stopped = False
    if all_sessions:
        await RUNTIME.close_sessions()
    return {
        "handoff_stopped": stopped,
        "sessions_closed": all_sessions,
        "warm_sessions": RUNTIME.describe(),
    }


@mcp.tool()
async def recipe_save(
    name: str, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Save an action list as a reusable recipe."""
    try:
        return save_recipe(name, actions)
    except RecipeError as exc:
        return _error(str(exc))
    except ActionError as exc:
        return _error(str(exc))


@mcp.tool()
async def recipe_run(
    name: str,
    url: str | None = None,
    tier: str = "auto",
    max_text_chars: int = 4_000,
    include_html: bool = False,
    snapshot: bool = False,
) -> dict[str, Any]:
    """Replay a saved recipe, optionally navigating to a URL first.

    With `url`, the recipe runs as the pre-extraction actions of a fetch.
    Without it, the recipe runs on the current warm or handoff page.
    """
    try:
        actions = load_recipe(name)
    except RecipeError as exc:
        return _error(str(exc))
    except ActionError as exc:
        return _error(str(exc))
    payload = recipe_dicts(actions)
    if url:
        if tier == "handoff":
            return _error(
                "recipe_run with a URL cannot use handoff; call handoff, "
                "then recipe_run without a URL"
            )
        return await fetch(
            url=url,
            tier=tier,
            actions=payload,
            max_text_chars=max_text_chars,
            include_html=include_html,
        )
    return await act(
        actions=payload,
        tier=tier,
        max_text_chars=max_text_chars,
        include_html=include_html,
        snapshot=snapshot,
    )


@mcp.tool()
async def recipe_list() -> dict[str, Any]:
    """List saved recipes."""
    return {"recipes": list_recipes()}


@mcp.tool()
async def recipe_delete(name: str) -> dict[str, Any]:
    """Delete a saved recipe."""
    try:
        deleted = delete_recipe(name)
    except RecipeError as exc:
        return _error(str(exc))
    return {"deleted": deleted, "name": name}


@mcp.tool()
async def detect(
    url: str,
    tier: str = "auto",
    timeout_ms: int = 30_000,
    headed: bool = False,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Classify a page's challenge wall without solving or escalating."""
    config = _config(timeout_ms=timeout_ms, headed=headed, proxy=proxy)
    plague = Plague(config)
    try:
        try:
            probe = await plague.probe(
                url, tier=tier, timeout_ms=timeout_ms
            )
        except PlagueError as exc:
            return error_dict(exc)
        return probe_dict(probe)
    finally:
        await plague.close()


@mcp.tool()
async def fingerprint(
    engine: str = "all",
    url: str = "https://example.com",
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Compare navigator, screen, client hints, and canvas surfaces.

    Args:
        engine: all, lightpanda, cloak, or chrome.
        url: Page to navigate before probing.
        timeout_ms: Navigation timeout in milliseconds.
    """
    config = _config(timeout_ms=timeout_ms)
    plague = Plague(config)
    try:
        plague.check_url(url)
    except PlagueError as exc:
        return _error(str(exc))
    names = (
        list(plague.engines) if engine == "all" else [engine]
    )
    results: dict[str, Any] = {}
    try:
        for name in names:
            if name not in plague.engines:
                results[name] = {"error": f"unknown engine {name!r}"}
                continue
            session = None
            try:
                session = await plague.engines[name].open(config.profile())
                await session.goto(
                    url, wait_until="domcontentloaded", timeout_ms=timeout_ms
                )
                results[name] = await collect_fingerprint(session)
            except Exception as exc:
                results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                if session is not None:
                    await session.close()
    finally:
        await plague.close()
    return results


@mcp.tool()
async def bench(
    urls: list[str],
    tier: str = "auto",
    timeout_ms: int = 30_000,
    warm: bool = True,
    workers: int = 4,
    escalate: bool = False,
) -> dict[str, Any]:
    """Fetch a list of URLs and report engine, status, challenge, and latency.

    Warm mode reuses one session per worker and is the fast path. Set
    escalate=True to fall back to the next tier when a warm page is blocked.
    """
    rows = await _bench_rows(
        urls,
        tier=tier,
        timeout_ms=timeout_ms,
        warm=warm,
        workers=workers,
        escalate=escalate,
    )
    return {
        "rows": rows,
        "warm": warm,
        "workers": workers,
        "escalate": escalate,
    }


async def _bench_rows(
    urls: list[str],
    *,
    tier: str,
    timeout_ms: int,
    warm: bool,
    workers: int,
    escalate: bool,
) -> list[dict[str, Any]]:
    config = _config(timeout_ms=timeout_ms)
    plague = Plague(config)
    try:
        results = await plague.fetch_many(
            urls,
            tier=tier,
            warm=warm,
            workers=workers,
            escalate=escalate,
            timeout_ms=timeout_ms,
        )
    finally:
        await plague.close()

    return [
        {
            "url": result.url,
            "ok": result.ok,
            "engine": result.engine,
            "status": result.status,
            "ms": result.elapsed_ms,
            "challenge": result.challenge.label
            if result.challenge
            else (
                result.attempts[-1].challenge if result.attempts else None
            ),
            "solved": result.solved,
            "attempts": len(result.attempts),
        }
        for result in results
    ]


DEMOS = [
    "https://nopecha.com/demo/cloudflare",
    "https://nopecha.com/demo/turnstile",
    "https://nopecha.com/demo/recaptcha",
    "https://2captcha.com/demo/recaptcha-v2",
]


@mcp.tool()
async def captcha_demos(
    tier: str = "auto",
    urls: list[str] | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Run the public CAPTCHA demo walls and classify each result.

    Solver keys from the environment are used automatically. Without keys,
    token walls are detected but not solved.
    """
    targets = urls or DEMOS
    rows = await _bench_rows(
        targets,
        tier=tier,
        timeout_ms=timeout_ms,
        warm=False,
        workers=1,
        escalate=True,
    )
    return {
        "rows": rows,
        "warm": False,
        "workers": 1,
        "escalate": True,
        "solver_keys": {
            "capsolver": bool(os.environ.get("CAPSOLVER_API_KEY")),
            "twocaptcha": bool(os.environ.get("TWOCAPTCHA_API_KEY")),
        },
    }


@mcp.resource("plague://docs/reverse-engineering")
def reverse_engineering_doc() -> str:
    """The CloakBrowser vs Lightpanda reverse engineering report."""
    return (ROOT / "docs" / "REVERSE_ENGINEERING.md").read_text(encoding="utf-8")


@mcp.resource("plague://docs/readme")
def readme_doc() -> str:
    """The project README."""
    return (ROOT / "README.md").read_text(encoding="utf-8")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
