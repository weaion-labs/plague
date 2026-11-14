from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

PAGE = b"""<!doctype html>
<html><head><title>Warm page</title></head>
<body><h1>Hello</h1><a href="/next">Next page</a>
<button id="go">Go</button></body></html>"""

FORM_PAGE = b"""<!doctype html>
<html><head><title>Form page</title></head>
<body>
<form id="f"><input name="q" aria-label="Search">
<button id="go" type="submit">Go</button></form>
<div id="out">nothing</div>
<script>
document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  document.getElementById('out').textContent =
    'hello ' + document.querySelector('input[name=q]').value;
});
</script></body></html>"""

OBS_PAGE = b"""<!doctype html>
<html><head><title>Observation</title></head>
<body><h1>Observe</h1>
<script>
console.log('obs-log');
fetch('/api').then((r) => r.text());
</script></body></html>"""


class _ObsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/api":
            payload = b'{"ok": true}'
            content_type = "application/json"
        else:
            payload = OBS_PAGE
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        return None


class _FormHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(FORM_PAGE)

    def log_message(self, *args):
        return None


def test_mcp_detect_names_do_not_collide():
    import plague.mcp_server as server
    from plague.challenge import detect as detector

    assert server.detect_challenge is detector
    assert server.detect is not detector


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    patched = ROOT / ".plague" / "lightpanda-src" / "zig-out" / "bin" / "lightpanda"
    if patched.is_file():
        env["PLAGUE_LIGHTPANDA_BIN"] = str(patched)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "plague.mcp_server"],
        env=env,
        cwd=str(ROOT),
    )


@pytest.mark.integration
def test_mcp_server_lists_tools_and_reports_doctor():
    async def scenario():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(tool.name for tool in tools.tools)
                result = await session.call_tool("doctor", {})
                return names, result

    names, result = asyncio.run(scenario())

    assert {
        "act",
        "api_request",
        "bench",
        "captcha",
        "captcha_demos",
        "console",
        "detect",
        "doctor",
        "fetch",
        "fingerprint",
        "handoff",
        "launch",
        "network",
        "network_export",
        "read",
        "recipe_delete",
        "recipe_list",
        "recipe_run",
        "recipe_save",
        "release",
        "screenshot",
        "snapshot",
        "storage_delete",
        "storage_list",
        "storage_load",
        "storage_save",
        "tab_close",
        "tab_open",
        "tab_switch",
        "tabs",
    } <= set(names)
    assert result.content
    data = json.loads(result.content[0].text)
    assert "engines" in data
    assert {engine["name"] for engine in data["engines"]} == {
        "lightpanda",
        "cloak",
        "chrome",
    }


@pytest.mark.integration
def test_mcp_warm_fetch_and_snapshot_reuse_one_session():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    async def scenario():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                first = await session.call_tool("fetch", {"url": url})
                second = await session.call_tool("fetch", {"url": url})
                snap = await session.call_tool(
                    "snapshot", {"tier": "fast", "limit": 20}
                )
                fast_read = await session.call_tool(
                    "read", {"url": url}
                )
                launched = await session.call_tool(
                    "launch", {"tier": "fast"}
                )
                cap = await session.call_tool(
                    "captcha", {"action": "status"}
                )
                await session.call_tool("release", {"all_sessions": True})
                return first, second, snap, fast_read, launched, cap

    try:
        first, second, snap, fast_read, launched, cap = asyncio.run(
            scenario()
        )
    finally:
        server.shutdown()
        server.server_close()

    first_data = json.loads(first.content[0].text)
    second_data = json.loads(second.content[0].text)
    snapshot_data = json.loads(snap.content[0].text)
    read_data = json.loads(fast_read.content[0].text)
    launch_data = json.loads(launched.content[0].text)
    captcha_data = json.loads(cap.content[0].text)

    assert first_data["ok"] is True
    assert second_data["ok"] is True
    assert second_data["warm"] is True
    assert second_data["url"] == url
    assert snapshot_data["count"] >= 2
    names = {item["name"] for item in snapshot_data["elements"]}
    assert "Next page" in names
    assert read_data["ok"] is True
    assert "Hello" in read_data["text"]
    assert launch_data["engine"] == "lightpanda"
    assert launch_data["tier"] == "fast"
    assert captcha_data["challenge"] is None


