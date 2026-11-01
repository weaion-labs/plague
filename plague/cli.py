"""Command line interface for plague."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from . import __version__
from .challenge import SolverError
from .config import Config, project_cache_dir
from .fingerprint import collect as collect_fingerprint
from .install import InstallError, install_lightpanda
from .models import Action, Attempt, Tier
from .router import CHAINS, Plague, PlagueError
from .serialize import error_dict, probe_dict, result_dict

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.version_option(__version__, prog_name="plague")
@click.option("-v", "--verbose", count=True, help="More logging on stderr.")
@click.pass_context
def main(ctx: click.Context, verbose: int) -> None:
    """Plague: Lightpanda speed, CloakBrowser stealth, Chrome compatibility."""
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


def _config(
    *,
    solver: str | None = None,
    proxy: str | None = None,
    headed: bool = False,
    humanize: bool | None = None,
    timeout: int | None = None,
    geoip: bool | None = None,
    solve_present: bool | None = None,
) -> Config:
    config = Config.from_env()
    if solver:
        config.solver = solver
    if proxy:
        config.proxy = proxy
    if headed or config.solver == "manual":
        config.headless = False
    if humanize is not None:
        config.humanize = humanize
    if timeout is not None:
        config.timeout_ms = timeout
    if geoip is not None:
        config.geoip = geoip
    if solve_present is not None:
        config.solve_present = solve_present
    return config


def _attempts_table(attempts: list[Attempt]) -> Table:
    table = Table(title="attempts", show_lines=False)
    table.add_column("engine", style="cyan", no_wrap=True)
    table.add_column("result", no_wrap=True)
    table.add_column("status", justify="right")
    table.add_column("challenge", overflow="fold")
    table.add_column("ms", justify="right")
    table.add_column("note", overflow="fold")
    for attempt in attempts:
        if attempt.skipped:
            outcome = "[yellow]skip[/yellow]"
        elif attempt.ok:
            outcome = "[green]ok[/green]"
        else:
            outcome = "[red]fail[/red]"
        note_parts = []
        if attempt.solver:
            note_parts.append(f"solver={attempt.solver}")
        if attempt.cost_usd:
            note_parts.append(f"${attempt.cost_usd:.4f}")
        if attempt.error:
            note_parts.append(attempt.error)
        table.add_row(
            attempt.engine,
            outcome,
            str(attempt.status or ""),
            attempt.challenge or "",
            str(attempt.elapsed_ms),
            " ".join(note_parts),
        )
    return table


def _install_with_progress(force: bool = False) -> Path:
    with Progress(
        TextColumn("[bold]lightpanda[/bold]"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("download", total=None)
        path = install_lightpanda(
            force=force,
            progress=lambda written, total: progress.update(
                task, completed=written, total=total or None
            ),
        )
    return path


@main.command()
@click.option("--install", "do_install", is_flag=True, help="Download Lightpanda if missing.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def doctor(do_install: bool, as_json: bool) -> None:
    """Show engine availability, capabilities, and solver configuration."""
    if do_install:
        try:
            path = _install_with_progress()
            console.print(f"installed Lightpanda at [cyan]{path}[/cyan]")
        except InstallError as exc:
            err_console.print(f"[red]install failed:[/red] {exc}")
            raise SystemExit(1) from exc

    config = Config.from_env()
    plague = Plague(config)
    try:
        rows = plague.describe_engines()
        solver = {
            "requested": config.solver,
            "active": plague.solver.name if plague.solver else None,
            "capsolver_key": bool(config.capsolver_key),
            "twocaptcha_key": bool(config.twocaptcha_key),
            "error": plague.solver_error,
        }
        paths = {
            "lightpanda_bin": config.lightpanda_bin,
            "chrome_executable": config.chrome_executable,
            "cache": str(project_cache_dir()),
        }
    finally:
        asyncio.run(plague.close())

    if as_json:
        click.echo(json.dumps({"engines": rows, "solver": solver, "paths": paths}, indent=2))
        return

    table = Table(title="engines")
    table.add_column("engine", style="cyan", no_wrap=True)
    table.add_column("ready")
    table.add_column("detail", overflow="fold")
    table.add_column("capabilities", overflow="fold")
    for row in rows:
        table.add_row(
            row["name"],
            "[green]yes[/green]" if row["available"] else "[red]no[/red]",
            row["reason"],
            ", ".join(row["capabilities"]),
        )
    console.print(table)

    console.print()
    console.print("[bold]solver[/bold]")
    console.print(f"  requested: {solver['requested']}")
    console.print(f"  active:    {solver['active'] or 'none'}")
    console.print(f"  capsolver key: {'set' if solver['capsolver_key'] else 'missing'}")
    console.print(f"  2captcha key:  {'set' if solver['twocaptcha_key'] else 'missing'}")
    if solver["error"]:
        console.print(f"  [yellow]error:[/yellow] {solver['error']}")

    console.print()
    console.print("[bold]paths[/bold]")
    for key, value in paths.items():
        console.print(f"  {key}: {value or 'not found'}")


@main.command()
@click.argument("url")
@click.option("--tier", type=click.Choice([t.value for t in Tier]), default="auto")
@click.option(
    "--wait-until",
    type=click.Choice(["commit", "domcontentloaded", "load", "networkidle"]),
    default="domcontentloaded",
)
@click.option("--timeout", type=int, default=None, help="Navigation timeout in ms.")
@click.option("--html", "html_path", type=click.Path(dir_okay=False), help="Save HTML here.")
@click.option("--screenshot", type=click.Path(dir_okay=False), help="Save a full-page PNG here.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--headed", is_flag=True, help="Show the browser window.")
@click.option("--humanize/--no-humanize", default=None)
@click.option("--geoip", is_flag=True, default=None, help="Match timezone and locale to the proxy IP (Cloak).")
@click.option("--solve-widgets", is_flag=True, default=None, help="Solve token widgets even when the page is not blocked.")
@click.option("--proxy", default=None)
@click.option(
    "--solver",
    type=click.Choice(["auto", "none", "capsolver", "2captcha", "manual"]),
    default=None,
)
@click.option("--manual", is_flag=True, help="Solve challenges by hand in a headed window.")
@click.option("--click", "clicks", multiple=True, help="CSS selector to click before extraction.")
@click.option("--fill", "fills", multiple=True, help="selector=value to fill before extraction.")
@click.option("--no-text", is_flag=True, help="Do not print the text preview.")
def fetch(
    url: str,
    tier: str,
    wait_until: str,
    timeout: int | None,
    html_path: str | None,
    screenshot: str | None,
    as_json: bool,
    headed: bool,
    humanize: bool | None,
    geoip: bool | None,
    solve_widgets: bool | None,
    proxy: str | None,
    solver: str | None,
    manual: bool,
    clicks: tuple[str, ...],
    fills: tuple[str, ...],
    no_text: bool,
) -> None:
    """Fetch one URL through the tier router."""
    if manual:
        solver = "manual"
        headed = True

    actions: list[Action] = []
    for selector in clicks:
        actions.append(Action(type="click", selector=selector))
    for item in fills:
        if "=" not in item:
            raise click.BadParameter(f"expected selector=value, got {item!r}")
        selector, value = item.split("=", 1)
        actions.append(Action(type="fill", selector=selector, value=value))

    config = _config(
        solver=solver,
        proxy=proxy,
        headed=headed,
        humanize=humanize,
        timeout=timeout,
        geoip=geoip,
        solve_present=solve_widgets,
    )

    async def run():
        plague = Plague(config)
        try:
            return await plague.fetch(
                url,
                tier=tier,
                wait_until=wait_until,
                timeout_ms=timeout,
                screenshot=screenshot,
                actions=actions or None,
                geoip=geoip,
            )
        finally:
            await plague.close()

    try:
        result = asyncio.run(run())
    except PlagueError as exc:
        if as_json:
            click.echo(json.dumps(error_dict(exc), indent=2))
        else:
            err_console.print(f"[red]failed:[/red] {exc}")
            if exc.attempts:
                err_console.print(_attempts_table(exc.attempts))
        raise SystemExit(1) from exc
    except SolverError as exc:
        err_console.print(f"[red]solver error:[/red] {exc}")
        raise SystemExit(1) from exc

    if html_path:
        Path(html_path).write_text(result.html, encoding="utf-8")
    if as_json:
        click.echo(json.dumps(result_dict(result, include_html=False), indent=2))
        return

    status_style = "green" if result.ok else "red"
    console.print(
        f"[{status_style}]{result.status}[/{status_style}] "
        f"[bold]{result.title or '(no title)'}[/bold]"
    )
    console.print(
        f"engine=[cyan]{result.engine}[/cyan] "
        f"solved={'yes' if result.solved else 'no'} "
        f"time={result.elapsed_ms}ms "
        f"url={result.final_url}"
    )
    if result.challenge:
        console.print(
            f"challenge=[yellow]{result.challenge.label}[/yellow] "
            f"blocking={result.challenge.blocking} "
            f"solvable={result.challenge.solvable}"
        )
    console.print(_attempts_table(result.attempts))
    if not no_text and result.text:
        console.print()
        console.print("[bold]text[/bold]")
        console.print(result.text[:2000], markup=False)


@main.command("fingerprint")
@click.option("--tier", type=click.Choice([t.value for t in Tier]), default="auto")
@click.option("--all", "run_all", is_flag=True, help="Probe every configured engine.")
@click.option("--url", default="https://example.com")
@click.option("--json", "as_json", is_flag=True)
@click.option("--headed", is_flag=True)
@click.option("--proxy", default=None)
def fingerprint_cmd(
    tier: str,
    run_all: bool,
    url: str,
    as_json: bool,
    headed: bool,
    proxy: str | None,
) -> None:
    """Compare navigator, screen, client hints, and canvas across engines."""
    config = _config(proxy=proxy, headed=headed)

    async def run():
        plague = Plague(config)
        names = (
            list(plague.engines)
            if run_all
            else [n for n in CHAINS[Tier(tier)] if n in plague.engines]
        )
        results: dict[str, dict] = {}
        try:
            for name in names:
                engine = plague.engines[name]
                session = None
                try:
                    session = await engine.open(config.profile())
                    await session.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout_ms=config.timeout_ms,
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

    results = asyncio.run(run())
    if as_json:
        click.echo(json.dumps(results, indent=2, default=str))
        return

    names = list(results)
    table = Table(title=f"fingerprint ({url})")
    table.add_column("property", style="cyan", no_wrap=True)
    for name in names:
        table.add_column(name, overflow="fold")

    keys: list[str] = []
    for data in results.values():
        for key in data:
            if key not in keys:
                keys.append(key)

    for key in keys:
        row = [key]
        for name in names:
            value = results[name].get(key, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value, default=str)
            row.append(str(value)[:120])
        table.add_row(*row)
    console.print(table)


@main.command("detect")
@click.argument("url")
@click.option("--tier", type=click.Choice([t.value for t in Tier]), default="auto")
@click.option("--timeout", type=int, default=None)
@click.option("--headed", is_flag=True)
@click.option("--proxy", default=None)
@click.option("--json", "as_json", is_flag=True)
def detect_cmd(
    url: str, tier: str, timeout: int | None, headed: bool, proxy: str | None, as_json: bool
) -> None:
    """Classify a page's challenge wall without solving or escalating."""
    config = _config(proxy=proxy, headed=headed, timeout=timeout)

    async def run():
        plague = Plague(config)
        try:
            return await plague.probe(url, tier=tier, timeout_ms=timeout)
        finally:
            await plague.close()

    try:
        probe = asyncio.run(run())
    except PlagueError as exc:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            err_console.print(f"[red]probe failed:[/red] {exc}")
        raise SystemExit(1) from exc

    if as_json:
        click.echo(json.dumps(probe_dict(probe), indent=2))
    else:
        console.print(f"engine=[cyan]{probe.engine}[/cyan] status={probe.status} time={probe.elapsed_ms}ms")
        console.print(f"url={probe.final_url}")
        console.print(f"title={probe.title}")
        if probe.challenge is None:
            console.print("[green]no challenge detected[/green]")
        else:
            challenge = probe.challenge
            console.print(
                f"challenge=[yellow]{challenge.label}[/yellow] "
                f"blocking={challenge.blocking} solvable={challenge.solvable} "
                f"confidence={challenge.confidence:.2f}"
            )
            if challenge.sitekey:
                console.print(f"sitekey={challenge.sitekey}")
            for item in challenge.evidence:
                console.print(f"  evidence: {item}", markup=False)

    if probe.challenge and probe.challenge.blocking:
        raise SystemExit(1)


