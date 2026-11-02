"""Measure cold and warm speed, extraction accuracy, and memory per engine.

Usage:
    python benchmarks/bench_speed.py
    python benchmarks/bench_speed.py --concurrency 3
    python benchmarks/bench_speed.py --quick --repeat 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import psutil
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from plague import Config
from plague.engines import ChromeEngine, CloakEngine, LightpandaEngine
from server import start_server  # noqa: E402

PATCHED = ROOT / ".plague" / "lightpanda-src" / "zig-out" / "bin" / "lightpanda"
STOCK = ROOT / ".plague" / "bin" / "lightpanda"

PAGES: dict[str, dict[str, Any]] = {
    "/clean/1": {
        "title": "Clean Page 1",
        "tokens": ["token-1-0", "token-1-29"],
        "settle_ms": 0,
    },
    "/clean/2": {
        "title": "Clean Page 2",
        "tokens": ["token-2-0", "token-2-29"],
        "settle_ms": 0,
    },
    "/js/1": {
        "title": "JS Page 1",
        "tokens": ["Hydrated 1", "js-token-1"],
        "settle_ms": 250,
    },
    "/large": {
        "title": "Large Page",
        "tokens": ["large-token-0", "large-token-1199"],
        "settle_ms": 0,
    },
}
PATHS = list(PAGES)

console = Console()


def tree_rss_mb() -> float:
    process = psutil.Process(os.getpid())
    total = process.memory_info().rss
    for child in process.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            continue
    return total / (1024 * 1024)


def checks_for(path: str, title: str, text: str) -> list[bool]:
    info = PAGES[path]
    checks = [title.strip() == info["title"]]
    checks.extend(token in text for token in info["tokens"])
    return checks


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class EngineSpec:
    name: str
    engine: Any
    config: Config


def make_config(binary: Path | None = None) -> Config:
    config = Config.from_env()
    config.headless = True
    config.humanize = False
    config.timeout_ms = 30_000
    if binary is not None:
        config.lightpanda_bin = str(binary)
    return config


def build_engines(quick: bool) -> list[EngineSpec]:
    specs: list[EngineSpec] = []
    if PATCHED.is_file():
        config = make_config(PATCHED)
        specs.append(EngineSpec("lightpanda-patched", LightpandaEngine(config), config))
    if STOCK.is_file() and not quick:
        config = make_config(STOCK)
        specs.append(EngineSpec("lightpanda-stock", LightpandaEngine(config), config))
    if not quick:
        config = make_config()
        specs.append(EngineSpec("cloak", CloakEngine(config), config))
    config = make_config()
    specs.append(EngineSpec("chrome", ChromeEngine(config), config))
    return specs


async def cold_engine(spec: EngineSpec, base_url: str) -> dict[str, Any]:
    times: list[float] = []
    goto_times: list[float] = []
    checks: list[bool] = []

    for path in PATHS:
        started = time.perf_counter()
        session = await spec.engine.open(spec.config.profile())
        try:
            nav_started = time.perf_counter()
            await session.goto(
                base_url + path, wait_until="domcontentloaded", timeout_ms=30_000
            )
            goto_times.append((time.perf_counter() - nav_started) * 1000)
            settle = PAGES[path]["settle_ms"]
            if settle:
                await session.wait_for_timeout(settle)
            title = await session.title()
            text = await session.text()
        finally:
            await session.close()
        times.append((time.perf_counter() - started) * 1000)
        checks.extend(checks_for(path, title, text))

    return {
        "cold_ms": times,
        "cold_mean_ms": mean(times),
        "cold_goto_ms": mean(goto_times),
        "checks": checks,
    }


async def warm_engine(
    spec: EngineSpec, base_url: str, repeat: int
) -> dict[str, Any]:
    deltas: list[float] = []
    goto_times: list[float] = []
    checks: list[bool] = []
    baseline = tree_rss_mb()

    session = await spec.engine.open(spec.config.profile())
    try:
        await session.goto(
            base_url + "/clean/1", wait_until="domcontentloaded", timeout_ms=30_000
        )
        await session.wait_for_timeout(100)
        rss = tree_rss_mb() - baseline

        for pass_index in range(repeat):
            for path in PATHS:
                started = time.perf_counter()
                nav_started = time.perf_counter()
                await session.goto(
                    base_url + path,
                    wait_until="domcontentloaded",
                    timeout_ms=30_000,
                )
                goto_times.append((time.perf_counter() - nav_started) * 1000)
                settle = PAGES[path]["settle_ms"]
                if settle:
                    await session.wait_for_timeout(settle)
                title = await session.title()
                text = await session.text()
                deltas.append((time.perf_counter() - started) * 1000)
                if pass_index == 0:
                    checks.extend(checks_for(path, title, text))
    finally:
        await session.close()

    return {
        "warm_ms": deltas,
        "warm_mean_ms": mean(deltas),
        "warm_p50_ms": percentile(deltas, 50),
        "warm_p95_ms": percentile(deltas, 95),
        "warm_goto_ms": mean(goto_times),
        "rss_mb": max(0.0, rss),
        "checks": checks,
    }


async def concurrent_engine(
    spec: EngineSpec, base_url: str, count: int
) -> dict[str, Any]:
    baseline = tree_rss_mb()
    started = time.perf_counter()
    sessions = await asyncio.gather(
        *[spec.engine.open(spec.config.profile()) for _ in range(count)]
    )
    peak = tree_rss_mb() - baseline
    try:
        await asyncio.gather(
            *[
                session.goto(
                    base_url + "/clean/1",
                    wait_until="domcontentloaded",
                    timeout_ms=30_000,
                )
                for session in sessions
            ]
        )
        await asyncio.gather(*[session.text() for session in sessions])
    finally:
        await asyncio.gather(
            *[session.close() for session in sessions], return_exceptions=True
        )
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "concurrent_ms": elapsed,
        "concurrent_per_page_ms": elapsed / count,
        "concurrent_rss_mb": max(0.0, peak),
    }


async def playwright_baseline(base_url: str, repeat: int) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    cold: list[float] = []
    warm: list[float] = []
    checks: list[bool] = []
    baseline = tree_rss_mb()

    playwright = await async_playwright().start()
    try:
        for path in PATHS:
            started = time.perf_counter()
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(
                    base_url + path,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                settle = PAGES[path]["settle_ms"]
                if settle:
                    await page.wait_for_timeout(settle)
                title = await page.title()
                text = await page.inner_text("body")
            finally:
                await browser.close()
            cold.append((time.perf_counter() - started) * 1000)
            checks.extend(checks_for(path, title, text))

        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(
                base_url + "/clean/1", wait_until="domcontentloaded", timeout=30_000
            )
            await page.wait_for_timeout(100)
            rss = tree_rss_mb() - baseline
            for pass_index in range(repeat):
                for path in PATHS:
                    started = time.perf_counter()
                    await page.goto(
                        base_url + path,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    settle = PAGES[path]["settle_ms"]
                    if settle:
                        await page.wait_for_timeout(settle)
                    title = await page.title()
                    text = await page.inner_text("body")
                    warm.append((time.perf_counter() - started) * 1000)
                    if pass_index == 0:
                        checks.extend(checks_for(path, title, text))
        finally:
            await browser.close()
    finally:
        await playwright.stop()

    return {
        "cold_ms": cold,
        "cold_mean_ms": mean(cold),
        "cold_goto_ms": 0.0,
        "warm_ms": warm,
        "warm_mean_ms": mean(warm),
        "warm_p50_ms": percentile(warm, 50),
        "warm_p95_ms": percentile(warm, 95),
        "warm_goto_ms": 0.0,
        "rss_mb": max(0.0, rss),
        "checks": checks,
    }


def accuracy(checks: list[bool]) -> float:
    return 100.0 * sum(checks) / len(checks) if checks else 0.0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=0)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json", default="out/speed.json")
    args = parser.parse_args()

    server, base_url = start_server()
    specs = build_engines(args.quick)
    rows: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}

    try:
        for spec in specs:
            console.print(f"[cyan]{spec.name}[/cyan] cold ...")
            cold = await cold_engine(spec, base_url)
            console.print(f"[cyan]{spec.name}[/cyan] warm ...")
            warm = await warm_engine(spec, base_url, args.repeat)
            row = {
                "engine": spec.name,
                **cold,
                **warm,
                "accuracy": accuracy(cold["checks"]),
                "warm_accuracy": accuracy(warm["checks"]),
            }
            if args.concurrency:
                console.print(
                    f"[cyan]{spec.name}[/cyan] concurrent x{args.concurrency} ..."
                )
                row.update(
                    await concurrent_engine(spec, base_url, args.concurrency)
                )
            rows.append(row)
            raw[spec.name] = row

        console.print("[cyan]playwright-chromium[/cyan] cold ...")
        pw_cold = await playwright_baseline(base_url, args.repeat)
        rows.append(
            {
                "engine": "playwright-chromium",
                **pw_cold,
                "accuracy": accuracy(pw_cold["checks"]),
                "warm_accuracy": accuracy(pw_cold["checks"]),
            }
        )
        raw["playwright-chromium"] = rows[-1]
    finally:
        server.shutdown()
        server.server_close()

    table = Table(title="speed and accuracy (local pages)")
    table.add_column("engine", style="cyan", no_wrap=True)
    table.add_column("cold ms", justify="right")
    table.add_column("warm ms", justify="right")
    table.add_column("p50 ms", justify="right")
    table.add_column("p95 ms", justify="right")
    table.add_column("acc %", justify="right")
    table.add_column("rss MB", justify="right")
    if args.concurrency:
        table.add_column("conc ms", justify="right")
        table.add_column("conc RSS", justify="right")

    for row in rows:
        values = [
            row["engine"],
            f"{row['cold_mean_ms']:.0f}",
            f"{row['warm_mean_ms']:.0f}",
            f"{row['warm_p50_ms']:.0f}",
            f"{row['warm_p95_ms']:.0f}",
            f"{row['accuracy']:.0f}",
            f"{row['rss_mb']:.0f}",
        ]
        if args.concurrency:
            values += [
                f"{row.get('concurrent_ms', 0):.0f}",
                f"{row.get('concurrent_rss_mb', 0):.0f}",
            ]
        table.add_row(*values)
    console.print(table)

    output = Path(args.json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    console.print(f"wrote {output}")


if __name__ == "__main__":
    asyncio.run(main())
