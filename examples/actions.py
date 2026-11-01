"""Interact with a page before extracting it."""

import asyncio

from plague import Action, Plague


async def main() -> None:
    async with Plague() as plague:
        result = await plague.fetch(
            "https://news.ycombinator.com",
            actions=[
                Action(type="click", selector="a.morelink"),
                Action(type="wait", value="1000"),
            ],
        )
        print(result.engine, result.status, result.final_url)
        print(result.text[:800])


if __name__ == "__main__":
    asyncio.run(main())
