"""Let the router solve a token-based challenge with CapSolver.

Point PLAGUE_TARGET at a URL that actually shows a token wall. On a clean page
the solver is never called, by design.
"""

import asyncio
import os

from plague import Config, Plague, Tier

TARGET = os.environ.get("PLAGUE_TARGET", "https://example.com")


async def main() -> None:
    config = Config.from_env()
    config.solver = "capsolver"  # requires CAPSOLVER_API_KEY
    config.humanize = True

    async with Plague(config) as plague:
        result = await plague.fetch(
            TARGET,
            tier=Tier.STEALTH,
            screenshot="out/solved.png",
        )
        print(f"engine={result.engine} solved={result.solved}")
        if result.challenge:
            print(f"challenge={result.challenge.label}")
        for attempt in result.attempts:
            print(
                f"  {attempt.engine}: challenge={attempt.challenge} "
                f"solver={attempt.solver} cost=${attempt.cost_usd:.4f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
