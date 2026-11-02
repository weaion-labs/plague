from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_mcp_server_lists_tools_and_reports_doctor():
    async def scenario():
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        patched = ROOT / ".plague" / "lightpanda-src" / "zig-out" / "bin" / "lightpanda"
        if patched.is_file():
            env["PLAGUE_LIGHTPANDA_BIN"] = str(patched)

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "plague.mcp_server"],
            env=env,
            cwd=str(ROOT),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(tool.name for tool in tools.tools)
                result = await session.call_tool("doctor", {})
                return names, result

    names, result = asyncio.run(scenario())

    assert {
        "bench",
        "captcha_demos",
        "detect",
        "doctor",
        "fetch",
        "fingerprint",
    } <= set(names)
    assert result.content
    data = json.loads(result.content[0].text)
    assert "engines" in data
    assert {engine["name"] for engine in data["engines"]} == {
        "lightpanda",
        "cloak",
        "chrome",
    }