@main.command()
@click.argument("urls", nargs=-1)
@click.option("--file", "url_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--tier", type=click.Choice([t.value for t in Tier]), default="auto")
@click.option("--timeout", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def bench(
    urls: tuple[str, ...],
    url_file: str | None,
    tier: str,
    timeout: int | None,
    as_json: bool,
) -> None:
    """Run a list of URLs and report engine, status, and latency."""
    targets = list(urls)
    if url_file:
        targets += [
            line.strip()
            for line in Path(url_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    if not targets:
        raise click.UsageError("provide URLs or --file")

    config = _config(timeout=timeout)

    async def run():
        plague = Plague(config)
        rows = []
        try:
            for target in targets:
                try:
                    result = await plague.fetch(target, tier=tier, timeout_ms=timeout)
                    rows.append(
                        {
                            "url": target,
                            "ok": result.ok,
                            "engine": result.engine,
                            "status": result.status,
                            "ms": result.elapsed_ms,
                            "challenge": result.challenge.label if result.challenge else None,
                            "error": None,
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "url": target,
                            "ok": False,
                            "engine": None,
                            "status": None,
                            "ms": None,
                            "challenge": None,
                            "error": str(exc),
                        }
                    )
        finally:
            await plague.close()
        return rows

    rows = asyncio.run(run())
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return

    table = Table(title=f"bench ({tier})")
    table.add_column("url", overflow="fold")
    table.add_column("ok", no_wrap=True)
    table.add_column("engine", no_wrap=True)
    table.add_column("status", justify="right")
    table.add_column("ms", justify="right")
    table.add_column("challenge", overflow="fold")
    for row in rows:
        table.add_row(
            row["url"],
            "[green]yes[/green]" if row["ok"] else "[red]no[/red]",
            row["engine"] or "",
            str(row["status"] or ""),
            str(row["ms"] or ""),
            row["challenge"] or row["error"] or "",
        )
    console.print(table)

    ok = [row for row in rows if row["ok"]]
    if ok:
        mean = sum(row["ms"] for row in ok) / len(ok)
        engines: dict[str, int] = {}
        for row in ok:
            engines[row["engine"]] = engines.get(row["engine"], 0) + 1
        console.print(
            f"success {len(ok)}/{len(rows)} | mean {mean:.0f}ms | "
            + ", ".join(f"{k}={v}" for k, v in sorted(engines.items()))
        )


@main.command("install-lightpanda")
@click.option("--force", is_flag=True)
def install_lightpanda_cmd(force: bool) -> None:
    """Download the Lightpanda nightly binary for this machine."""
    try:
        path = _install_with_progress(force=force)
    except InstallError as exc:
        err_console.print(f"[red]install failed:[/red] {exc}")
        raise SystemExit(1) from exc
    console.print(f"installed at [cyan]{path}[/cyan]")
