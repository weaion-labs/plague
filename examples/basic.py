"""Minimal fetch through the tier router."""

import asyncio

from plague import Plague


async def main() -> None:
    async with Plague() as plague:
        result = await plague.fetch("https://example.com")
        print(f"engine={result.engine} status={result.status} time={result.elapsed_ms}ms")
        print(f"title={result.title}")
        for attempt in result.attempts:
            print(
                f"  {attempt.engine}: ok={attempt.ok} "
                f"challenge={attempt.challenge} ms={attempt.elapsed_ms}"
            )
        print()
        print(result.text[:600])


if __name__ == "__main__":
    asyncio.run(main())