@pytest.mark.integration
def test_mcp_ref_actions_run_in_the_browser():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FormHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    async def scenario():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("fetch", {"url": url})
                snap = await session.call_tool("snapshot", {"tier": "fast"})
                data = json.loads(snap.content[0].text)
                refs = {
                    item["name"]: item["ref"]
                    for item in data["elements"]
                }
                result = await session.call_tool(
                    "act",
                    {
                        "tier": "fast",
                        "actions": [
                            {
                                "type": "fill",
                                "ref": refs["Search"],
                                "value": "plague",
                            },
                            {"type": "click", "ref": refs["Go"]},
                        ],
                    },
                )
                await session.call_tool("release", {"all_sessions": True})
                return result

    try:
        result = asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()

    data = json.loads(result.content[0].text)
    assert data["ok"] is True
    assert "hello plague" in data["text"]


@pytest.mark.integration
def test_mcp_chrome_observation_tabs_screenshot_and_storage():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ObsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    async def scenario():
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                fetched = await session.call_tool(
                    "fetch", {"url": url, "tier": "chrome"}
                )
                data = json.loads(fetched.content[0].text)
                if not data.get("ok"):
                    return {"skip": data}

                network = await session.call_tool(
                    "network",
                    {
                        "tier": "chrome",
                        "filter": "api",
                        "include_body": True,
                    },
                )
                har = await session.call_tool(
                    "network_export",
                    {"tier": "chrome", "format": "har", "filter": "api"},
                )
                curls = await session.call_tool(
                    "network_export",
                    {"tier": "chrome", "format": "curl", "filter": "api"},
                )
                logs = await session.call_tool(
                    "console", {"tier": "chrome", "filter": "obs"}
                )
                shot = await session.call_tool(
                    "screenshot", {"tier": "chrome"}
                )
                pages = await session.call_tool(
                    "tabs", {"tier": "chrome"}
                )
                opened = await session.call_tool(
                    "tab_open", {"tier": "chrome", "url": url}
                )
                switched = await session.call_tool(
                    "tab_switch", {"tier": "chrome", "index": 0}
                )
                closed = await session.call_tool(
                    "tab_close", {"tier": "chrome", "index": 1}
                )
                saved = await session.call_tool(
                    "storage_save", {"tier": "chrome", "name": "itest"}
                )
                states = await session.call_tool("storage_list", {})
                loaded = await session.call_tool(
                    "storage_load",
                    {"name": "itest", "tier": "chrome", "url": url},
                )
                deleted = await session.call_tool(
                    "storage_delete", {"name": "itest"}
                )
                await session.call_tool("release", {"all_sessions": True})
                return {
                    "network": json.loads(network.content[0].text),
                    "har": json.loads(har.content[0].text),
                    "curls": json.loads(curls.content[0].text),
                    "logs": json.loads(logs.content[0].text),
                    "shot": json.loads(shot.content[0].text),
                    "pages": json.loads(pages.content[0].text),
                    "opened": json.loads(opened.content[0].text),
                    "switched": json.loads(switched.content[0].text),
                    "closed": json.loads(closed.content[0].text),
                    "saved": json.loads(saved.content[0].text),
                    "states": json.loads(states.content[0].text),
                    "loaded": json.loads(loaded.content[0].text),
                    "deleted": json.loads(deleted.content[0].text),
                }

    try:
        out = asyncio.run(scenario())
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"chrome unavailable: {exc}")
    finally:
        server.shutdown()
        server.server_close()

    if "skip" in out:
        pytest.skip(f"chrome unavailable: {out['skip']}")

    assert out["network"]["count"] >= 1
    assert any("/api" in row["url"] for row in out["network"]["entries"])
    assert any(
        "ok" in row.get("body", "") for row in out["network"]["entries"]
    )
    assert out["har"]["ok"] is True
    assert out["har"]["entries"] >= 1
    assert out["curls"]["ok"] is True
    assert out["curls"]["count"] >= 1
    assert any("obs-log" in row["text"] for row in out["logs"]["entries"])
    assert out["shot"]["ok"] is True
    assert out["shot"]["path"].endswith(".png")
    assert out["pages"]["pages"][0]["active"] is True
    assert out["opened"]["ok"] is True
    assert out["switched"]["ok"] is True
    assert out["closed"]["ok"] is True
    assert len(out["closed"]["pages"]) == 1
    assert out["saved"]["cookies"] >= 0
    assert any(row["name"] == "itest" for row in out["states"]["states"])
    assert out["loaded"]["ok"] is True
    assert out["deleted"]["deleted"] is True
