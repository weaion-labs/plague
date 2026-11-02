"""Project-local MCP server for Plague.

Run with:

    python -m plague.mcp_server

It speaks MCP over stdio. The server is intentionally not installed as a
console script; OpenCode starts it from `.opencode/opencode.json` with the
project root as its working directory.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any

# The MCP SDK's settings model emits this on Python 3.14 before the server
# starts. It is harmless and would otherwise pollute the stdio stderr log.
warnings.filterwarnings(
    "ignore",
    message="Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP

from . import Config, Plague, PlagueError, Tier
from .fingerprint import collect as collect_fingerprint
from .serialize import error_dict, probe_dict, result_dict

ROOT = Path(__file__).resolve().parents[1]
PATCHED_BINARY = ROOT / ".plague" / "lightpanda-src" / "zig-out" / "bin" / "lightpanda"

# Prefer the locally built Chrome-persona binary unless the caller chose one.
if PATCHED_BINARY.is_file() and not os.environ.get("PLAGUE_LIGHTPANDA_BIN"):
    os.environ["PLAGUE_LIGHTPANDA_BIN"] = str(PATCHED_BINARY)

INSTRUCTIONS = """
Plague is a tiered browser router: Lightpanda first for speed, CloakBrowser when
a wall appears, stock Chrome as the reference. Use `doctor` to see what is
available. Use `fetch` to retrieve a page, `detect` to classify a challenge
without solving, `fingerprint` to compare JS and network surfaces, and `bench`
for a list of URLs. `captcha_demos` runs the public demo walls.

Without solver keys, token walls are detected and classified but no token is
purchased. The patched Lightpanda binary is used automatically when present at
.plague/lightpanda-src/zig-out/bin/lightpanda.
""".strip()

mcp = FastMCP("plague", instructions=INSTRUCTIONS, log_level="WARNING")


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


@mcp.tool()
async def doctor() -> dict[str, Any]:
    """Show engine availability, the active solver, and the binary in use."""
    plague = Plague(Config.from_env())
    try:
        return {
            "engines": plague.describe_engines(),
            "solver": {
                "active": plague.solver.name if plague.solver else None,
                "error": plague.solver_error,
            },
            "patched_lightpanda": str(PATCHED_BINARY)
            if PATCHED_BINARY.is_file()
            else None,
            "lightpanda_bin": os.environ.get("PLAGUE_LIGHTPANDA_BIN"),
        }
    finally:
        await plague.close()


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
) -> dict[str, Any]:
    """Fetch one URL through the tier router and return a structured result.

    Args:
        url: Page to fetch.
        tier: auto, fast, stealth, or chrome.
        timeout_ms: Navigation timeout in milliseconds.
        screenshot: Optional path for a full-page PNG.
        solve_widgets: Also solve token widgets on pages that are not blocked.
        headed: Show the browser window.
        proxy: Proxy URL for this call.
        include_html: Include the full HTML in the result.
        max_text_chars: Truncate the extracted text to this many characters.
    """
    config = _config(
        timeout_ms=timeout_ms,
        solve_widgets=solve_widgets,
        headed=headed,
        proxy=proxy,
    )
    if screenshot:
        Path(screenshot).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )

    plague = Plague(config)
    try:
        try:
            result = await plague.fetch(
                url,
                tier=tier,
                timeout_ms=timeout_ms,
                screenshot=str(Path(screenshot).expanduser()) if screenshot else None,
                headed=True if headed else None,
                proxy=proxy,
            )
        except PlagueError as exc:
            return error_dict(exc)
        return _trim(result_dict(result, include_html=include_html), max_text_chars)
    finally:
        await plague.close()


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
) -> dict[str, Any]:
    """Fetch a list of URLs and report engine, status, challenge, and latency."""
    config = _config(timeout_ms=timeout_ms)
    plague = Plague(config)
    rows: list[dict[str, Any]] = []
    try:
        for url in urls:
            try:
                result = await plague.fetch(
                    url, tier=tier, timeout_ms=timeout_ms
                )
                rows.append(
                    {
                        "url": url,
                        "ok": result.ok,
                        "engine": result.engine,
                        "status": result.status,
                        "ms": result.elapsed_ms,
                        "challenge": result.challenge.label
                        if result.challenge
                        else None,
                        "solved": result.solved,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "url": url,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    finally:
        await plague.close()
    return {"rows": rows}


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
    result = await bench(targets, tier=tier, timeout_ms=timeout_ms)
    result["solver_keys"] = {
        "capsolver": bool(os.environ.get("CAPSOLVER_API_KEY")),
        "twocaptcha": bool(os.environ.get("TWOCAPTCHA_API_KEY")),
    }
    return result


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
