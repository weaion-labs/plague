from __future__ import annotations

import asyncio
import http.server
import json
import threading

import plague.mcp_server as server
from plague.http import request


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self._reply()

    def do_POST(self):  # noqa: N802
        self._reply()

    def do_PATCH(self):  # noqa: N802
        self._reply()

    def _reply(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.dumps(
            {
                "method": self.command,
                "body": body,
                "cookie": self.headers.get("cookie") or "",
                "user_agent": self.headers.get("user-agent") or "",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "server=1; Path=/")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return None


def _start():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def test_http_request_posts_json_and_sets_chrome_user_agent():
    httpd, url = _start()
    try:
        result = asyncio.run(
            request("POST", url, json_body={"role": "admin"})
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert result["ok"] is True
    assert result["status"] == 200
    echoed = json.loads(result["body"])
    assert echoed["method"] == "POST"
    assert json.loads(echoed["body"]) == {"role": "admin"}
    assert "Chrome/" in echoed["user_agent"]
    assert result["headers"]["set-cookie"].startswith("server=1")


class FakeCookies:
    async def cookies(self, urls=None):
        return [{"name": "session", "value": "abc"}]


def test_api_request_reuses_warm_session_cookies():
    httpd, url = _start()
    key = "fast"
    server.RUNTIME._sessions[key] = server._Warm(
        session=FakeCookies(), last_used=0
    )
    try:
        result = asyncio.run(server.api_request("GET", url))
    finally:
        server.RUNTIME._sessions.pop(key, None)
        httpd.shutdown()
        httpd.server_close()

    assert result["ok"] is True
    assert result["cookies_used"] == 1
    echoed = json.loads(result["body"])
    assert "session=abc" in echoed["cookie"]
