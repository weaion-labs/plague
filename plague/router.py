"""The router: cheap tier first, stealth tier when it matters."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

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
from .challenge.capture import install as install_capture
from .challenge.live import extract_hints
from .config import Config
from .engines import BaseEngine, EngineUnavailable, Session, default_engines
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

                # Record sitekey/action/cdata from vendor render calls before
                # page scripts run. This is what makes late-rendered widgets
                # solvable without guessing from the DOM.
                if self.solver is not None or self.config.solve_present:
                    await install_capture(session)

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
                wants_solve = challenge and (
                    challenge.blocking or self.config.solve_present
                )
                if (
                    wants_solve
                    and challenge.kind is ChallengeKind.TOKEN
                    and self.solver is not None
                    and allow_solve
                ):
                    hints = await extract_hints(session.page, challenge.vendor)
                    sitekey = (
                        challenge.sitekey
                        or find_sitekey(html, challenge.vendor)
                        or hints.get("sitekey")
                    )
                    if sitekey:
                        task = SolveTask(
                            vendor=challenge.vendor,
                            page_url=nav.url,
                            sitekey=sitekey,
                            page=session.page,
                            html=html,
                            action=hints.get("action"),
                            cdata=hints.get("cdata"),
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
                            if challenge.blocking:
                                await session.wait_for_timeout(1500)
                                # Reload after injecting so clearance cookies and
                                # the real response replace the challenge document.
                                nav = await session.goto(
                                    url, wait_until=wait_until, timeout_ms=timeout
                                )
                                html = await session.content()
                            else:
                                # A widget on an accessible form: keep the page
                                # and its form state, do not reload.
                                await session.wait_for_timeout(1000)
                                html = await session.content()
                                nav = self._nav(session, nav)
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

    async def fetch_many(
        self,
        urls: Iterable[str],
        *,
        tier: Tier | str = Tier.AUTO,
        workers: int = 1,
        warm: bool = True,
        escalate: bool = False,
        timeout_ms: int | None = None,
        screenshot_dir: str | None = None,
    ) -> list[Result]:
        """Fetch many URLs with optional warm sessions and worker concurrency.

        Warm mode reuses one engine session per worker. It skips escalation
        unless escalate=True, in which case a blocking page falls back to the
        next tier through the normal router.
        """
        targets = list(urls)
        if not targets:
            return []
        timeout = timeout_ms or self.config.timeout_ms
        if screenshot_dir:
            Path(screenshot_dir).mkdir(parents=True, exist_ok=True)

        if not warm:
            semaphore = asyncio.Semaphore(max(1, workers))

            async def cold_one(target: str) -> Result:
                async with semaphore:
                    try:
                        return await self.fetch(
                            target,
                            tier=tier,
                            timeout_ms=timeout,
                            screenshot=self._screenshot_path(
                                screenshot_dir, target
                            )
                            if screenshot_dir
                            else None,
                        )
                    except PlagueError as exc:
                        result = self._error_result(target, exc)
                        result.attempts = exc.attempts or result.attempts
                        return result
                    except Exception as exc:
                        return self._error_result(target, exc)

            return list(
                await asyncio.gather(*(cold_one(target) for target in targets))
            )

        worker_count = max(1, min(workers, len(targets)))
        results: list[Result | None] = [None] * len(targets)
        queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        for index, target in enumerate(targets):
            queue.put_nowait((index, target))

        async def worker() -> None:
            try:
                async with self.session(tier=tier) as session:
                    while True:
                        try:
                            index, target = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        results[index] = await self._warm_fetch(
                            session,
                            target,
                            escalate,
                            timeout,
                            screenshot_dir,
                        )
            except Exception as exc:
                log.warning("warm worker stopped: %s", exc)

        await asyncio.gather(*(worker() for _ in range(worker_count)))
        return [
            result
            if result is not None
            else self._error_result(
                target, RuntimeError("warm worker stopped before this URL")
            )
            for target, result in zip(targets, results)
        ]

    async def _warm_fetch(
        self,
        session: Session,
        url: str,
        escalate: bool,
        timeout_ms: int,
        screenshot_dir: str | None,
    ) -> Result:
        started = time.monotonic()
        engine_name = session.info.name

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            nav = await session.goto(
                url, wait_until="domcontentloaded", timeout_ms=timeout_ms
            )
            html = await session.content()
            challenge = detect(
                status=nav.status,
                url=nav.url,
                headers=nav.headers,
                html=html,
            )

            if challenge and challenge.blocking:
                attempt = Attempt(
                    engine=engine_name,
                    ok=False,
                    elapsed_ms=elapsed(),
                    status=nav.status,
                    challenge=challenge.label,
                    error="challenge in warm mode",
                )
                if escalate:
                    next_tier = {
                        "lightpanda": Tier.STEALTH,
                        "cloak": Tier.CHROME,
                        "chrome": Tier.CHROME,
                    }.get(engine_name, Tier.CHROME)
                    try:
                        cold = await self.fetch(
                            url,
                            tier=next_tier,
                            timeout_ms=timeout_ms,
                            screenshot=self._screenshot_path(
                                screenshot_dir, url
                            )
                            if screenshot_dir
                            else None,
                        )
                    except PlagueError as exc:
                        result = self._error_result(url, exc, engine=engine_name)
                        result.attempts = [attempt, *exc.attempts]
                        if exc.attempts:
                            result.engine = exc.attempts[-1].engine
                            result.status = exc.attempts[-1].status
                        result.elapsed_ms = elapsed()
                        return result
                    cold.attempts.insert(0, attempt)
                    return cold

                return Result(
                    url=url,
                    final_url=nav.url,
                    status=nav.status,
                    title=await session.title(),
                    html=html,
                    text=await session.text(),
                    engine=engine_name,
                    attempts=[attempt],
                    challenge=challenge,
                    solved=False,
                    elapsed_ms=elapsed(),
                )

            title = await session.title()
            text = await session.text()
            shot = None
            if screenshot_dir and session.supports(Capability.VISUAL):
                shot = await session.screenshot(
                    self._screenshot_path(screenshot_dir, url)
                )
            try:
                cookies = await session.cookies()
            except Exception:
                cookies = None

            attempt = Attempt(
                engine=engine_name,
                ok=True,
                elapsed_ms=elapsed(),
                status=nav.status,
                challenge=challenge.label if challenge else None,
            )
            return Result(
                url=url,
                final_url=nav.url,
                status=nav.status,
                title=title,
                html=html,
                text=text,
                engine=engine_name,
                attempts=[attempt],
                challenge=challenge,
                solved=False,
                elapsed_ms=elapsed(),
                screenshot=shot,
                cookies=cookies,
            )
        except Exception as exc:
            return self._error_result(
                url, exc, engine=engine_name, elapsed_ms=elapsed()
            )

    @staticmethod
    def _screenshot_path(directory: str | None, url: str) -> str | None:
        if not directory:
            return None
        parsed = urlparse(url)
        label = f"{parsed.netloc}{parsed.path}".strip("/") or "page"
        label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:80]
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        return str(Path(directory) / f"{label}-{digest}.png")

    @staticmethod
    def _error_result(
        url: str,
        exc: Exception,
        *,
        engine: str | None = None,
        elapsed_ms: int = 0,
    ) -> Result:
        return Result(
            url=url,
            final_url=url,
            status=None,
            title="",
            html="",
            text="",
            engine=engine,
            attempts=[
                Attempt(
                    engine=engine or "router",
                    ok=False,
                    elapsed_ms=elapsed_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
            ],
            challenge=None,
            solved=False,
            elapsed_ms=elapsed_ms,
        )

    @asynccontextmanager
    async def session(
        self,
        tier: Tier | str = Tier.FAST,
        profile: Profile | None = None,
    ) -> AsyncIterator[Session]:
        """Open one engine session for repeated navigations.

        Warm mode skips escalation and challenge solving. Use fetch() when a
        page may need a stronger tier. If the first engine is unavailable, the
        next engine in the tier chain is tried.
        """
        chain, _ = self._chain(Tier(tier), need_visual=False)
        if not chain:
            raise PlagueError(f"no engine available for tier={tier!r}")
        session_profile = profile or self.config.profile()
        last_error: Exception | None = None
        for name in chain:
            engine = self.engines[name]
            try:
                session = await engine.open(session_profile)
            except EngineUnavailable as exc:
                last_error = exc
                continue
            try:
                yield session
            finally:
                await session.close()
            return
        raise PlagueError(
            f"no engine available for tier={tier!r}: {last_error}"
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
