"""Stealth tier with a residential proxy and humanized input."""

import asyncio
import os

from plague import Config, Plague, Tier


async def main() -> None:
    config = Config.from_env()
    config.proxy = os.environ.get("RESIDENTIAL_PROXY")
    config.humanize = True
    config.headless = False

    async with Plague(config) as plague:
        result = await plague.fetch(
            "https://example.com",
            tier=Tier.STEALTH,
            headed=True,
        )
        print(result.engine, result.status, result.elapsed_ms)
        print(result.text[:400])


if __name__ == "__main__":
    asyncio.run(main())
