#!/usr/bin/env python3
"""Run a matrix of CAPTCHA demos through Plague and record what happens.

Usage:
    python scripts/captcha_matrix.py
    python scripts/captcha_matrix.py --tier stealth --tier auto --json out/matrix.json
    python scripts/captcha_matrix.py --url https://example.com/demo

Solver keys from the environment are used automatically. With no keys, token
walls are detected and reported but not solved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plague import Config, Plague, PlagueError, Tier  # noqa: E402
from plague.serialize import attempt_dict  # noqa: E402

DEMOS = [
    "https://nopecha.com/demo/cloudflare",
    "https://nopecha.com/demo/turnstile",
    "https://nopecha.com/demo/recaptcha",
    "https://nopecha.com/demo/hcaptcha",
    "https://2captcha.com/demo/recaptcha-v2",
    "https://www.google.com/recaptcha/api2/demo",
]


async def run_one(plague: Plague, url: str, tier: str, timeout_ms: int) -> dict:
    started = time.monotonic()
    try:
        result = await plague.fetch(
            url, tier=tier, timeout_ms=timeout_ms, wait_until="domcontentloaded"
        )
        return {
            "url": url,
            "tier": tier,
            "ok": result.ok,
            "engine": result.engine,
            "status": result.status,
            "ms": result.elapsed_ms,
            "challenge": result.challenge.label if result.challenge else None,
            "blocking": result.challenge.blocking if result.challenge else False,
            "kind": result.challenge.kind.value if result.challenge else None,
            "solvable": result.challenge.solvable if result.challenge else False,
            "solved": result.solved,
            "title": result.title,
            "text_len": len(result.text),
            "attempts": [attempt_dict(a) for a in result.attempts],
        }
    except PlagueError as exc:
        return {
            "url": url,
            "tier": tier,
            "ok": False,
            "error": str(exc),
            "ms": int((time.monotonic() - started) * 1000),
            "attempts": [attempt_dict(a) for a in exc.attempts],
        }
    except Exception as exc:
        return {
            "url": url,
            "tier": tier,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "ms": int((time.monotonic() - started) * 1000),
        }


async def main_async(args) -> list[dict]:
    config = Config.from_env()
    config.timeout_ms = args.timeout
    plague = Plague(config)
    rows = []
    try:
        for url in args.url:
            for tier in args.tier:
                print(f"{tier:8} {url} ...", flush=True)
                row = await run_one(plague, url, tier, args.timeout)
                rows.append(row)
                print(
                    f"         ok={row.get('ok')} engine={row.get('engine')} "
                    f"challenge={row.get('challenge')} solved={row.get('solved')} "
                    f"ms={row.get('ms')}",
                    flush=True,
                )
    finally:
        await plague.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", action="append", default=None)
    parser.add_argument("--url", action="append", default=None)
    parser.add_argument("--timeout", type=int, default=30_000)
    parser.add_argument("--json", default="out/captcha-matrix.json")
    args = parser.parse_args()
    args.tier = args.tier or ["auto", "stealth"]
    args.url = args.url or DEMOS

    print(
        "solver keys: capsolver=%s 2captcha=%s"
        % (bool(os.environ.get("CAPSOLVER_API_KEY")), bool(os.environ.get("TWOCAPTCHA_API_KEY")))
    )
    rows = asyncio.run(main_async(args))
    output = Path(args.json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print()
    print(f"{'tier':8} {'engine':10} {'status':6} {'challenge':28} {'solved':6} {'ms':6} url")
    for row in rows:
        print(
            f"{row.get('tier', ''):8} {str(row.get('engine') or '-'):10} "
            f"{str(row.get('status') or '-'):6} {str(row.get('challenge') or '-'):28} "
            f"{str(row.get('solved', False)):6} {str(row.get('ms') or '-'):6} {row['url']}"
        )
    print(f"\nwrote {output}")


if __name__ == "__main__":
    main()
