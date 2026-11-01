"""Lightpanda: the fast, rendering-free tier, driven over CDP."""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

from ..config import project_cache_dir
from ..models import Capability, EngineInfo, Profile
from .base import BaseEngine, EngineError, EngineUnavailable, Session

log = logging.getLogger("plague.engine.lightpanda")

CAPABILITIES = frozenset(
    {
        Capability.ROUTES,
        Capability.STORAGE_STATE,
        Capability.COOKIES,
        Capability.INIT_SCRIPT,
    }
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LightpandaEngine(BaseEngine):
    info = EngineInfo(
        name="lightpanda",
        capabilities=CAPABILITIES,
        description="Lightpanda, a Zig headless browser with no layout engine",
    )

    def availability(self) -> tuple[bool, str]:
        binary = self._binary()
        if not binary:
            return False, "binary not found (run: plague doctor --install)"
        try:
            result = subprocess.run(
                [binary, "version"], capture_output=True, text=True, timeout=5
            )
            version = (result.stdout or result.stderr).strip().splitlines()
            return True, version[0] if version else binary
        except Exception as exc:
            return False, f"cannot execute {binary}: {exc}"

    def _binary(self) -> str | None:
        if self.config.lightpanda_bin and Path(self.config.lightpanda_bin).is_file():
            return self.config.lightpanda_bin
        from ..config import find_lightpanda

        return find_lightpanda()

    async def open(self, profile: Profile) -> Session:
        binary = self._binary()
        if not binary:
            raise EngineUnavailable(
                "lightpanda binary not found; run `plague doctor --install`"
            )

        port = self.config.lightpanda_port or _free_port()
        log_dir = project_cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"lightpanda-{port}.log"
        log_file = open(log_path, "ab")

        args = [
            binary,
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warn",
        ]
        args += self.config.lightpanda_args
        if profile.proxy:
            args += ["--http-proxy", profile.proxy]
        if profile.locale:
            args += ["--locale", profile.locale]
        for key, value in (profile.extra_headers or {}).items():
            args += ["--http-header", f"{key}: {value}"]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )

        playwright = None
        browser = None
        try:
            await self._wait_ready(proc, port, log_path)
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(
                f"ws://127.0.0.1:{port}"
            )

            context_kwargs: dict = {"locale": profile.locale}
            if profile.timezone:
                context_kwargs["timezone_id"] = profile.timezone
            if profile.user_agent:
                context_kwargs["user_agent"] = profile.user_agent
            if profile.viewport:
                context_kwargs["viewport"] = profile.viewport
            if profile.storage_state:
                context_kwargs["storage_state"] = profile.storage_state

            try:
                context = await browser.new_context(**context_kwargs)
            except Exception as exc:
                # Lightpanda implements a CDP subset; a context option it does
                # not understand must not take the whole tier down.
                log.debug("lightpanda context options rejected (%s), retrying bare", exc)
                context = await browser.new_context()
            page = await context.new_page()

            async def _stop_playwright() -> None:
                if playwright is not None:
                    await playwright.stop()

            async def _kill() -> None:
                await self._terminate(proc)

            async def _close_log() -> None:
                try:
                    log_file.close()
                except Exception:
                    pass

            return Session(
                page=page,
                context=context,
                browser=browser,
                info=self.info,
                closers=[_close_log, _kill, _stop_playwright, browser.close],
            )
        except Exception as exc:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass
            await self._terminate(proc)
            try:
                log_file.close()
            except Exception:
                pass
            tail = self._log_tail(log_path)
            detail = f": {tail}" if tail else ""
            raise EngineError(f"lightpanda failed to start{detail}") from exc

    async def _wait_ready(
        self, proc: asyncio.subprocess.Process, port: int, log_path: Path
    ) -> None:
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            if proc.returncode is not None:
                tail = self._log_tail(log_path)
                raise EngineUnavailable(
                    f"lightpanda exited with code {proc.returncode}: {tail}"
                )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                del reader
                return
            except OSError:
                await asyncio.sleep(0.1)
        raise EngineUnavailable("lightpanda did not open its CDP port in time")

    @staticmethod
    async def _terminate(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass

    @staticmethod
    def _log_tail(path: Path, lines: int = 6) -> str:
        try:
            content = path.read_text(errors="replace").strip().splitlines()
            return " | ".join(content[-lines:])
        except Exception:
            return ""
