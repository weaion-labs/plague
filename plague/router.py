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
from .engines import BaseEngine, EngineUnavailable, Nav, Session, default_engines
from .interact import run_actions as run_action_list
from .models import (
    Action,
    Attempt,
    Capability,
    Challenge,
    ChallengeKind,
    Profile,
    Result,
    SolveReport,
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
        self._guard(url)
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
                (
                    nav,
                    html,
                    challenge,
                    solved,
                    solver_name,
                    cost,
                    solver_failure,
                ) = await self._resolve_wall(
                    session,
                    name,
                    url,
                    nav,
                    html,
                    challenge=challenge,
                    wait_until=wait_until,
                    timeout_ms=timeout,
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

    async def open_session(
        self,
        tier: Tier | str = Tier.AUTO,
        profile: Profile | None = None,
    ) -> Session:
        """Open one long-lived session without a context manager.

        The caller owns the session and must close it. This is what lets a
        long-running MCP server keep one warm browser across tool calls. The
        first usable engine in the tier chain wins; fallbacks are silent.
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
            await install_capture(session)
            return session
        raise PlagueError(
            f"no engine available for tier={tier!r}: {last_error}"
        )

    async def fetch_on(
        self,
        session: Session,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
        actions: Iterable[Action] | None = None,
        screenshot: str | None = None,
        allow_solve: bool | None = None,
    ) -> Result:
        """Fetch and extract on an already-open session, leaving it open.

        Challenge handling matches ``fetch``: JS interstitials are waited out
        and token walls are solved when the engine and policy allow it. A
        blocking wall that survives is returned in the result rather than
        raised, so the caller can decide to escalate or hand off.
        """
        self._guard(url)
        timeout = timeout_ms or self.config.timeout_ms
        started = time.monotonic()
        name = session.info.name

        nav = await session.goto(url, wait_until=wait_until, timeout_ms=timeout)
        html = await session.content()
        challenge = detect(
            status=nav.status,
            url=nav.url,
            headers=nav.headers,
            html=html,
        )
        (
            nav,
            html,
            challenge,
            solved,
            solver_name,
            cost,
            solver_failure,
        ) = await self._resolve_wall(
            session,
            name,
            url,
            nav,
            html,
            challenge=challenge,
            wait_until=wait_until,
            timeout_ms=timeout,
            allow_solve=allow_solve,
        )

        if challenge and challenge.blocking:
            return await self._stopped_result(
                session,
                url,
                nav,
                html,
                name,
                challenge,
                started,
                solved=solved,
                solver_name=solver_name,
                cost=cost,
                error=solver_failure,
            )

        # A client-rendered shell can return 200 with no visible text. Wait for
        # hydration, then report it so the caller can escalate.
        if (
            name == "lightpanda"
            and APP_SHELL.search(html)
            and len((await session.text()).strip()) < self.config.min_text_chars
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
                return await self._stopped_result(
                    session,
                    url,
                    nav,
                    html,
                    name,
                    challenge,
                    started,
                    error="challenge appeared after hydration",
                )
            if len((await session.text()).strip()) < self.config.min_text_chars:
                return await self._stopped_result(
                    session,
                    url,
                    nav,
                    html,
                    name,
                    None,
                    started,
                    error="client-rendered shell with no visible text; escalated",
                )

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
                return await self._stopped_result(
                    session,
                    url,
                    nav,
                    html,
                    name,
                    challenge,
                    started,
                    solved=solved,
                    solver_name=solver_name,
                    cost=cost,
                )

        title = await session.title() or html_to_title(html)
        text = await session.text()
        shot = None
        if screenshot:
            shot = await session.screenshot(screenshot)
        try:
            cookies = await session.cookies()
        except Exception:
            cookies = None

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Result(
            url=url,
            final_url=nav.url,
            status=nav.status,
            title=title,
            html=html,
            text=text,
            engine=name,
            attempts=[
                Attempt(
                    engine=name,
                    ok=True,
                    elapsed_ms=elapsed_ms,
                    status=nav.status,
                    challenge=challenge.label if challenge else None,
                    solved=solved,
                    solver=solver_name,
                    cost_usd=cost,
                )
            ],
            challenge=challenge,
            solved=solved,
            elapsed_ms=elapsed_ms,
            screenshot=shot,
            cookies=cookies,
        )

    async def _stopped_result(
        self,
        session: Session,
        url: str,
        nav: Any,
        html: str,
        engine_name: str,
        challenge: Challenge | None,
        started: float,
        *,
        solved: bool = False,
        solver_name: str | None = None,
        cost: float = 0.0,
        error: str | None = None,
    ) -> Result:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Result(
            url=url,
            final_url=nav.url,
            status=nav.status,
            title=await session.title() or html_to_title(html),
            html=html,
            text=await session.text(),
            engine=engine_name,
            attempts=[
                Attempt(
                    engine=engine_name,
                    ok=False,
                    elapsed_ms=elapsed_ms,
                    status=nav.status,
                    challenge=challenge.label if challenge else None,
                    solved=solved,
                    solver=solver_name,
                    cost_usd=cost,
                    error=error,
                )
            ],
            challenge=challenge,
            solved=solved,
            elapsed_ms=elapsed_ms,
        )

    async def solve_page(
        self,
        session: Session,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
    ) -> SolveReport:
        """Detect and solve a challenge on the session's current page.

        This is the explicit, on-demand path behind the MCP ``captcha`` tool. It
        does not navigate first, so it is useful when a page is already open and
        the caller wants to know whether the wall is solvable, or wants to spend
        a token now.
        """
        url = str(getattr(session.page, "url", ""))
        self._guard(url)
        timeout = timeout_ms or self.config.timeout_ms
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        html = await session.content()
        last = getattr(session, "last_nav", None)
        if last is not None and getattr(last, "url", "") == url:
            status = last.status
            headers = last.headers
        else:
            status = None
            headers = {}
        challenge = detect(
            status=status, url=url, headers=headers, html=html
        )
        report = SolveReport(url=url, status=None, challenge=challenge)
        if challenge is None:
            report.error = "no challenge detected"
            report.elapsed_ms = elapsed()
            return report
        if self.config.solve_mode == "never":
            report.error = "solver disabled by PLAGUE_SOLVE_MODE"
            report.elapsed_ms = elapsed()
            return report
        if self.solver is None:
            report.error = self.solver_error or "no solver configured"
            report.elapsed_ms = elapsed()
            return report

        nav = Nav(url=url, status=None, headers={})
        (
            nav,
            html,
            challenge,
            solved,
            solver_name,
            cost,
            error,
        ) = await self._resolve_wall(
            session,
            session.info.name,
            url,
            nav,
            html,
            challenge=challenge,
            wait_until=wait_until,
            timeout_ms=timeout,
            allow_solve=True,
        )

        report.status = nav.status
        report.challenge = challenge
        report.solved = solved
        report.solver = solver_name
        report.cost_usd = cost
        report.error = error
        report.elapsed_ms = elapsed()
        if (
            not solved
            and error is None
            and challenge is not None
            and challenge.blocking
        ):
            report.error = (
                "challenge is still blocking after the solve attempt"
            )
        return report

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
            result = await self.fetch_on(
                session,
                url,
                timeout_ms=timeout_ms,
                screenshot=(
                    self._screenshot_path(screenshot_dir, url)
                    if screenshot_dir and session.supports(Capability.VISUAL)
                    else None
                ),
            )
        except Exception as exc:
            return self._error_result(
                url, exc, engine=engine_name, elapsed_ms=elapsed()
            )

        blocked = bool(result.challenge and result.challenge.blocking)
        shell = any(
            attempt.error and "shell" in attempt.error
            for attempt in result.attempts
        )
        if escalate and (blocked or shell):
            attempt = (
                result.attempts[0]
                if result.attempts
                else Attempt(engine=engine_name, ok=False, elapsed_ms=elapsed())
            )
            if shell and not attempt.error:
                attempt.error = (
                    "client-rendered shell with no visible text; escalated"
                )
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
                    screenshot=self._screenshot_path(screenshot_dir, url)
                    if screenshot_dir
                    else None,
                )
            except PlagueError as exc:
                error_result = self._error_result(
                    url, exc, engine=engine_name
                )
                error_result.attempts = [attempt, *exc.attempts]
                if exc.attempts:
                    error_result.engine = exc.attempts[-1].engine
                    error_result.status = exc.attempts[-1].status
                error_result.elapsed_ms = elapsed()
                return error_result
            cold.attempts.insert(0, attempt)
            return cold

        result.elapsed_ms = elapsed()
        return result

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
        self._guard(url)
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

    def check_url(self, url: str) -> None:
        """Raise when a URL falls outside PLAGUE_ALLOWED_DOMAINS."""
        self._guard(url)

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
        nav = type(previous)(
            url=session.page.url,
            status=previous.status,
            headers=previous.headers,
        )
        try:
            session.last_nav = nav
        except Exception:
            pass
        return nav

    async def _run_actions(
        self, session: Session, actions: Iterable[Action]
    ) -> None:
        for action in actions:
            if action.type.lower() == "goto" and action.value:
                self._guard(action.value)
        await run_action_list(session, actions)

    async def _resolve_wall(
        self,
        session: Session,
        engine_name: str,
        url: str,
        nav: Any,
        html: str,
        *,
        challenge: Challenge | None,
        wait_until: str,
        timeout_ms: int,
        allow_solve: bool | None = None,
    ) -> tuple[Any, str, Challenge | None, bool, str | None, float, str | None]:
        """Clear JS interstitials and token walls in place on a live session.

        Returns ``(nav, html, challenge, solved, solver_name, cost, error)``.
        A blocking challenge that survives is returned unchanged so the caller
        can either escalate or report it.
        """
        solved = False
        solver_name: str | None = None
        cost = 0.0
        solver_failure: str | None = None

        # Cloudflare-style JS interstitials often clear themselves once a real
        # browser runs the challenge script. Give them a moment.
        if (
            challenge
            and challenge.blocking
            and challenge.kind is ChallengeKind.JS
            and session.supports(Capability.VISUAL)
        ):
            for _ in range(self.config.js_challenge_rounds):
                await session.wait_for_timeout(self.config.js_challenge_wait_ms)
                if challenge.vendor in {"cloudflare", "cloudflare_turnstile"}:
                    await click_turnstile(session.page)
                    await session.wait_for_timeout(1000)
                # Reload so a clearance cookie is applied and the status is no
                # longer the challenge response's 403 or 503.
                nav = await session.goto(
                    url, wait_until=wait_until, timeout_ms=timeout_ms
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

        if allow_solve is None:
            allow_solve = (
                engine_name != "lightpanda"
                or self.config.solve_on_fast
                or self.config.solve_mode == "always"
            )
        solve_mode = self.config.solve_mode
        wants_solve = challenge and (
            challenge.blocking
            or self.config.solve_present
            or solve_mode == "always"
        )
        kind_is_solvable = (
            challenge is not None
            and (
                challenge.kind is ChallengeKind.TOKEN
                or solve_mode == "always"
            )
        )
        if (
            wants_solve
            and solve_mode != "never"
            and kind_is_solvable
            and self.solver is not None
            and allow_solve
        ):
            if not self._solve_allowed(nav.url):
                solver_failure = "domain not in PLAGUE_SOLVE_DOMAINS"
                log.info("solver skipped for %s: domain not allowed", nav.url)
            else:
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
                        log.warning("solver failed on %s: %s", engine_name, exc)
                    else:
                        solver_name = solution.provider
                        cost = solution.cost_usd
                        log.info(
                            "solved %s on %s with %s cost=%.4f",
                            challenge.vendor,
                            nav.url,
                            solver_name,
                            cost,
                        )
                        await inject_token(
                            session.page, challenge.vendor, solution.token
                        )
                        if challenge.blocking:
                            await session.wait_for_timeout(1500)
                            # Reload after injecting so clearance cookies and the
                            # real response replace the challenge document.
                            nav = await session.goto(
                                url, wait_until=wait_until, timeout_ms=timeout_ms
                            )
                            html = await session.content()
                        else:
                            # A widget on an accessible form: keep the page and
                            # its form state, do not reload.
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

        return nav, html, challenge, solved, solver_name, cost, solver_failure

    def _guard(self, url: str) -> None:
        """Apply PLAGUE_ALLOWED_DOMAINS according to the policy mode."""
        domains = self.config.allowed_domains
        if not domains:
            return
        policy = self.config.policy
        if policy == "open":
            return
        host = (urlparse(url).hostname or "").lower()
        if host and self._domain_matches(host, domains):
            return
        if policy == "warn":
            log.warning(
                "navigation outside PLAGUE_ALLOWED_DOMAINS (policy=warn): %s",
                host or url,
            )
            return
        raise PlagueError(
            f"domain not allowed by PLAGUE_ALLOWED_DOMAINS: {host or url}"
        )

    def _solve_allowed(self, url: str) -> bool:
        if self.config.solve_mode == "never":
            return False
        domains = self.config.solve_domains
        if not domains:
            return True
        host = (urlparse(url).hostname or "").lower()
        if host and self._domain_matches(host, domains):
            return True
        if self.config.policy in {"open", "warn"}:
            if self.config.policy == "warn":
                log.warning(
                    "solver outside PLAGUE_SOLVE_DOMAINS (policy=warn): %s",
                    host or url,
                )
            return True
        return False

    @staticmethod
    def _domain_matches(host: str, domains: Iterable[str]) -> bool:
        return any(
            host == domain or host.endswith("." + domain)
            for domain in domains
        )
