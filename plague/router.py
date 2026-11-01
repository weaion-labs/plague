"""The router: cheap tier first, stealth tier when it matters."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

from .challenge import (
    SolveTask,
    Solver,
    SolverError,
    build_solver,
    detect,
    find_sitekey,
    inject_token,
)
from .challenge.actions import click_turnstile
from .config import Config
from .engines import BaseEngine, EngineUnavailable, default_engines
from .models import (
    Action,
    Attempt,
    Capability,
    Challenge,
    ChallengeKind,
    Profile,
    Result,
    Tier,
)
from .text import html_to_title

log = logging.getLogger("plague.router")

CHAINS: dict[Tier, tuple[str, ...]] = {
    Tier.AUTO: ("lightpanda", "cloak", "chrome"),
    Tier.FAST: ("lightpanda",),
    Tier.STEALTH: ("cloak",),
    Tier.CHROME: ("chrome",),
}

# Common markers for a client-rendered shell. A white page from one of these is
# not a successful extraction, even if the HTTP status was 200.
APP_SHELL = re.compile(
    r"""id=["'](?:root|app|__next|__nuxt|svelte)["']""", re.IGNORECASE
)

_UNSET = object()


class PlagueError(RuntimeError):
    def __init__(self, message: str, attempts: list[Attempt] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class Probe:
    url: str
    final_url: str
    status: int | None
    engine: str
    title: str
    challenge: Challenge | None
    elapsed_ms: int
    error: str | None = None


class Plague:
    def __init__(
        self,
        config: Config | None = None,
        *,
        engines: dict[str, BaseEngine] | None = None,
        solver: Solver | None | object = _UNSET,
    ) -> None:
        self.config = config or Config.from_env()
        self.engines = engines if engines is not None else default_engines(self.config)
        self.solver_error: str | None = None
        if solver is _UNSET:
            try:
                self.solver = build_solver(self.config)
            except SolverError as exc:
                self.solver = None
                self.solver_error = str(exc)
                log.warning("solver disabled: %s", exc)
        else:
            self.solver = solver  # type: ignore[assignment]

    # ------------------------------------------------------------------ public

    async def fetch(
        self,
        url: str,
        *,
        tier: Tier | str = Tier.AUTO,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
        screenshot: str | None = None,
        actions: Iterable[Action] | None = None,
        profile: Profile | None = None,
        headed: bool | None = None,
        humanize: bool | None = None,
        proxy: str | None = None,
        geoip: bool | None = None,
    ) -> Result:
        tier = Tier(tier)
        if profile is None:
            overrides: dict[str, Any] = {}
            if headed is not None:
                overrides["headless"] = not headed
            if humanize is not None:
                overrides["humanize"] = humanize
            if proxy is not None:
                overrides["proxy"] = proxy
            if geoip is not None:
                overrides["geoip"] = geoip
            profile = self.config.profile(**overrides)

        chain, skipped = self._chain(tier, need_visual=bool(screenshot))
        attempts: list[Attempt] = list(skipped)
        if not chain:
            raise PlagueError(
                f"no engine can satisfy tier={tier.value!r}"
                + (" with screenshots" if screenshot else ""),
                attempts,
            )

        timeout = timeout_ms or self.config.timeout_ms
        overall_start = time.monotonic()

        for name in chain:
            engine = self.engines[name]
            attempt_start = time.monotonic()
            session = None
            try:
                try:
                    session = await engine.open(profile)
                except EngineUnavailable as exc:
                    attempts.append(
                        self._attempt(name, attempt_start, skipped=str(exc))
                    )
                    continue
                except Exception as exc:
                    attempts.append(
                        self._attempt(
                            name, attempt_start, error=f"launch: {exc}"
                        )
                    )
                    continue

                nav = await session.goto(
                    url, wait_until=wait_until, timeout_ms=timeout
                )
                html = await session.content()
                challenge = detect(
                    status=nav.status,
                    url=nav.url,
                    headers=nav.headers,
                    html=html,
                )
                solved = False
                solver_name: str | None = None
                cost = 0.0
                solver_failure: str | None = None

                # Cloudflare-style JS interstitials often clear themselves once a
                # real browser runs the challenge script. Give them a moment.
                if (
                    challenge
                    and challenge.blocking
                    and challenge.kind is ChallengeKind.JS
                    and session.supports(Capability.VISUAL)
                ):
                    for _ in range(self.config.js_challenge_rounds):
                        await session.wait_for_timeout(
                            self.config.js_challenge_wait_ms
                        )
                        if challenge.vendor in {
                            "cloudflare",
                            "cloudflare_turnstile",
                        }:
                            await click_turnstile(session.page)
                            await session.wait_for_timeout(1000)
                        # Reload so a clearance cookie is applied and the status
                        # is no longer the challenge response's 403 or 503.
                        nav = await session.goto(
                            url, wait_until=wait_until, timeout_ms=timeout
                        )
                        html = await session.content()
                        challenge = detect(
                            status=nav.status,
                            url=nav.url,
                            headers=nav.headers,
                            html=html,
                        )
                        if not challenge or not challenge.blocking:
                            break

                allow_solve = name != "lightpanda" or self.config.solve_on_fast
                if (
                    challenge
                    and challenge.blocking
                    and challenge.kind is ChallengeKind.TOKEN
                    and self.solver is not None
                    and allow_solve
                ):
                    sitekey = challenge.sitekey or find_sitekey(
                        html, challenge.vendor
                    )
                    if sitekey:
                        task = SolveTask(
                            vendor=challenge.vendor,
                            page_url=nav.url,
                            sitekey=sitekey,
                            page=session.page,
                            html=html,
                        )
                        try:
                            solution = await self.solver.solve(task)
                        except SolverError as exc:
                            solver_failure = str(exc)
                            log.warning("solver failed on %s: %s", name, exc)
                        else:
                            solver_name = solution.provider
                            cost = solution.cost_usd
                            await inject_token(
                                session.page, challenge.vendor, solution.token
                            )
                            await session.wait_for_timeout(1500)
                            # Reload after injecting so clearance cookies and the
                            # real response replace the challenge document.
                            nav = await session.goto(
                                url, wait_until=wait_until, timeout_ms=timeout
                            )
                            html = await session.content()
                            updated = detect(
                                status=nav.status,
                                url=nav.url,
                                headers=nav.headers,
                                html=html,
                            )
                            if updated is None or not updated.blocking:
                                solved = True
                            challenge = updated
                    else:
                        solver_failure = "no sitekey found"

                if challenge and challenge.blocking:
                    attempts.append(
                        self._attempt(
                            name,
                            attempt_start,
                            ok=False,
                            status=nav.status,
                            challenge=challenge.label,
                            solved=solved,
                            solver=solver_name,
                            cost=cost,
                            error=solver_failure,
                        )
                    )
                    continue

                # A JS app shell can return 200 with an empty body. Lightpanda
                # is cheap, so give hydration a moment, then escalate if the
                # page still has no visible text.
                if (
                    name == "lightpanda"
                    and APP_SHELL.search(html)
                    and len((await session.text()).strip())
                    < self.config.min_text_chars
                ):
                    await session.wait_for_timeout(1500)
                    html = await session.content()
                    nav = self._nav(session, nav)
                    challenge = detect(
                        status=nav.status,
                        url=nav.url,
                        headers=nav.headers,
                        html=html,
                    )
                    if challenge and challenge.blocking:
                        attempts.append(
                            self._attempt(
                                name,
                                attempt_start,
                                ok=False,
                                status=nav.status,
                                challenge=challenge.label,
                                error="challenge appeared after hydration",
                            )
                        )
                        continue
                    if len((await session.text()).strip()) < self.config.min_text_chars:
                        attempts.append(
                            self._attempt(
                                name,
                                attempt_start,
                                ok=False,
                                status=nav.status,
                                error="client-rendered shell with no visible text; escalated",
                            )
                        )
                        continue

                if actions:
                    await self._run_actions(session, actions)
                    html = await session.content()
                    nav = self._nav(session, nav)
                    challenge = detect(
                        status=nav.status,
                        url=nav.url,
                        headers=nav.headers,
                        html=html,
                    )
                    if challenge and challenge.blocking:
                        attempts.append(
                            self._attempt(
                                name,
                                attempt_start,
                                ok=False,
                                status=nav.status,
                                challenge=challenge.label,
                                solved=solved,
                                solver=solver_name,
                                cost=cost,
                            )
                        )
                        continue

                title = await session.title() or html_to_title(html)
                text = await session.text()
                shot = None
                if screenshot:
                    shot = await session.screenshot(screenshot)
                try:
                    cookies = await session.cookies()
                except Exception:
                    cookies = None

                attempts.append(
                    self._attempt(
                        name,
                        attempt_start,
                        status=nav.status,
                        challenge=challenge.label if challenge else None,
                        solved=solved,
                        solver=solver_name,
                        cost=cost,
                    )
                )
                return Result(
                    url=url,
                    final_url=nav.url,
                    status=nav.status,
                    title=title,
                    html=html,
                    text=text,
                    engine=name,
                    attempts=attempts,
                    challenge=challenge,
                    solved=solved,
                    elapsed_ms=int((time.monotonic() - overall_start) * 1000),
                    screenshot=shot,
                    cookies=cookies,
                )
            except Exception as exc:
                attempts.append(
                    self._attempt(
                        name,
                        attempt_start,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            finally:
                if session is not None:
                    await session.close()

        raise PlagueError(
            f"all engines failed for {url}", attempts
        )

    async def probe(
        self,
        url: str,
        *,
        tier: Tier | str = Tier.AUTO,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
        profile: Profile | None = None,
    ) -> Probe:
        """One navigation on the first usable engine, no escalation, no solving."""
        chain, _ = self._chain(Tier(tier), need_visual=False)
        profile = profile or self.config.profile()
        timeout = timeout_ms or self.config.timeout_ms
        errors: list[str] = []
        started = time.monotonic()

        for name in chain:
            engine = self.engines[name]
            session = None
            try:
                session = await engine.open(profile)
                nav = await session.goto(
                    url, wait_until=wait_until, timeout_ms=timeout
                )
                html = await session.content()
                challenge = detect(
                    status=nav.status,
                    url=nav.url,
                    headers=nav.headers,
                    html=html,
                )
                return Probe(
                    url=url,
                    final_url=nav.url,
                    status=nav.status,
                    engine=name,
                    title=await session.title() or html_to_title(html),
                    challenge=challenge,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as exc:
                errors.append(f"{name}: {exc}")
            finally:
                if session is not None:
                    await session.close()

        raise PlagueError(
            f"probe failed for {url}: " + "; ".join(errors) if errors else "no engine",
        )

    def describe_engines(self) -> list[dict[str, Any]]:
        return [engine.describe() for engine in self.engines.values()]

    async def close(self) -> None:
        if self.solver is not None:
            await self.solver.close()

    async def __aenter__(self) -> "Plague":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    # ----------------------------------------------------------------- private

    def _chain(
        self, tier: Tier, *, need_visual: bool
    ) -> tuple[list[str], list[Attempt]]:
        chain: list[str] = []
        skipped: list[Attempt] = []
        for name in CHAINS[tier]:
            engine = self.engines.get(name)
            if engine is None:
                continue
            if need_visual and not engine.info.supports(Capability.VISUAL):
                skipped.append(
                    Attempt(
                        engine=name,
                        ok=False,
                        elapsed_ms=0,
                        skipped="no visual rendering (screenshot requested)",
                    )
                )
                continue
            chain.append(name)
        return chain, skipped

    @staticmethod
    def _attempt(
        engine: str,
        started: float,
        *,
        ok: bool = True,
        status: int | None = None,
        challenge: str | None = None,
        solved: bool = False,
        solver: str | None = None,
        cost: float = 0.0,
        error: str | None = None,
        skipped: str | None = None,
    ) -> Attempt:
        return Attempt(
            engine=engine,
            ok=ok and error is None and skipped is None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            status=status,
            challenge=challenge,
            solved=solved,
            solver=solver,
            cost_usd=cost,
            error=error,
            skipped=skipped,
        )

    @staticmethod
    def _nav(session, previous):
        return type(previous)(
            url=session.page.url,
            status=previous.status,
            headers=previous.headers,
        )

    @staticmethod
    async def _run_actions(session, actions: Iterable[Action]) -> None:
        for action in actions:
            kind = action.type.lower()
            if kind == "click":
                if not action.selector:
                    raise ValueError("click action needs a selector")
                await session.click(action.selector, action.timeout_ms)
            elif kind == "fill":
                if not action.selector:
                    raise ValueError("fill action needs a selector")
                await session.fill(
                    action.selector, action.value or "", action.timeout_ms
                )
            elif kind == "press":
                if not action.selector:
                    raise ValueError("press action needs a selector")
                await session.press(
                    action.selector, action.value or "Enter", action.timeout_ms
                )
            elif kind == "wait_for":
                if not action.selector:
                    raise ValueError("wait_for action needs a selector")
                await session.wait_for_selector(action.selector, action.timeout_ms)
            elif kind == "wait":
                await session.wait_for_timeout(int(action.value or 1000))
            elif kind == "evaluate":
                if not action.value:
                    raise ValueError("evaluate action needs a value")
                await session.evaluate(action.value)
            else:
                raise ValueError(f"unknown action type: {action.type!r}")
